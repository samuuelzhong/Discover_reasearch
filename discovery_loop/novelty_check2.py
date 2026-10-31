"""发散检索（novelty 审计后的再发散）：验证三条交叉假设线的空白状态。

用法：python -m discovery_loop.novelty_check2
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

CROSSES = {
    "X1-regime-closure-constraint": {
        "rationale": "机制依赖的约束价值（2026 命中）×闭合/regime 条件化约束注入——分档思想向 regime/闭合条件扩展",
        "queries": [
            "closure error basin conditioning",
            "regime dependent physical constraint",
            "water balance residual conditioning LSTM",
            "adaptive constraint closure error",
            "error stratified physics constraint",
        ],
    },
    "X2-coverage-closure": {
        "rationale": "Alsafari per-basin coverage × 闭合误差关联——覆盖异质性是否由闭合质量驱动",
        "queries": [
            "coverage water balance error",
            "prediction interval closure quality",
            "coverage stratified catchment attributes",
            "uncertainty closure error hydrology",
            "interval width basin closure",
        ],
    },
    "X3-ews-sindy": {
        "rationale": "两条 novel 线交叉：临界慢化前兆统计的稀疏回归自动发现",
        "queries": [
            "early warning sparse regression",
            "critical transition equation discovery",
            "SINDy early warning",
            "sparse regression regime shift detection",
            "automated precursor discovery hydrology",
        ],
    },
}


def scout_search(run_id: str, query: str, n: int = 6) -> list[str]:
    r = subprocess.run(
        [sys.executable, "-m", "discovery_loop.scout", "--run", run_id, "search", query, "--n", str(n)],
        cwd=str(ROOT), capture_output=True, text=True, timeout=180, encoding="utf-8", errors="replace",
    )
    if r.returncode != 0:
        return [f"ERROR: {(r.stderr or r.stdout)[-200:]}"]
    hits = []
    for line in r.stdout.splitlines():
        line = line.strip()
        if line:
            hits.append(line[:300])
    return hits


def main():
    out = {}
    for xid, spec in CROSSES.items():
        print(f"== {xid}: {spec['rationale'][:50]}...", flush=True)
        results = []
        for q in spec["queries"]:
            hits = scout_search("novelty-hm5-x", q)
            results.append({"query": q, "hits": hits})
            print(f"   [{q[:48]}] -> {len(hits)} raw", flush=True)
        out[xid] = {"rationale": spec["rationale"], "results": results}
    dest = ROOT / "discovery_loop" / "data" / "novelty_cross_results.json"
    dest.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nsaved -> {dest}")


if __name__ == "__main__":
    main()
