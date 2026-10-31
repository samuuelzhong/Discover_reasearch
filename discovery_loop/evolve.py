"""Stage 3b — Evolution engine (ShinkaEvolve-style, ~200 lines, auditable).

What is evolved: the *feature design* of a rainfall-runoff model (branch 1: accuracy).
What is recursively improved (the RSI part): the *mutation policy itself*. After each
generation we credit operators by the score delta they produced and re-weight sampling
(UCB1 bandit). So round k+1 searches better because of what round k learned — and this
is measurable: we log operator weights per generation.

Islands keep diversity: three selection objectives (median NSE / worst-basin NSE /
parsimony-adjusted NSE) so the population cannot collapse onto one template — the
failure mode DiscoveryRSI reports (restart rate collapsing, novelty dropping).
"""
from __future__ import annotations

import copy
import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np

from . import experiment as exp


@dataclass
class Individual:
    spec: list[tuple[str, dict]]
    score: float = -1e9
    test: float = float("nan")
    n_features: int = 0
    code_sha: str = ""
    origin: str = "seed"
    extra: dict = field(default_factory=dict)

    def code(self) -> str:
        return exp.render(self.spec)


def seed_specs() -> list[list[tuple[str, dict]]]:
    return [
        [("p_ewm", {"alpha": 0.1}), ("harm", {"k": 1})],
        [("p_ewm", {"alpha": 0.05}), ("pet_ewm", {"alpha": 0.05}), ("harm", {"k": 1})],
        [("p_lag", {"k": 1}), ("p_roll", {"w": 7}), ("t_ewm", {"alpha": 0.1}), ("harm", {"k": 2})],
    ]


def _rand_params(rng, name: str) -> dict:
    doc = exp.COMPONENTS[name][0]
    return {k: (float(rng.choice(v)) if isinstance(v[0], float) else int(rng.choice(v)))
            for k, v in doc.items()}


MUTATIONS = ("add", "remove", "tweak", "swap")


class OperatorPolicy:
    """UCB1 bandit over mutation operators — the recursively improved component."""

    def __init__(self, ops=MUTATIONS):
        self.ops = list(ops)
        self.n = {o: 1 for o in self.ops}
        self.wins = {o: 1.0 for o in self.ops}
        self.history: list[dict] = []

    def pick(self, rng) -> str:
        total = sum(self.n.values())
        ucb = {o: self.wins[o] / self.n[o] + 1.2 * math.sqrt(math.log(total) / self.n[o]) for o in self.ops}
        best = max(ucb, key=ucb.get)
        return best if rng.random() > 0.15 else rng.choice(self.ops)

    def credit(self, op: str, delta: float) -> None:
        self.n[op] += 1
        # squash delta into (0,1): positive improvements count more than equal losses
        self.wins[op] += 1.0 if delta > 0 else 0.3

    def snapshot(self) -> dict:
        return {o: round(self.wins[o] / self.n[o], 3) for o in self.ops}


def mutate(spec: list[tuple[str, dict]], op: str, rng) -> list[tuple[str, dict]]:
    s = [(n, dict(p)) for n, p in spec]
    present = {n for n, _ in s}
    if op == "add" or (op in ("tweak", "swap") and not s):
        pool = [c for c in exp.COMPONENTS if c not in present]
        if pool:
            name = rng.choice(pool)
            s.append((name, _rand_params(rng, name)))
    elif op == "remove" and len(s) > 1:
        s.pop(int(rng.integers(len(s))))
    elif op == "tweak" and s:
        i = int(rng.integers(len(s)))
        name = s[i][0]
        s[i] = (name, _rand_params(rng, name))
    elif op == "swap" and s:
        i = int(rng.integers(len(s)))
        pool = [c for c in exp.COMPONENTS if c not in present]
        if pool:
            name = rng.choice(pool)
            s[i] = (name, _rand_params(rng, name))
    return s


def _objective(res: dict, island: int) -> float:
    med, mean, worst = res["score_median"], res["score_mean"], res.get("neg_basins", 0)
    if island == 0:
        return med
    if island == 1:
        return 0.6 * med + 0.4 * mean - 0.02 * worst
    return med - 0.01 * res.get("n_features", 0)  # parsimony island


