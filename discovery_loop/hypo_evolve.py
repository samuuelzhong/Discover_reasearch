"""假设池工具层（纯工具，零判断——判断归 agent，协议见下）。

架构分层（2026-10-31 用户纠正后固化）：
    工具层（本文件）：池 I/O / 检索执行 / 留痕 / 状态字段——机械
    判断层（agent）：检索词设计 / 语义判读 / delta 精化 / 终止裁决——智能辩证

Agent 驱动循环协议（每个循环轮次）：
    1. agent 读 hypo_pool.json，自主设计检索计划 → data/agent_plan.json
    2. agent 运行 python discovery_loop/agent_round.py <round_key> 执行真检索
    3. agent 逐条语义判读命中（真先例/邻域/噪声——不用词表替代判断）
    4. agent 判断写回池（nearest_prior/delta/status/history 留理由）
    5. 终止裁决：agent 回答三个辩证问题（文献边际信息/可检验形态/检索vs实验
       边际价值），STOP+理由写入 hypo_evolve_log.jsonl——可审计，非规则触发

禁止事项：
    - 禁止在脚本内做"机械判读"（词表匹配替代语义判断）——历史教训：机械版
      --loop 曾向池塞入 22 个未判读 prior（2026-10-31 已清洗，理由在 history）
    - 禁止静默删除池内记录（清洗必须带判断理由入 history）
    - 种子导入必须标注人工来源（seed from 人工轮），循环内零人工

用法：
    python -m discovery_loop.hypo_evolve status     # 池状态查看（唯一 CLI）
    python discovery_loop/agent_round.py <round>    # agent 的检索执行器
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POOL_PATH = ROOT / "discovery_loop" / "data" / "hypo_pool.json"
LOG_PATH = ROOT / "discovery_loop" / "data" / "hypo_evolve_log.jsonl"

# 参考过滤（仅辅助 agent 预筛，不替代判读）
DOMAIN_WORDS = {
    "hydrolog", "streamflow", "runoff", "rainfall", "catchment", "basin",
    "camels", "lstm", "discharge", "precipitation", "snow", "flood",
    "water balance", "mass balance", "soil moisture", "evapotranspiration",
}


def load_pool() -> list[dict]:
    if POOL_PATH.exists():
        return json.loads(POOL_PATH.read_text(encoding="utf-8"))
    return []


def save_pool(pool: list[dict]) -> None:
    POOL_PATH.parent.mkdir(parents=True, exist_ok=True)
    POOL_PATH.write_text(json.dumps(pool, ensure_ascii=False, indent=1), encoding="utf-8")


def log_event(ev: dict) -> None:
    ev["ts"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(ev, ensure_ascii=False) + "\n")


def scout_search(query: str, run: str = "hypo-evolve", n: int = 6) -> list[dict]:
    """真检索（scout TSV 解析）。返回结构化命中供 agent 语义判读。"""
    r = subprocess.run(
        [sys.executable, "-m", "discovery_loop.scout", "--run", run,
         "search", query, "--n", str(n)],
        cwd=str(ROOT), capture_output=True, text=True, timeout=180,
        encoding="utf-8", errors="replace",
    )
    hits = []
    if r.returncode == 0:
        for line in r.stdout.splitlines():
            line = line.strip()
            if line and "\t" in line:
                parts = line.split("\t", 2)
                if len(parts) >= 3:
                    hits.append({"cite_id": parts[0], "year": parts[1], "title": parts[2]})
    return hits


def relevance_hint(title: str) -> int:
    """领域词命中数——只是 agent 判读的参考信号，不是判定。"""
    t = title.lower()
    return sum(1 for w in DOMAIN_WORDS if w in t)


def main():
    pool = load_pool()
    for h in pool:
        print(f"{h['hid']:6s} {h.get('formal_status','-'):14s} {h['status']:14s} "
              f"{h.get('verification_status','-'):16s} prior={len(h.get('nearest_prior', []))} "
              f"| {h['claim'][:44]}")


if __name__ == "__main__":
    main()
