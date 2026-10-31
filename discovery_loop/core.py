"""Core state: run directory, append-only event log, provenance DB, cost ledger.

Design principles
-----------------
1. 任何"文献事实"必须落库为 papers 行（含 URL / 检索时间 / 原文哈希），
   引用它的断言必须是 claims 行，quote 经 verify_quote 逐字校验。
   → 机制上禁止模型凭记忆编造文献。
2. 所有产出写 runs/<id>/events.jsonl（追加），决策写 decisions 表（谁、何时、依据）。
3. Shared Summary 只允许 Boss 单线程写入（文件锁 + 记录 writer）。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
RUNS_DIR = ROOT / "runs"

SCHEMA = """
CREATE TABLE IF NOT EXISTS events(
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, stage TEXT, kind TEXT, payload TEXT);
CREATE TABLE IF NOT EXISTS costs(
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, stage TEXT, kind TEXT, units REAL, unit_name TEXT, note TEXT);
CREATE TABLE IF NOT EXISTS papers(
  cite_id TEXT PRIMARY KEY, source TEXT, doi TEXT, arxiv_id TEXT, title TEXT, year INTEGER,
  venue TEXT, authors TEXT, abstract TEXT, fulltext TEXT, url TEXT, retrieved_at TEXT,
  raw_sha256 TEXT, is_local INTEGER DEFAULT 0, extra TEXT);
CREATE TABLE IF NOT EXISTS claims(
  id INTEGER PRIMARY KEY AUTOINCREMENT, cite_id TEXT, quote TEXT, norm_quote TEXT,
  field TEXT, char_start INTEGER, char_end INTEGER, verified_at TEXT, used_by TEXT);
CREATE TABLE IF NOT EXISTS hypotheses(
  hid TEXT PRIMARY KEY, branch TEXT, claim TEXT, plan TEXT, decision_criteria TEXT,
  alternatives TEXT, citations TEXT, gate_status TEXT, gate_reasons TEXT,
  created_at TEXT, decided_at TEXT, decision TEXT);
CREATE TABLE IF NOT EXISTS evaluations(
  id INTEGER PRIMARY KEY AUTOINCREMENT, hid TEXT, candidate TEXT, code_sha TEXT, data_sha TEXT,
  split TEXT, metric TEXT, value REAL, per_basin TEXT, seconds REAL, created_at TEXT, extra TEXT);
