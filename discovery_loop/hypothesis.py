"""Stage 2 — Hypothesis as a checkable object: H = (c, pi, d, a).

c  claim                — one testable sentence
pi plan                 — data / method / cost / runtime
d  decision criteria    — written BEFORE seeing results; quantitative, directional,
                          with an explicit "supports" / "weakens" mapping
a  alternatives         — at least one rival explanation that would also fit

Structural gate (mechanical, no LLM judgement):
  * all four components present and non-trivial
  * every decision criterion carries metric + direction + numeric threshold
  * every citation resolves to a paper fetched in THIS run, and its quote is
    verbatim-verified (run.verify_quote) — otherwise the hypothesis is rejected
  * criteria timestamp precedes any evaluation of the same hid (no post-hoc editing)
  * estimated cost within budget

The gate deliberately does NOT judge importance or novelty — those are not
decidable pre-execution (see docs chapter 11). Importance is adjudicated later by
data + subsequent literature, never by self-assessment.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field, asdict

from .core import Run, utcnow

BRANCHES = ("accuracy", "interpretation")
DIRECTIONS = (">", "<", "abs>", "median>", "group>", "corr<")


@dataclass
class Hypothesis:
    hid: str
    branch: str
    claim: str
    plan: dict
    decision_criteria: list[dict]
    alternatives: list[str]
    citations: list[dict] = field(default_factory=list)
    author: str = "boss"
    created_at: str = field(default_factory=utcnow)
    gate_status: str = "pending"
    gate_reasons: list[str] = field(default_factory=list)

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, indent=2)

    @staticmethod
    def from_json(txt: str) -> "Hypothesis":
        d = json.loads(txt)
        return Hypothesis(**{k: v for k, v in d.items() if k in Hypothesis.__dataclass_fields__})


def check_gate(run: Run, h: Hypothesis, budget_units: float = 1e9) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if h.branch not in BRANCHES:
        reasons.append(f"branch must be one of {BRANCHES}")
    if len(h.claim.strip()) < 25:
        reasons.append("claim too short / not a proposition (>=25 chars)")
    if not re.search(r"\d|显著|高于|低于|大于|小于|increase|decrease|higher|lower", h.claim, re.I):
        reasons.append("claim has no comparable predicate (no number or comparative)")

    if not h.decision_criteria:
        reasons.append("d: decision_criteria empty")
    for i, c in enumerate(h.decision_criteria):
        for key in ("metric", "direction", "threshold", "supports", "weakens"):
            if key not in c or c[key] in ("", None):
                reasons.append(f"d[{i}] missing '{key}'")
        if c.get("direction") not in DIRECTIONS:
            reasons.append(f"d[{i}] direction must be one of {DIRECTIONS}")
        thr = c.get("threshold")
        if not isinstance(thr, (int, float)):
            reasons.append(f"d[{i}] threshold must be numeric, got {type(thr).__name__}")

    if len([a for a in h.alternatives if len(a.strip()) > 8]) < 1:
        reasons.append("a: need at least one substantive alternative explanation")

    if not h.plan.get("data") or not h.plan.get("method"):
        reasons.append("pi: plan must specify data and method")
    est = h.plan.get("cost_estimate")
    if not isinstance(est, (int, float)):
        reasons.append("pi: cost_estimate must be numeric")
    elif est > budget_units:
        reasons.append(f"pi: cost_estimate {est} exceeds budget {budget_units}")

    if not h.citations:
        reasons.append("citations: none (verbatim-verified citations required)")
    for i, c in enumerate(h.citations):
        cid, quote = c.get("cite_id"), c.get("quote", "")
        if not cid or not quote:
            reasons.append(f"citation[{i}] needs cite_id and quote")
            continue
        ok, detail = run.verify_quote(cid, quote, used_by=h.hid)
        if not ok:
            reasons.append(f"citation[{i}] REJECTED: {detail.get('error', 'unverifiable')} ({cid})")

    # post-hoc guard
    row = run.db.execute(
        "SELECT MIN(created_at) t FROM evaluations WHERE hid=?", (h.hid,)).fetchone()
    if row and row["t"]:
        if h.created_at > row["t"]:
            reasons.append("d was written after results exist (post-hoc editing detected)")

    return (len(reasons) == 0), reasons


def register(run: Run, h: Hypothesis, budget_units: float = 1e9) -> tuple[bool, list[str]]:
    ok, reasons = check_gate(run, h, budget_units)
    h.gate_status = "pass" if ok else "reject"
    h.gate_reasons = reasons
    run.db.execute(
        """INSERT OR REPLACE INTO hypotheses
        (hid,branch,claim,plan,decision_criteria,alternatives,citations,
         gate_status,gate_reasons,created_at,decided_at,decision)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
        (h.hid, h.branch, h.claim, json.dumps(h.plan, ensure_ascii=False),
         json.dumps(h.decision_criteria, ensure_ascii=False),
         json.dumps(h.alternatives, ensure_ascii=False),
         json.dumps(h.citations, ensure_ascii=False),
         h.gate_status, json.dumps(reasons, ensure_ascii=False), h.created_at, utcnow(),
         "pending"),
    )
    run.db.commit()
    run.event("hypothesis", "gate", {"hid": h.hid, "status": h.gate_status, "reasons": reasons})
    p = run.dir / "hypotheses" / f"{h.hid}.json"
    p.write_text(h.to_json(), encoding="utf-8")
    return ok, reasons


# ---------------- blind pairwise scoring (Elo), kept separate from accuracy scores ----------------
def elo_update(run: Run, winner: str, loser: str, judge: str, note: str = "", k: float = 24.0) -> dict:
    """Blind = judge sees claims only, never the numeric val/test scores (enforced by prompt)."""
    run.db.executescript(
        """CREATE TABLE IF NOT EXISTS elo(hid TEXT PRIMARY KEY, rating REAL, wins INT, losses INT);"""
    )
    for hid in (winner, loser):
        run.db.execute("INSERT OR IGNORE INTO elo(hid,rating,wins,losses) VALUES(?,?,0,0)", (hid, 1400.0))
    rw = run.db.execute("SELECT rating FROM elo WHERE hid=?", (winner,)).fetchone()["rating"]
    rl = run.db.execute("SELECT rating FROM elo WHERE hid=?", (loser,)).fetchone()["rating"]
    exp_w = 1 / (1 + 10 ** ((rl - rw) / 400))
    new_w, new_l = rw + k * (1 - exp_w), rl + k * (0 - (1 - exp_w))
    run.db.execute("UPDATE elo SET rating=?, wins=wins+1 WHERE hid=?", (new_w, winner))
    run.db.execute("UPDATE elo SET rating=?, losses=losses+1 WHERE hid=?", (new_l, loser))
    run.db.commit()
    run.event("hypothesis", "pairwise", {"winner": winner, "loser": loser, "judge": judge,
                                         "delta": round(new_w - rw, 2), "note": note})
    return {"winner": round(new_w, 1), "loser": round(new_l, 1)}


def leaderboard(run: Run) -> list[dict]:
    try:
        rows = run.db.execute("SELECT * FROM elo ORDER BY rating DESC").fetchall()
    except Exception:
        return []
    return [dict(r) for r in rows]
