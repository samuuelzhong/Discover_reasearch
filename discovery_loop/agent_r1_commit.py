"""Round 1 agent 判断写回池 + STOP 裁决（判断由 agent 产出，本脚本只做持久化）。"""
import json
import time
from pathlib import Path

POOL = Path(r"E:\multiagent\discovery_loop\data\hypo_pool.json")
LOG = Path(r"E:\multiagent\discovery_loop\data\hypo_evolve_log.jsonl")

R1_JUDGMENTS = {
    "HM5-1": {
        "priors": [
            {"cite_id": "arxiv:2104.06217", "title": "Self-adaptive loss balanced PINNs", "year": "2021",
             "note": "adaptive weighting 在 PINN 成熟；无水文应用"},
            {"cite_id": "arxiv:2509.25262", "title": "AW-EL-PINNs multi-task adaptive weighting", "year": "2025",
             "note": "加权机制工具箱"},
        ],
        "delta": "adaptive loss weighting 是 PINN/CFD 成熟机制（12 命中全非水文），"
                 "basin-wise 加权 0 命中——delta 精化为：将 PINN 自适应加权思想迁移到"
                 "水文闭合约束的流域分档（大样本 LSTM 场景空白）",
        "status": "refined",
        "reason": "检索判读：adaptive weighting 邻域密集但水文×LSTM 空白，delta 收窄且方法路径明确",
    },
    "HM5-2": {
        "priors": [
            {"cite_id": "arxiv:2501.14980", "title": "Deep State Space Model for Rainfall-Runoff (S4D)", "year": "2025",
             "note": "全文级确认：无效率测量（paperqa_cited）"},
            {"cite_id": "arxiv:2505.22535", "title": "RiverMamba", "year": "2025",
             "note": "全文级确认：无 LSTM 效率对比，非 CAMELS（paperqa_cited）"},
        ],
        "delta": "效率维度双 prior 全文级确认空白：S4D（区域 CAMELS）只答精度，"
                 "RiverMamba（全球）只报自身算力（16xA100x3d）无 LSTM 对比——"
                 "水文 SSM×LSTM 训练/推理效率对照确认无人做过",
        "status": "refined",
        "reason": "RiverMamba 全文级查询后效率 delta 双确认，文献层无可再挖",
    },
    "HM5-6": {
        "delta": "第二话语系（tipping points/CSD water）复扫：CSD 存在于水物理/多孔介质领域，"
                 "水文 streamflow 非平稳场景空白保持",
        "status": "novelty_probed",
        "reason": "话语系切换后 novel 判定二次确认，置信度提升",
    },
    "HM5-7": {
        "priors": [
            {"cite_id": "arxiv:2601.08116", "title": "Learning a Stochastic DE Model of Tropical Cyclone Intensity", "year": "2026",
             "note": "环境系统 SDE 数据驱动发现的方法先例（非水文）"},
        ],
        "delta": "novel 判定保持：环境邻域有 SDE 发现先例（方法可迁移），水文径流控制方程 SINDy 空白",
        "status": "novelty_probed",
        "reason": "获得邻域方法先例，novel 维持且路径更清晰",
    },
    "H6-a": {"delta": "两查询命中无覆盖×闭合关联工作，空白保持", "status": "novelty_probed",
             "reason": "空白确认，且 HM5-1 残差即将可检验"},
    "H6-b": {"delta": "regime-dependent 语义存在于两相流（2026），水文 regime×约束空白保持",
             "status": "novelty_probed", "reason": "空白确认"},
    "H6-c": {"delta": "WSINDy 命中为伪科学库噪声；EWS×SINDy 交叉空白保持",
             "status": "novelty_probed", "reason": "空白确认"},
}

STOP_VERDICT = {
    "ev": "hypo_evolve.stop_verdict",
    "round": 1,
    "decision": "STOP 假设层 RSI，转入实验验证（R20）",
    "dialectic_reasoning": {
        "Q1_文献边际信息": "两轮语义判读+三次全文级后，池内新信息仅剩 HM5-1 的 PINN-weighting "
                      "具体设计——这属于实验设计阶段的方法调研（实验环内 align_probe 可回询），"
                      "非假设层问题。连续判读产出均为'空白确认/邻域精化'，claim 层信息增量趋零。",
        "Q2_可检验形态": "HM5-1（CAMELS+NH 栈+MCP 工具全在库）✓；H6-a/b（搭 HM5-1 残差）✓；"
                    "H6-c（合成原型+ews/sindy 在库）✓；HM5-6/7（残差首验）✓。"
                    "HM5-2 缺 Mamba 环境（工程问题非文献问题）；HM5-4 缺 GRACE 数据（资源问题，deferred 在案）。",
        "Q3_边际价值对比": "继续检索的预期增量 < 实验产出：HM5-1 三档实验将生成残差与分档证据，"
                      "直接反哺 H6-a/b 检验与 HM5-6/7 残差首验——下一波信息增益在实验侧而非文献侧。",
    },
    "residual_risks": "OpenAlex 精确短语的书脊式漏检风险仍在；H6 空白判定为检索级"
                   "（非全文级），正式 hyp.proposed 时需 blank_probe 升级。",
}

pool = json.loads(POOL.read_text(encoding="utf-8"))
for h in pool:
    j = R1_JUDGMENTS.get(h["hid"])
    if not j:
        continue
    if j.get("priors"):
        known = {p["cite_id"] for p in h.get("nearest_prior", [])}
        h["nearest_prior"] = h.get("nearest_prior", []) + [
            p for p in j["priors"] if p["cite_id"] not in known]
    h["delta"] = j["delta"]
    h["status"] = j["status"]
    h.setdefault("history", []).append(
        {"round": 1, "action": "agent_judgment", "note": j["reason"]})
POOL.write_text(json.dumps(pool, ensure_ascii=False, indent=1), encoding="utf-8")

with LOG.open("a", encoding="utf-8") as f:
    f.write(json.dumps({**STOP_VERDICT, "ts": time.strftime("%Y-%m-%dT%H:%M:%S")},
                       ensure_ascii=False) + "\n")

print("pool updated + stop verdict logged")
for h in pool:
    print(f"{h['hid']:6s} {h['status']:14s} {h['verification_status']:16s} prior={len(h.get('nearest_prior', []))}")