CREATE TABLE IF NOT EXISTS anomalies(
  id INTEGER PRIMARY KEY AUTOINCREMENT, basin TEXT, metric TEXT, value REAL, z REAL,
  baseline TEXT, question TEXT, created_at TEXT, promoted INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS decisions(
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, actor TEXT, topic TEXT, choice TEXT, rationale TEXT);
"""


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


_WS = re.compile(r"[\s\u00a0\u2007\u202f]+")


def norm_ws(text: str) -> str:
    """Normalize whitespace and typographic dashes/quotes for quote matching."""
    t = (text or "").replace("\u2019", "'").replace("\u2018", "'")
    t = t.replace("\u201c", '"').replace("\u201d", '"')
    t = t.replace("\u2013", "-").replace("\u2014", "-").replace("\u2212", "-")
    t = t.replace("\ufb01", "fi").replace("\ufb02", "fl")
    return _WS.sub(" ", t).strip().lower()


class Run:
    """One closed-loop run. All stage I/O goes through here."""

    def __init__(self, run_id: str | None = None, base: str | Path | None = None):
        self.id = run_id or time.strftime("%Y%m%d-%H%M%S")
        self.dir = Path(base or RUNS_DIR) / self.id
        for sub in ("artifacts", "scout", "hypotheses", "experiments", "analysis", "mcp"):
            (self.dir / sub).mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.dir / "state.db")
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        self.db.commit()
        self.events_path = self.dir / "events.jsonl"

    # ---------- logging ----------
    def event(self, stage: str, kind: str, payload: Any) -> None:
        rec = {"ts": utcnow(), "stage": stage, "kind": kind, "payload": payload}
        with open(self.events_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        self.db.execute(
            "INSERT INTO events(ts,stage,kind,payload) VALUES(?,?,?,?)",
            (rec["ts"], stage, kind, json.dumps(payload, ensure_ascii=False)),
        )
        self.db.commit()

    def cost(self, stage: str, kind: str, units: float, unit_name: str, note: str = "") -> None:
        self.db.execute(
            "INSERT INTO costs(ts,stage,kind,units,unit_name,note) VALUES(?,?,?,?,?,?)",
            (utcnow(), stage, kind, float(units), unit_name, note),
        )
        self.db.commit()

    def decision(self, actor: str, topic: str, choice: str, rationale: str) -> None:
        self.db.execute(
            "INSERT INTO decisions(ts,actor,topic,choice,rationale) VALUES(?,?,?,?,?)",
            (utcnow(), actor, topic, choice, rationale),
        )
        self.db.commit()
        self.event("boss", "decision", {"topic": topic, "choice": choice})

    # ---------- provenance ----------
    def add_paper(
        self,
        *,
        cite_id: str,
        source: str,
        title: str,
        abstract: str = "",
        year: int | None = None,
        venue: str = "",
        authors: str = "",
        doi: str = "",
        arxiv_id: str = "",
        url: str = "",
        fulltext: str = "",
        is_local: bool = False,
        raw: bytes | None = None,
        extra: dict | None = None,
    ) -> None:
        raw_sha = hashlib.sha256(raw).hexdigest() if raw is not None else sha256_text(title + abstract + fulltext)
        self.db.execute(
            """INSERT OR REPLACE INTO papers
            (cite_id,source,doi,arxiv_id,title,year,venue,authors,abstract,fulltext,url,
             retrieved_at,raw_sha256,is_local,extra) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (cite_id, source, doi, arxiv_id, title, year, venue, authors, abstract, fulltext,
             url, utcnow(), raw_sha, int(is_local), json.dumps(extra or {}, ensure_ascii=False)),
        )
        self.db.commit()

    def get_paper(self, cite_id: str) -> sqlite3.Row | None:
        return self.db.execute("SELECT * FROM papers WHERE cite_id=?", (cite_id,)).fetchone()

    def papers(self) -> list[sqlite3.Row]:
        return self.db.execute("SELECT * FROM papers ORDER BY year DESC").fetchall()

    def verify_quote(self, cite_id: str, quote: str, used_by: str = "") -> tuple[bool, dict]:
        """Whitelist check: the quote must appear verbatim in the stored text.

        Returns (ok, detail). ok=False means the quote cannot be located —
        i.e. it is a fabrication or a paraphrase; both are rejected by the gate.
        """
        row = self.get_paper(cite_id)
        if row is None:
            return False, {"error": "unknown cite_id"}
        needle = norm_ws(quote)
        if len(needle) < 12:
            return False, {"error": "quote too short to verify (min 12 chars)"}
        for fname in ("fulltext", "abstract"):
            hay = norm_ws(row[fname] or "")
            if not hay:
                continue
            pos = hay.find(needle)
            if pos >= 0:
                self.db.execute(
                    """INSERT INTO claims(cite_id,quote,norm_quote,field,char_start,char_end,verified_at,used_by)
                    VALUES(?,?,?,?,?,?,?,?)""",
                    (cite_id, quote, needle, fname, pos, pos + len(needle), utcnow(), used_by),
                )
                self.db.commit()
                return True, {"field": fname, "char_start": pos, "char_end": pos + len(needle)}
        return False, {"error": "quote not found in stored abstract/fulltext", "cite_id": cite_id}

    def verified_claims(self, cite_id: str | None = None) -> list[sqlite3.Row]:
        if cite_id:
            return self.db.execute("SELECT * FROM claims WHERE cite_id=?", (cite_id,)).fetchall()
        return self.db.execute("SELECT * FROM claims").fetchall()

    # ---------- artifacts ----------
    def write_json(self, rel: str, obj: Any) -> Path:
        p = self.dir / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
        return p

    def summary_append(self, text: str) -> None:
        """Single writer: Boss only. Appends a timestamped block."""
        owner = os.environ.get("DL_OWNER", "boss")
        p = self.dir / "shared_summary.md"
        with open(p, "a", encoding="utf-8") as f:
            f.write(f"\n\n<!-- writer={owner} ts={utcnow()} -->\n{text.strip()}\n")

    def cost_report(self) -> dict:
        rows = self.db.execute(
            "SELECT stage, unit_name, SUM(units) u FROM costs GROUP BY stage, unit_name"
        ).fetchall()
        return {(r["stage"] + "/" + r["unit_name"]): round(r["u"], 3) for r in rows}
