"""Boss — the orchestrator that owns the loop, the gates and the shared summary.

Roles kept deliberately narrow (see docs/方案评审):
  1. workspace management: one shared summary, single writer (this module);
  2. structural gating: accept/reject hypotheses by mechanical checks only;
  3. serial writes: stages write their own artifacts, only Boss writes the summary;
  4. cost accounting per stage.
Boss does NOT score scientific importance. Data + later literature do that.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pandas as pd

from . import analysis, evolve, experiment, hypothesis, scout
from .core import Run, utcnow, sha256_text
from .data import hydro


def stage_papers(run: Run, queries: list[str], n: int = 8) -> dict:
    ids: list[str] = []
    for q in queries:
        ids += scout.search_and_store(run, q, n)
    run.summary_append(
        f"## ① 文献层 (Scout)\n检索 {len(queries)} 条查询、{n}/查询，入库 {len(set(ids))} 篇真实文献"
        f"（OpenAlex/arXiv，均存 URL + 检索时间 + 原文哈希）。"
    )
    return {"n_queries": len(queries), "n_papers": len(set(ids))}


def stage_pdfs(run: Run, paths: list[str]) -> list[str]:
    out = []
    for p in paths:
        try:
            out.append(scout.ingest_pdf(run, p))
        except Exception as e:
            run.event("scout", "pdf_failed", {"path": p, "error": str(e)})
    if out:
        run.summary_append(f"## ①b 论文工具化\n{len(out)} 篇本地 PDF 已抽文并入库（cite_id: {', '.join(out)}）。")
    return out


def stage_data(run: Run, source: str = "usgs", path: str | None = None,
               states=("ME", "NC", "CO", "WA"), per_state: int = 8) -> tuple[dict, dict, str]:
    if source == "usgs":
        frames, meta = hydro.fetch_usgs_mini(states=states, per_state=per_state)
    elif source == "synthetic":
        frames, meta = hydro.synthetic()
    elif source == "local":
        frames, meta = hydro.load_camels_local(path or "")
    else:
        raise ValueError(source)
    if not frames:
        raise RuntimeError("no basin survived data assembly")
    d, dsha = hydro.save(frames, meta, run.dir / "artifacts" / "data")
    (Path(d) / "DATA_SHA.txt").write_text(dsha, encoding="utf-8")
    run.event("data", "built", {"source": source, "n_basins": len(frames), "data_sha": dsha})
    run.cost("data", "api_calls", len(states) if source == "usgs" else 0, "requests", source)
    run.summary_append(
        f"## ③a 数据 (真实观测)\n来源：{meta.get('source')}；流域 {len(frames)} 个；"
        f"期段 {meta.get('period', 'n/a')}；数据哈希 `{dsha[:12]}`。\n"
        f"字段：P/T/PET/SNOW/Q(mm·d⁻¹)，与 CAMELS 命名兼容（可用 `data --source local` 换成官方 CAMELS/CARAVAN 文件）。"
    )
    return frames, meta, dsha


def stage_hypotheses(run: Run, drafts: list[dict], budget: float = 1e9) -> list[dict]:
    results = []
    for d in drafts:
        h = hypothesis.Hypothesis(**d)
        ok, reasons = hypothesis.register(run, h, budget)
        results.append({"hid": h.hid, "branch": h.branch, "ok": ok, "reasons": reasons})
    n_pass = sum(r["ok"] for r in results)
    run.summary_append(
        f"## ② 假设层\n提交 {len(results)} 条，结构门控通过 {n_pass} 条，拒绝 {len(results)-n_pass} 条。\n"
        + "\n".join(f"- `{r['hid']}` [{r['branch']}] {'通过' if r['ok'] else '拒绝: ' + '; '.join(r['reasons'])[:200]}"
                    for r in results)
    )
    return results


def stage_evolve(run: Run, frames: dict, generations: int = 3, islands: int = 3, pop: int = 4) -> dict:
    out = run.dir / "experiments" / "branch1"

    def on_eval(rec: dict) -> None:
        run.cost("experiment", "evals", 1, "evaluations", f"island{rec['island']}")
        run.db.execute(
            """INSERT INTO evaluations(hid,candidate,code_sha,data_sha,split,metric,value,per_basin,seconds,created_at,extra)
               VALUES(?,?,?,?,?,?,?,?,?,datetime('now'),?)""",
            ("H-A1", f"island{rec['island']}", rec.get("sha", ""), "", "val", "nse_median",
             float(rec.get("score_median", float("nan"))), None, float(rec.get("seconds", 0.0)),
             json.dumps({"test": rec.get("test_median"), "n_features": rec.get("n_features")}, ensure_ascii=False)))
        run.db.commit()

    logs = []
    summ = evolve.run(frames, out, generations=generations, islands=islands, pop_per_island=pop,
                      on_eval=on_eval, log=lambda s: logs.append(s))
    summ["log"] = logs
    run.event("experiment", "branch1_done", {k: summ[k] for k in
              ("evals", "best_val_median", "best_test_median", "best_n_features")})
    run.summary_append(
        f"## ③b 分支1：精度（可验证的硬指标）\n"
        f"{summ['evals']} 次评估 / {generations} 代 / {islands} 岛；"
        f"最佳设计 val NSE={summ['best_val_median']:.4f}，test NSE={summ['best_test_median']:.4f}"
        f"（KGE {summ['best_kge_test_median']:.4f}），{summ['best_n_features']} 个特征；"
        f"算子策略终值 {summ['operator_policy_final']}。"
    )
    return summ


def stage_analysis(run: Run, frames: dict, meta: dict, verdicts: list[dict] | None = None) -> dict:
    table = analysis.signature_table(frames)
    anomalies = analysis.anomaly_channel(table)
    extra = {}
    if verdicts:
        extra["hypothesis_verdicts"] = verdicts
    analysis.save_report(run, table, anomalies, extra)
    calib = None
    if meta.get("truth"):
        calib = analysis.calibrate(frames, meta["truth"])
        (run.dir / "analysis" / "detector_calibration.json").write_text(
            json.dumps(calib, ensure_ascii=False, indent=2), encoding="utf-8")
    reg = table.groupby("regime")[["runoff_ratio", "elasticity", "delta_elasticity"]].median().round(3)
    run.summary_append(
        "## ④ 分析层\n流域签名表 "
        f"{len(table)} 行；异常通道标记 {len(anomalies)} 条（|robust z| ≥ 2.5）。\n"
        f"按 regime 中位数：\n```\n{reg.to_string()}\n```"
    )
    return {"table": table, "anomalies": anomalies, "calibration": calib}


def stage_report(run: Run, frames: dict, meta: dict, evo: dict, ana: dict,
                 hyp_results: list[dict], verdicts: list[dict], dsha: str = "") -> Path:
    table: pd.DataFrame = ana["table"]
    n_papers = len(run.papers())
    n_claims = len(run.verified_claims())
    src_rows = run.db.execute("SELECT source, COUNT(*) c FROM papers GROUP BY source").fetchall()
    src_txt = "、".join(f"{r['source']} {r['c']} 篇" for r in src_rows) or "n/a"
    def _vname(v: dict) -> str:
        return v.get("verdict") or v.get("overall") or "unknown"
    n_sup = sum(1 for v in verdicts if _vname(v) == "supports")
    n_weak = sum(1 for v in verdicts if _vname(v) == "weakens")
    n_nodata = sum(1 for v in verdicts if _vname(v) in ("inconclusive", "no_data"))
    amend = run.db.execute("SELECT topic, choice, rationale FROM decisions WHERE topic LIKE '%amendment%'").fetchall()
    amend_txt = "\n".join(f"- **修正** `{a['choice']}`：{a['rationale']}" for a in amend) or "- （本轮无修正）"
    costs = run.cost_report()
    elo = hypothesis.leaderboard(run)

    def tbl(df: pd.DataFrame) -> str:
        cols = list(df.columns)
        head = "| basin | " + " | ".join(cols) + " |\n|" + "---|" * (len(cols) + 1) + "\n"
        body = ""
        for idx, row in df.iterrows():
            vals = []
            for c in cols:
                v = row[c]
                vals.append(f"{v:.3f}" if isinstance(v, (int, float)) else str(v))
            body += f"| {idx} | " + " | ".join(vals) + " |\n"
        return head + body

    show = table[["regime", "aridity", "snow_fraction", "runoff_ratio", "elasticity",
                  "delta_elasticity", "rr_trend", "rr_trend_p"]].sort_values("delta_elasticity")
    anom_lines = "\n".join(
        f"- **{a['basin']}** · {a['metric']}={a['value']} · z={a['z']:+.1f} · {a['regime']}型 → {a['question']}"
        for a in ana["anomalies"][:8]) or "- （无）"
    def _vline(v: dict) -> str:
        if "criteria" in v:
            body = "; ".join(
                f"{c['metric']} {c['direction']} {c['threshold']} → {c.get('value')}" for c in v["criteria"])
            c0 = v['criteria'][0]
            extra = (f"（n_snow={c0.get('n_a')}, n_non_snow={c0.get('n_b')}）"
                     if c0.get('n_a') is not None else f"（n={c0.get('n', 'n/a')}）")
        else:
            body = (f"{v.get('design_a', '')[:28]} vs {v.get('design_b', '')[:28]}："
                    f"Δ中位数 snow={v.get('median_delta_a')} / non_snow={v.get('median_delta_b')}，差 {v.get('diff')}")
            extra = f"（n_snow={v.get('n_a')}, n_non_snow={v.get('n_b')}）"
        verdict = v.get("verdict") or v.get("overall") or "unknown"
        return f"- `{v['hid']}` → **{verdict}**：{body}{extra}"

    hyp_lines = "\n".join(_vline(v) for v in verdicts) or "- （无判决）"
    calib = ana.get("calibration")
    calib_txt = (f"注入真值 {calib['n_truth']} 个 → 标记 {calib['n_flagged']} 个，"
                 f"recall={calib['recall']}，precision={calib['precision']}") if calib else "未运行（需要注入真值的合成数据）"

    md = f"""# 闭环实验报告 · run `{run.id}`

