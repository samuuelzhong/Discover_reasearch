"""假设 novelty check（检索层）：七条 HM5 假设的先行工作扫描。

对每条假设用机制检索词组（领域话+外行话）跑 scout 真检索（OpenAlex/arXiv），
收集命中并输出 novelty_probe_results.json——检索层证据；
全文级验证（下载 nearest prior PDF + scout_pqa 问答）另步执行。

用法：python -m discovery_loop.novelty_check
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# 七条假设（H 四元取自 runs/c2-hypo-memo5，检索词按核心机制设计）
PROBES = {
    "HM5-1": {
        "claim": "按闭合误差分档差异化物理约束（软/严格）提升低闭合流域泛化",
        "queries": [
            "physics-constrained LSTM streamflow",
            "mass balance constraint deep learning",
            "water balance constraint runoff prediction",
            "physics loss poorly gauged basins",
            "consistency constraint hydrologic deep learning",
        ],
    },
    "HM5-2": {
        "claim": "SSM（状态空间/Mamba）主干对比 LSTM 的水文建模效率",
        "queries": [
            "Mamba rainfall-runoff",
            "state space model streamflow",
            "Mamba hydrology",
            "state space model rainfall runoff",
        ],
    },
    "HM5-3": {
        "claim": "MARRMoT 概念模型与 LSTM 的对照诊断",
        "queries": [
            "MARRMoT benchmark",
            "MARRMoT machine learning",
            "conceptual model LSTM comparison",
            "conceptual versus deep learning hydrology",
        ],
    },
    "HM5-4": {
        "claim": "GRACE 卫星数据作为驱动/对照源的水文建模",
        "queries": [
            "GRACE terrestrial water storage",
            "GRACE satellite streamflow",
            "GRACE LSTM runoff",
        ],
    },
    "HM5-5": {
        "claim": "conformal 预测区间逐流域覆盖审计",
        "queries": [
            "conformal prediction streamflow",
            "conformal prediction hydrology",
            "conformal prediction CAMELS",
            "prediction interval coverage rainfall runoff",
        ],
    },
    "HM5-6": {
        "claim": "临界慢化前兆统计（EWS）用于非平稳水文系统",
        "queries": [
            "early warning signals hydrology",
            "critical slowing down streamflow",
            "critical slowing down catchment",
            "regime shift early warning hydrological",
        ],
    },
    "HM5-7": {
        "claim": "SINDy 稀疏回归从水文数据中恢复控制方程",
        "queries": [
            "SINDy hydrology",
            "sparse identification hydrology",
            "symbolic regression rainfall runoff",
            "equation discovery catchment dynamics",
        ],
    },
}


def scout_search(run_id: str, query: str, n: int = 8) -> list[dict]:
    r = subprocess.run(
        [sys.executable, "-m", "discovery_loop.scout", "--run", run_id, "search", query, "--n", str(n)],
        cwd=str(ROOT), capture_output=True, text=True, timeout=180, encoding="utf-8", errors="replace",
    )
    if r.returncode != 0:
        return [{"error": (r.stderr or r.stdout)[-300:]}]
    hits = []
    for line in r.stdout.splitlines():
        line = line.strip()
        if not line or line.startswith(("run=", "queried", "recorded", "[")):
            continue
        hits.append(line[:400])
    return hits


def main():
    out = {}
    for hid, spec in PROBES.items():
        print(f"== {hid}: {spec['claim'][:40]}...", flush=True)
        results = []
        for q in spec["queries"]:
            hits = scout_search("novelty-hm5", q)
            results.append({"query": q, "n_raw": len(hits), "hits": hits[:8]})
            print(f"   [{q[:50]}] -> {len(hits)} raw", flush=True)
        out[hid] = {"claim": spec["claim"], "results": results}
    dest = ROOT / "discovery_loop" / "data" / "novelty_probe_results.json"
    dest.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nsaved -> {dest}")


if __name__ == "__main__":
    main()
