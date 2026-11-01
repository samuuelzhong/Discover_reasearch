"""可执行研究主线（冷启动协议）——把 README 的叙事级路线变成强制执行级。

为什么存在
----------
路线原来只写在 README/docstring（叙事级），接手者（人或另一台机器的 agent）
会顺着 runs/ 台账与既有假设池继续跑——2026-11-01 实际发生：换域任务直接
"接着既有池做"。本模块把路线固化为带门槛的状态机：

    s1_scout       文献检索入库（scout 多源：openalex+arxiv+s2）
    s1b_synthesize 精读+fieldmap 综合（领域画像/流派/机制图谱）
    s2_xdomain     跨域发散（fieldmap --domain，类比域抓回入库）
    s3_hypothesis  假设环（hypo_evolve 池循环 → 三辩证问题 STOP）
    s4_experiment  预注册裁决协议（只在 s3 STOP 后解锁；须先 gate 登记三层基线）
    s5_p2a         按假设需求内化数据/工具/基线（可前置作基座，或实验后沉淀）

规矩（与 README 设计原则一致）：
  - 文献在前：s1 未 done 之前 s3 拒绝执行（agent_round 会调 guard）
  - 池按域隔离：hypo_pool_<domain>.json，新域天然拿不到旧池
  - 实验在假设 STOP 之后：s4 的门槛是 s3 done
  - 基座门禁（2026-11-01 用户裁决）：实验不得在无基座/基线时开展——s4 guard
    要求先 `gate` 登记三层基线（消融/SOTA/sanity）及其内化来源。理由：不内化
    基座则增益与种子/协议抖动统计不可分；自建弱对照会制造"假领先"；半合成
    实验必须以真实论文的过程模型注入信号，自建模型注入=循环验证。p2a 由此
    按需前置（SP 类性能声明线先内化基座再实验；SC/SW 线可实验后沉淀资产）
  - 遗留域 "hydro"（主线启用前的既有池）无台账时警告放行，但每次可见

基础链条 ≠ 检索边界（2026-11-01 用户明确）：
  六阶段只是"首次覆盖"的基础链条；文献检索/跨域发散/引文回调是**全阶段常驻
  服务**——知识综合、假设提出与优化、实验验证与分析的任何时刻，都可以再调研、
  换角度补查、回调源论文。假设环本身每轮就是新检索计划（这就是补查）。用
  `refine` 把每次补查登记入台账（带"补查时所处的阶段"），留痕可审计。

用法：
  python discovery_loop/pipeline.py newdomain <域>       # 冷启动（拒绝覆盖已有域）
  python discovery_loop/pipeline.py status <域>          # 进度 + 下一步
  python discovery_loop/pipeline.py done <域> <阶段> "证据/理由"
  python discovery_loop/pipeline.py guard <域> <阶段>    # 门槛检查（0/1）——只拦跳步，不限制后续补查
  python discovery_loop/pipeline.py gate <域> "三层基线登记"  # s4 基座门禁：消融臂/SOTA基座(内化来源)/sanity
  python discovery_loop/pipeline.py refine <域> "为何补查/换了什么角度/查到什么"
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "discovery_loop" / "data"

STAGES = [
    ("s1_scout",       "文献检索入库（scout 多源：openalex+arxiv+s2）"),
    ("s1b_synthesize", "精读 + fieldmap 综合（领域画像/流派/机制图谱）"),
    ("s2_xdomain",     "跨域发散（fieldmap --domain，类比域抓回入库）"),
    ("s3_hypothesis",  "假设环（hypo_evolve 池循环 → 三辩证问题 STOP）"),
    ("s4_experiment",  "预注册裁决协议（s3 STOP 后解锁；须先 gate 登记三层基线——基座门禁）"),
    ("s5_p2a",         "按假设需求内化数据/工具/基线（可前置于 s4 作基座，或实验后沉淀资产）"),
]
LEGACY_DOMAIN = "hydro"  # 既有池所属域（主线启用前已存在）


def route_path(domain: str) -> Path:
    return DATA / f"route_{domain}.json"


def _idx(stage: str) -> int:
    for i, (k, _) in enumerate(STAGES):
        if k == stage:
            return i
    raise SystemExit(f"unknown stage: {stage}; known: {[k for k, _ in STAGES]}")


def _load_route(domain: str) -> dict | None:
    p = route_path(domain)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def _next_pending(route: dict) -> str | None:
    return next((k for k, _ in STAGES if route["stages"].get(k, {}).get("status") != "done"), None)


def _print_route(route: dict) -> None:
    print(f"主线 {route['domain']}（{route.get('created', '?')} 创建，{route.get('protocol', '?')}）：")
    for k, desc in STAGES:
        st = route["stages"].get(k, {})
        mark = "[done]    " if st.get("status") == "done" else "[pending] "
        note = f"  # {st['note']}" if st.get("note") else ""
        print(f"  {mark}{k:14s} {desc}{note}")
    for r in route.get("refinements", []):
        print(f"  [refine@{r['at_stage']}] {r['ts']}  # {r['note']}")


def cmd_newdomain(a) -> int:
    domain = a.domain
    if domain == LEGACY_DOMAIN:
        raise SystemExit(f"域 '{domain}' 是遗留域（既有池所有者）；新任务请用新域名，遗留池不可被冷启动覆盖")
    pool = DATA / f"hypo_pool_{domain}.json"
    if route_path(domain).exists() or pool.exists():
        raise SystemExit(f"域 '{domain}' 已有主线台账或假设池 —— 已有任务，拒绝冷启动覆盖；"
                         f"查看进度：python discovery_loop/pipeline.py status {domain}")
    route = {"domain": domain, "protocol": "cold-start-v1", "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
             "stages": {k: {"status": "pending", "note": None, "ts": None} for k, _ in STAGES}}
    route_path(domain).write_text(json.dumps(route, ensure_ascii=False, indent=1), encoding="utf-8")
    pool.write_text("[]", encoding="utf-8")
    print(f"域 '{domain}' 冷启动完成：路线台账 route_{domain}.json + 空假设池 hypo_pool_{domain}.json")
    _print_route(route)
    print("\n规矩：文献在前、实验在假设 STOP 之后，禁止跳步。"
          "\n下一步：python -m discovery_loop.scout --run <run_id> search <query> --n 10（默认 openalex+arxiv+s2 源）"
          "\n完成后：python discovery_loop/pipeline.py done <域> s1_scout \"<证据：run_id/查询数/入库数>\""
          "\n（假设环判读写回一律带 domain=<域>，新域拿不到旧池）")
    return 0


def cmd_status(a) -> int:
    route = _load_route(a.domain)
    if route is None:
        if a.domain == LEGACY_DOMAIN:
            print(f"域 '{a.domain}' 无主线台账（主线启用前的遗留任务）——仅提示不阻断")
            return 0
        raise SystemExit(f"域 '{a.domain}' 无主线台账——先冷启动：pipeline.py newdomain {a.domain}")
    _print_route(route)
    print(f"\n当前应做：{_next_pending(route) or '全部完成'}")
    return 0


def cmd_done(a) -> int:
    route = _load_route(a.domain)
    if route is None:
        raise SystemExit(f"域 '{a.domain}' 无主线台账——先冷启动：pipeline.py newdomain {a.domain}")
    route["stages"][a.stage] = {"status": "done", "note": a.note, "ts": time.strftime("%Y-%m-%dT%H:%M:%S")}
    route_path(a.domain).write_text(json.dumps(route, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"done: {a.stage}  # {a.note}\n下一步：{_next_pending(route) or '全部完成'}")
    return 0


def cmd_gate(a) -> int:
    """基座门禁登记：s4 实验前必须登记三层基线及其内化来源（判断归 agent，机械归工具层）。

    三层（缺一会被审稿人击破）：
      消融基线——证明机制存在（对照臂来自文献判读锁定的 nearest_prior）
      SOTA 外部基线——证明性能领先（内化自关键论文复现，含完整评测协议）
      sanity 基线——防所有臂都不比 chance 好（climatology/线性回归）
    """
    route = _load_route(a.domain)
    if route is None:
        raise SystemExit(f"域 '{a.domain}' 无主线台账——先冷启动：pipeline.py newdomain {a.domain}")
    if "baseline_gate" in route:
        raise SystemExit(f"域 '{a.domain}' 已有基座门禁登记（重新登记请先手工清理 route_{a.domain}.json 的 baseline_gate 字段）")
    route["baseline_gate"] = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "note": a.note}
    route_path(a.domain).write_text(json.dumps(route, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"gate 登记完成：{a.note}")
    return 0


def guard(domain: str, stage: str, quiet: bool = False) -> None:
    """线性主线门槛：前置阶段未 done 则拒绝。agent_round 在假设环前调用。"""
    route = _load_route(domain)
    if route is None:
        if domain == LEGACY_DOMAIN:
            if not quiet:
                print(f"[guard] 域 '{domain}' 无主线台账（遗留任务）——警告放行", file=sys.stderr)
            return
        raise SystemExit(
            f"[guard] 域 '{domain}' 无主线台账——禁止直接做 {stage}。\n"
            f"冷启动：python discovery_loop/pipeline.py newdomain {domain}（文献在前是 README 明文规矩）")
    for k, _ in STAGES[:_idx(stage)]:
        if route["stages"].get(k, {}).get("status") != "done":
            raise SystemExit(
                f"[guard] 域 '{domain}' 前置阶段 {k} 未 done——禁止跳步做 {stage}。\n"
                f"查进度：python discovery_loop/pipeline.py status {domain}")
    if stage == "s4_experiment" and "baseline_gate" not in route:
        raise SystemExit(
            "[guard] s4 基座门禁未登记——实验不得在无基座/基线时开展（防增益与协议抖动不可分、"
            "防自建弱对照证领先、防半合成循环验证）。\n"
            "先完成 p2a 内化（关键论文复现为可执行基座，含完整评测协议），再登记：\n"
            f"  python discovery_loop/pipeline.py gate {domain} \"消融臂:…；SOTA基座(内化自 doi:…):…；sanity:…\"")
    if not quiet:
        print(f"[guard] {domain}/{stage} 前置齐备，放行", file=sys.stderr)


def cmd_refine(a) -> int:
    """补查登记：文献检索是常驻服务，任何阶段都可再调研/换角度——登记留痕。"""
    route = _load_route(a.domain)
    if route is None:
        if a.domain == LEGACY_DOMAIN:
            print(f"域 '{a.domain}' 无主线台账——补查请直接跑检索，判读理由写 hypo_evolve_log（池循环自带留痕）")
            return 0
        raise SystemExit(f"域 '{a.domain}' 无主线台账——先冷启动：pipeline.py newdomain {a.domain}")
    route.setdefault("refinements", []).append(
        {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "at_stage": _next_pending(route), "note": a.note})
    route_path(a.domain).write_text(json.dumps(route, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"refine 登记于阶段 {_next_pending(route)}：{a.note}")
    return 0


def cmd_guard(a) -> int:
    guard(a.domain, a.stage)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(prog="discovery_loop.pipeline", description="可执行研究主线（冷启动+阶段门槛）")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("newdomain"); s.add_argument("domain"); s.set_defaults(f=cmd_newdomain)
    s = sub.add_parser("status"); s.add_argument("domain"); s.set_defaults(f=cmd_status)
    s = sub.add_parser("done"); s.add_argument("domain")
    s.add_argument("stage", choices=[k for k, _ in STAGES]); s.add_argument("note"); s.set_defaults(f=cmd_done)
    s = sub.add_parser("guard"); s.add_argument("domain")
    s.add_argument("stage", choices=[k for k, _ in STAGES]); s.set_defaults(f=cmd_guard)
    s = sub.add_parser("gate"); s.add_argument("domain"); s.add_argument("note"); s.set_defaults(f=cmd_gate)
    s = sub.add_parser("refine"); s.add_argument("domain"); s.add_argument("note"); s.set_defaults(f=cmd_refine)
    a = ap.parse_args()
    return a.f(a)


if __name__ == "__main__":
    raise SystemExit(main())