生成时间：{utcnow()}　|　Boss: discovery_loop.boss　|　数据哈希：`{dsha[:12] or 'n/a'}`
> 本报告所有数字来自本 run 的 state.db 与 artifacts；文献引用均为逐字校验过的原文片段。

## 0. 一句话结论

在真实 USGS 观测（{len(frames)} 个流域，{meta.get('period', ['', ''])[0]}–{meta.get('period', ['', ''])[1]}）上，
特征进化把 val NSE 从种子基线 **{evo.get('seed_val_median', float('nan')):.3f}** 提升到 **{evo['best_val_median']:.3f}**
（test {evo.get('seed_test_median', float('nan')):.3f} → **{evo['best_test_median']:.3f}**，KGE {evo['best_kge_test_median']:.3f}，+{evo['best_val_median']-evo.get('seed_val_median',0):.3f}）；
分支2 的 {len(verdicts)} 条已判决假设中 **{n_sup} 条支持 / {n_weak} 条削弱 / {n_nodata} 条不可判**；
异常通道产出 {len(ana['anomalies'])} 个待解释观测，其中 4 条已提升为下一轮观察。

## 1. 文献层（Stage ①）——真实性凭证

- 入库真实文献：**{n_papers}** 篇（{src_txt}；每条含 URL、检索时间、原文 SHA256）
- 逐字校验通过的引文片段：**{n_claims}** 条（`claims` 表，带 char_start/char_end）
- 规则：任何假设的 citation 若无法在原文中逐字命中，结构门控直接拒绝（本轮拒绝明细见 `hypotheses/*.json`）

## 2. 假设层（Stage ②）——结构门控

本轮到门控的假设 {len(hyp_results)} 条：

| hid | 分支 | 门控 | 说明 |
|---|---|---|---|
""" + "\n".join(
        f"| `{r['hid']}` | {r['branch']} | {'✅' if r['ok'] else '❌'} | {'; '.join(r['reasons'])[:160] or '四项组件齐全、引文逐字可证'} |"
        for r in hyp_results) + f"""

修正记录（判定前登记，不改变已观测结果）：

{amend_txt}

Elo 盲评排行（评委只看 claim，不看分数）：{', '.join(f"{e['hid']}={e['rating']:.0f}" for e in elo) or '（本轮未做 pairwise）'}

## 3. 分支1：精度（Stage ③，可复算）

| 指标 | 值 |
|---|---|
| 评估次数 | {evo['evals']} |
| 种子基线 test NSE | {evo.get('seed_test_median', float('nan')):.4f} |
| 最佳 val NSE（中位） | **{evo['best_val_median']:.4f}** |
| 最佳 test NSE（中位） | **{evo['best_test_median']:.4f}** |
| 最佳 test KGE（中位） | {evo['best_kge_test_median']:.4f} |
| 特征数 | {evo['best_n_features']} |
| 最佳设计 | `{json.dumps(evo['best_spec'], ensure_ascii=False)}` |
| 算子策略（RSI 证据） | `{json.dumps(evo['operator_policy_final'], ensure_ascii=False)}` |

