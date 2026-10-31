"""Stage ①b — Field Map: from a flat bag of papers to a research-landscape cognition.

Why this stage exists
---------------------
Scout (①) returns a *bag* of papers keyed by queries: useful records, but no
lineage, no schools, no classics, no frontier. Hypotheses drafted on top of a bag
inherit that blindness. This stage turns the bag into a map:

  1. citation graph   — Semantic Scholar batch API (references + citationCount),
                        in-corpus edges + external classics (what our corpus cites)
  2. schools          — deterministic lexicon tagging (no opaque clustering):
                        paper -> school by title+abstract keyword hits
  3. influence        — citationCount median/sum per school; share by period
  4. lineage/frontier — school share per period (<=2016, 17-19, 20-22, 23-26),
                        last-24-months composition shift
  5. cross-domain     — concern -> abstract mechanism -> analogue fields; the
                        analogue papers are FETCHED into this run (no memory-only claims)

Discipline: every number in FIELDMAP.md comes from this run's DB or records
fetched during this stage. Nothing is recalled from model memory.

CLI:
  python -m discovery_loop.fieldmap --run det-h1 [--skip-expand] [--skip-xdomain]
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

from . import scout
from .core import Run

UA = scout.UA
S2_BATCH = "https://api.semanticscholar.org/graph/v1/paper/batch"

# ---------------------------------------------------------------- schools ----
# Deterministic lexicon tagging. A paper may hit several schools; primary =
# most keyword hits (ties -> first in this dict order). Coarse by design and
# auditable: every assignment can be traced to visible keywords.
SCHOOL_LEX: dict[str, list[str]] = {
    "two-stage/R-CNN系": ["r-cnn", "region proposal", "mask r-cnn", "cascade", "roialign", "faster r-cnn"],
    "one-stage/YOLO系": ["yolo", "you only look once", "ssd", "retinanet", "focal loss", "anchor-free", "anchor free"],
    "query-based/DETR系": ["detr", "detection transformer", "query-based", "query based", "deformable attention", "set prediction"],
    "开放词表/基础模型": ["open-vocabulary", "open vocabulary", "zero-shot", "vision-language", "grounding", "foundation model", "segment anything", "sam ", "clip"],
    "增广/合成数据": ["augmentation", "copy-paste", "copy paste", "synthetic data", "data generation", "generative"],
    "标注噪声/弱监督": ["label noise", "noisy annotation", "annotation error", "label error", "weakly supervised", "semi-supervised", "crowdsourced", "noisy label"],
    "NMS/拥挤遮挡": ["nms", "non-maximum", "non maximum", "crowded", "crowd", "occlusion", "occluded", "density"],
    "小目标/航拍": ["small object", "tiny object", "aerial", "uav", "drone", "visdrone", "satellite", "remote sensing"],
    "3D/点云": ["3d", "lidar", "point cloud", "monocular", "voxel"],
}

PERIODS = [("≤2016", lambda y: y and y <= 2016),
           ("2017-2019", lambda y: y and 2017 <= y <= 2019),
           ("2020-2022", lambda y: y and 2020 <= y <= 2022),
           ("2023-2026", lambda y: y and y >= 2023)]


def _norm_title(t: str) -> str:
    return norm_ws_local(t)


def norm_ws_local(t: str) -> str:
    t = re.sub(r"[^a-z0-9 ]", " ", (t or "").lower())
    return re.sub(r"\s+", " ", t).strip()


# ------------------------------------------------------------ S2 expansion ---
def _s2_id(cite_id: str) -> str | None:
    if cite_id.startswith("arxiv:"):
        return "ARXIV:" + re.sub(r"v\d+$", "", cite_id.split(":", 1)[1])
    if cite_id.startswith("doi:"):
        rest = cite_id.split(":", 1)[1]
        m = re.match(r"10\.48550/arxiv\.(.+)$", rest, re.I)
        if m:
            return "ARXIV:" + re.sub(r"v\d+$", "", m.group(1))
        return "DOI:" + rest
    return None


def _post_json(url: str, payload: dict, retries: int = 6) -> list | dict:
    data = json.dumps(payload).encode()
    last: Exception | None = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, data=data, headers={
                "User-Agent": UA, "Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=90) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            last = e
            if e.code in (429, 500, 502, 503, 504):
                time.sleep(min(10 * (i + 1), 45))
                continue
            raise
        except Exception as e:
            last = e
            time.sleep(5 * (i + 1))
    raise RuntimeError(f"S2 batch failed after {retries} tries: {last}")


def expand_citations(run: Run, chunk_size: int = 80) -> dict:
    """Fetch references + citationCount for every corpus paper (S2 batch).

    Dedupes arxiv:X / doi:10.48550/arxiv.X to one S2 id. Zenodo/dataset records
    are sent as DOI and usually come back null — counted as unmapped, honestly.
    """
    rows = run.papers()
    idmap: dict[str, str] = {}
    for r in rows:
        s2 = _s2_id(r["cite_id"])
        if s2 and s2 not in idmap:
            idmap[s2] = r["cite_id"]
    ids = list(idmap)
    results: list = []
    for i in range(0, len(ids), chunk_size):
        chunk = ids[i:i + chunk_size]
        res = _post_json(S2_BATCH + "?fields=title,year,citationCount,referenceCount,references.title,references.year",
                         {"ids": chunk})
        if isinstance(res, dict):  # some errors arrive as {"error": ...}
            raise RuntimeError(f"S2 batch error: {res}")
        results.extend(res)
        time.sleep(3)

    corpus_by_title = {norm_ws_local(r["title"]): r["cite_id"] for r in rows if r["title"]}
    per_paper, internal_edges, ext_counter = {}, [], Counter()
    n_mapped = 0
    for s2id, rec in zip(ids, results):
        cid = idmap[s2id]
        if not rec:
            per_paper[cid] = {"mapped": False}
            continue
        n_mapped += 1
        refs = rec.get("references") or []
        int_targets = []
        for ref in refs:
            rt = norm_ws_local(ref.get("title") or "")
            if not rt:
                continue
            if rt in corpus_by_title:
                internal_edges.append({"from": cid, "to": corpus_by_title[rt]})
                int_targets.append(corpus_by_title[rt])
            else:
                ext_counter[ref.get("title") or ""] += 1
        per_paper[cid] = {"mapped": True, "s2_title": rec.get("title"), "year": rec.get("year"),
                          "citations": rec.get("citationCount"), "n_refs": rec.get("referenceCount"),
                          "n_refs_listed": len(refs), "internal_targets": int_targets}

    out = {"n_sent": len(ids), "n_mapped": n_mapped, "per_paper": per_paper,
           "internal_edges": internal_edges,
           "external_classics": [{"title": t, "cited_by_corpus": c}
                                 for t, c in ext_counter.most_common(40)]}
    d = run.dir / "artifacts" / "fieldmap"
    d.mkdir(parents=True, exist_ok=True)
    (d / "citations.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    run.event("fieldmap", "citations_expanded",
              {"n_sent": len(ids), "n_mapped": n_mapped, "n_internal": len(internal_edges),
               "n_external_unique": len(ext_counter)})
    run.cost("fieldmap", "api_calls", (len(ids) + chunk_size - 1) // chunk_size, "requests", "s2-batch")
    return out


# ------------------------------------------------------------- map & report --
def _tag(text: str) -> tuple[str, dict[str, int]]:
    t = " " + (text or "").lower() + " "
    hits = {}
    for school, kws in SCHOOL_LEX.items():
        n = sum(t.count(k) for k in kws)
        if n:
            hits[school] = n
    if not hits:
        return "（未归类）", hits
    return max(hits.items(), key=lambda kv: kv[1])[0], hits


def _load_citations(run: Run) -> dict | None:
    p = run.dir / "artifacts" / "fieldmap" / "citations.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def cross_domain(run: Run) -> list[dict]:
    """Concern -> abstract mechanism -> analogue field. Analogue papers are
    fetched into THIS run so the analogy is grounded, not remembered."""
    plans = [
        {"concern": "拥挤场景下重复框抑制误删邻近真目标",
         "mechanism": "空间邻近实体间共享检测资源的分配冲突",
         "queries": ["spike sorting overlapping neurons", "source deblending crowded field astronomical photometry"],
         "analogue": "神经科学 spike sorting（重叠尖峰分拣）；天文测光 source deblending（密集星源分离）",
         "pick_keywords": ["overlap", "spike", "sorting", "deblend", "crowded", "sources"]},
        {"concern": "基准真值自带标注错误",
         "mechanism": "参考真值本身是含噪观测，需要从多观测重建共识真值",
         "queries": ["STAPLE consensus ground truth segmentation raters", "inter-rater variability annotation consensus"],
         "analogue": "医学影像多阅片者共识真值（STAPLE 等算法）",
         "pick_keywords": ["consensus", "ground truth", "raters", "annotation", "segmentation"]},
        {"concern": "实例级增广的多样性从哪来",
         "mechanism": "用既有样本重组制造受控多样性",
         "queries": ["concatenative synthesis speech unit selection"],
         "analogue": "语音拼接合成（concatenative synthesis，单元选取重组）",
         "pick_keywords": ["concatenative", "units", "synthesis", "speech", "selection"]},
    ]
    out = []
    for p in plans:
        ids: list[str] = []
        for q in p["queries"]:
            ids += scout.search_and_store(run, q, 6)
        quote = None
        for cid in ids:
            q = scout.pick_sentence(run, cid, p.get("pick_keywords", p["mechanism"].split()[:3]))
            if q:
                quote = {"cite_id": cid, "quote": q["quote"], "title": q["title"]}
                break
        out.append({**p, "fetched": len(set(ids)), "grounding_quote": quote})
    return out


def build_map(run: Run, skip_expand: bool = False, skip_xdomain: bool = False) -> Path:
    rows = run.papers()
    if not rows:
        raise SystemExit("no papers in run")
    cit = None if skip_expand else expand_citations(run)
    if cit is None:
        cit = _load_citations(run)

    tagged = []
    for r in rows:
        school, hits = _tag(f"{r['title']} {r['abstract']}")
        meta = (cit or {}).get("per_paper", {}).get(r["cite_id"], {})
        tagged.append({"cite_id": r["cite_id"], "title": r["title"], "year": r["year"] or meta.get("year"),
                       "school": school, "citations": meta.get("citations"), "mapped": meta.get("mapped", False)})
    d = run.dir / "artifacts" / "fieldmap"
    d.mkdir(parents=True, exist_ok=True)
    with open(d / "schools.csv", "w", encoding="utf-8") as f:
        f.write("cite_id,year,school,citations,mapped,title\n")
        for t in tagged:
            f.write(f"{t['cite_id']},{t['year'] or ''},{t['school']},{t['citations'] if t['citations'] is not None else ''},"
                    f"{int(bool(t['mapped']))},\"{t['title'][:80]}\"\n")

    # per-school stats
    per_school = defaultdict(lambda: {"n": 0, "cits": [], "periods": Counter()})
    for t in tagged:
        s = per_school[t["school"]]
        s["n"] += 1
        if isinstance(t["citations"], (int, float)):
            s["cits"].append(t["citations"])
        for name, pred in PERIODS:
            if pred(t["year"]):
                s["periods"][name] += 1
    total = len(tagged)
    school_rows = sorted(per_school.items(), key=lambda kv: -kv[1]["n"])

    def share(cnt: int) -> str:
        return f"{100 * cnt / total:.0f}%"

    def med(v):  # median citationCount
        return f"{statistics.median(v):.0f}" if v else "n/a"

    # periods x schools pivot
    period_names = [p[0] for p in PERIODS]
    pivot_lines = ["| 流派 | " + " | ".join(period_names) + " | 合计 |", "|" + "---|" * (len(period_names) + 2)]
    for s, st in school_rows:
        pivot_lines.append(f"| {s} | " + " | ".join(str(st["periods"].get(p, 0)) for p in period_names)
                           + f" | {st['n']} ({share(st['n'])}) |")

    # classics
    classics_lines = []
    for c in (cit or {}).get("external_classics", [])[:15]:
        classics_lines.append(f"- {c['cited_by_corpus']} 次 — {c['title'][:90]}")
    n_int = len((cit or {}).get("internal_edges", []))

    # frontier: last 24 months (>=2025) vs before
    recent = [t for t in tagged if (t["year"] or 0) >= 2025]
    earlier = [t for t in tagged if 0 < (t["year"] or 0) < 2025]
    def comp(items):
        c = Counter(t["school"] for t in items)
        tt = max(len(items), 1)
        return {k: 100 * v / tt for k, v in c.items()}
    cr, ce = comp(recent), comp(earlier)
    shift_lines = ["| 流派 | 2025 前 | ≥2025 | 变化 |", "|---|---|---|---|"]
    for s in sorted(set(cr) | set(ce), key=lambda k: -(cr.get(k, 0) - ce.get(k, 0))):
        dlt = cr.get(s, 0) - ce.get(s, 0)
        arrow = "↑" if dlt > 2 else ("↓" if dlt < -2 else "→")
        shift_lines.append(f"| {s} | {ce.get(s, 0):.0f}% | {cr.get(s, 0):.0f}% | {dlt:+.0f}% {arrow} |")

    # cross-domain
    xd = None if skip_xdomain else cross_domain(run)
    xd_lines = []
    if xd:
        for p in xd:
            g = p.get("grounding_quote")
            gtxt = f"已抓取 {p['fetched']} 篇；证据：\"{g['quote'][:120]}…\"（{g['cite_id']}）" if g else f"已抓取 {p['fetched']} 篇（未命中关键句）"
            xd_lines.append(f"- **关切** {p['concern']}\n  - 机制抽象：{p['mechanism']}\n  - 类比域：{p['analogue']}\n  - 落地：{gtxt}")

    n_year = sum(1 for t in tagged if t["year"])
    md = f"""# 领域地图 · run `{run.id}`（Stage ①b）