def run(
    frames: dict,
    out_dir: Path,
    generations: int = 3,
    pop_per_island: int = 4,
    islands: int = 3,
    seed: int = 0,
    on_eval: Callable[[dict], None] | None = None,
    log: Callable[[str], None] | None = None,
) -> dict:
    rng = np.random.default_rng(seed)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    policy = OperatorPolicy()
    pops: list[list[Individual]] = []
    seeds = seed_specs()
    for k in range(islands):
        pops.append([Individual(copy.deepcopy(seeds[k % len(seeds)]), origin="seed")])

    history: list[dict] = []
    evals = 0
    best_overall: Individual | None = None
    log = log or (lambda *_: None)

    def evaluate(ind: Individual, island: int) -> None:
        nonlocal evals, best_overall
        code = ind.code()
        res = exp.evaluate_code(code, frames, metric_split="val")
        evals += 1
        if not res.get("ok"):
            ind.score = -1e9
            return
        ind.score = _objective(res, island)
        ind.test = res["test_median"]
        ind.n_features = res["n_features"]
        ind.code_sha = res["code_sha"]
        ind.extra = {k: res[k] for k in ("score_median", "score_mean", "test_median",
                                        "kge_test_median", "seconds", "n_basins", "neg_basins")}
        if on_eval:
            on_eval({"island": island, **ind.extra, "sha": ind.code_sha, "n_features": ind.n_features})
        # Selection uses the val median ONLY. test is recorded purely for reporting; letting
        # it decide which candidate survives would leak the holdout (this was a real bug in
        # v0.1: best_overall was picked by test score across all 39 candidates).
        val_med = float(res["score_median"])
        prev = best_overall.extra.get("score_median", -9e9) if best_overall else -9e9
        better = val_med > prev + 1e-12
        tie = abs(val_med - prev) <= 1e-12 and best_overall is not None and ind.n_features < best_overall.n_features
        if best_overall is None or better or tie:
            cand = Individual(copy.deepcopy(ind.spec), ind.score, ind.test, ind.n_features,
                              ind.code_sha, ind.origin, dict(ind.extra))
            best_overall = cand

    for isl, pop in enumerate(pops):
        for ind in pop:
            evaluate(ind, isl)

    for g in range(generations):
        gen_rec = {"generation": g + 1, "policy": policy.snapshot(), "islands": []}
        for isl, pop in enumerate(pops):
            pop.sort(key=lambda x: x.score, reverse=True)
            elite = pop[0]
            children: list[Individual] = []
            for _ in range(pop_per_island):
                op = policy.pick(rng)
                parent = elite if rng.random() < 0.6 else pop[int(rng.integers(len(pop)))]
                child = Individual(mutate(parent.spec, op, rng), origin=op)
                before = parent.score
                evaluate(child, isl)
                policy.credit(op, child.score - before)
                children.append(child)
            merged = (pop + children)
            merged.sort(key=lambda x: x.score, reverse=True)
            keep, seen = [], set()
            for ind in merged:  # diversity filter: dedupe by spec signature
                sig = json.dumps(ind.spec, sort_keys=True, default=str)
                if sig in seen:
                    continue
                seen.add(sig)
                keep.append(ind)
                if len(keep) >= pop_per_island:
                    break
            pops[isl] = keep
            gen_rec["islands"].append({
                "island": isl,
                "best_val": round(keep[0].extra.get("score_median", float("nan")), 4) if keep[0].extra else None,
                "best_test": round(keep[0].test, 4),
                "n_features": keep[0].n_features,
                "spec": keep[0].spec,
            })
            log(f"  gen {g+1} island {isl}: val={keep[0].extra.get('score_median'):.4f} "
                f"test={keep[0].test:.4f} feats={keep[0].n_features} spec={keep[0].spec}")
        history.append(gen_rec)
        (out_dir / "history.json").write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")

    assert best_overall is not None
    best_code = best_overall.code()
    (out_dir / "best_candidate.py").write_text(best_code, encoding="utf-8")
    final = exp.evaluate_code(best_code, frames, metric_split="test", detail=True)
    exp.archive(out_dir / "best_eval", best_code, final)
    summary = {
        "evals": evals,
        "generations": generations,
        "islands": islands,
        "operator_policy_final": policy.snapshot(),
        "history": history,
        "best_spec": best_overall.spec,
        "best_val_median": best_overall.extra.get("score_median"),
        "best_test_median": final.get("test_median"),
        "best_kge_test_median": final.get("kge_test_median"),
        "best_n_features": final.get("n_features"),
        "best_code_sha": final.get("code_sha"),
        "n_basins": final.get("n_basins"),
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary
