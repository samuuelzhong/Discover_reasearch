"""agent 循环的检索执行器（工具层）：读 agent 写的计划文件，执行真检索。

用法：python discovery_loop/agent_round.py <round_key>
计划文件：data/agent_plan_<round_key>.json
    {"HM5-1": ["query1", "query2"], ...}
输出：data/agent_<round_key>.json（原始命中，供 agent 语义判读）
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from discovery_loop.hypo_evolve import scout_search  # noqa: E402


def main(round_key: str):
    plan_path = ROOT / "discovery_loop" / "data" / f"agent_plan_{round_key}.json"
    if not plan_path.exists():
        print(f"plan file missing: {plan_path}")
        return 1
    queries = json.loads(plan_path.read_text(encoding="utf-8"))
    out = {}
    for hid, qs in queries.items():
        out[hid] = []
        for q in qs:
            hits = scout_search(q, run=f"hypo-evolve-{round_key}")
            out[hid].append({"query": q, "hits": hits})
            print(f"{hid} [{q}] -> {len(hits)}", flush=True)
            time.sleep(1.5)  # API 礼貌
    dest = ROOT / "discovery_loop" / "data" / f"agent_{round_key}.json"
    dest.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"saved -> {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else ""))