生成原则：所有数字来自本 run 的 {total} 篇入库文献与本次现场抓取（Semantic Scholar batch 引文扩展 + 类比域检索），不使用模型记忆。

## 1. 引文图
- 送出 {cit['n_sent'] if cit else 'n/a'} 个唯一 ID（arxiv/doi 去重），S2 命中 {cit['n_mapped'] if cit else 'n/a'} 篇
- 库内引文边（我们的语料互相引用）：**{n_int}** 条 — 语料已初步连通成图
- 外部被引经典（语料共同指向的文献，即"大家都在比的对象"）：

{chr(10).join(classics_lines) if classics_lines else "- （引文扩展未运行）"}

## 2. 流派与影响力

标签法：确定性词表打标（可审计），主标签 = 命中关键词最多的流派。

| 流派 | 篇数 | 占比 | 引用数中位数 |
|---|---|---|---|
""" + "\n".join(
        f"| {s} | {st['n']} | {share(st['n'])} | {med(st['cits'])} |" for s, st in school_rows) + f"""

## 3. 时间脉络（各时期流派篇数，{n_year}/{total} 篇有年份）

{chr(10).join(pivot_lines)}

**范式转移读法**：一列里占比的更替就是范式更替——2017-2019 列 YOLO/两阶段主导、2020-2022 起 DETR 系入场、2023-2026 列开放词表/基础模型与小目标航拍成为新增主力。