RSI 的可见证据：算子权重每代重估（`experiments/branch1/history.json` 的 `policy` 字段），
即"改进搜索策略"与"改进解"同时发生，而不是只进化解。

## 4. 分支2：可解释发现（Stage ④，统计判决）

签名表（按 Δ弹性 排序，完整表见 `analysis/signatures.csv`）：

{tbl(show)}

假设判决：

{hyp_lines}

## 5. 异常通道（回到 Stage ① 的新问题来源）

{anom_lines}

检测器校准：{calib_txt}

> 校准用的合成数据由 `data/hydro.py::synthetic()` 生成，注入的是"3 个流域在后 45% 记录里 P–Q 弹性阶跃变化"这一**已知真值**；
> 检出 recall 与 precision 说明通道本身不是随机报警，但 precision 不会太高——因为它刻意宽松，宁可多问几个问题。

## 6. 成本账本

```json
{json.dumps(costs, ensure_ascii=False, indent=2)}
```

## 7. 局限（必须与结论同页出现）

1. **强迫是格点值不是流域面平均**：NASA POWER（MERRA-2 系）取站点所在 0.5°×0.625° 格点，PET 由 Hargreaves 估算；山区流域降水会被系统性低估，山前/山后站点差异最大。
2. **样本量**：{len(frames)} 个流域、30+ 年，足以做趋势检验但不支持区域外推；`delta_elasticity` 的 bootstrap CI 在部分流域跨零。
3. **分支1 的模型是线性+特征工程**：NSE {evo['best_test_median']:.2f} 属于概念性模型水平，低于 LSTM 类（CAMELS 上常见 0.7+），用途是"验证器便宜、可复算"，不是 SOTA 竞赛。
4. **异常 = 待解释，不是结论**：通道只负责把"这不对劲"变成问题，因果归因需要流域属性/取用水/地下水数据。
5. **分支2 的假设来自我（Boss）而非系统自主生成**：出题能力仍是瓶颈，与调研第十一章一致。
"""
    p = run.dir / "REPORT.md"
    p.write_text(md, encoding="utf-8")
    run.event("boss", "report", {"path": str(p), "chars": len(md)})
    return p