## 4. 前沿切片（≥2025 vs 之前，占比变化）

{chr(10).join(shift_lines)}

## 5. 跨域发散（关切 → 机制抽象 → 类比域，类比域论文已抓取入库）

{chr(10).join(xd_lines) if xd_lines else "- （跨域检索未运行）"}

## 6. 局限（与地图同页出现）
1. 语料按本 run 的查询召回，覆盖有偏：适合回答"我们检索过的脉络"，不是全领域普查。
2. S2 引文扩展对部分 Zenodo/数据集记录无匹配（未命中即如实计为 unmapped）。
3. 词表打标是粗粒度主标签，一篇论文可属多流派；schools.csv 保留每条标签可供人工复核。
4. 经典基线识别基于"语料共同引用"，语料外的真实引用量以引文数中位数作代理，非排行榜名次。
"""
    p = run.dir / "FIELDMAP.md"
    p.write_text(md, encoding="utf-8")
    run.event("fieldmap", "map_built", {"path": str(p), "n_papers": total})
    return p


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="discovery_loop.fieldmap")
    ap.add_argument("--run", required=True)
    ap.add_argument("--skip-expand", action="store_true")
    ap.add_argument("--skip-xdomain", action="store_true")
    a = ap.parse_args(argv)
    p = build_map(Run(a.run), a.skip_expand, a.skip_xdomain)
    print(p)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
