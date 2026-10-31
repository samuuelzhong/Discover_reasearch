"""Scout 全文级验证引擎（PaperQA2 嵌入）：PDF → 索引 → 带页码引用的 claim 核查。

分工（对齐交付说明-闭环框架v0.1 的观察层设计）：
- scout.py   检索召回层：多源（OpenAlex/arXiv/S2/DataCite）+ 本地 PDF + quote 逐字验证
- scout_pqa.py（本模块）全文验证层：PaperQA2（paperqa 2026.8.12）对召回命中的 PDF
  做整篇索引+问答，输出页码级引用——文献锚点强度升级：
      web_snippet（检索摘要，弱） < pdf_fulltext（人工精读，强） < paperqa_cited（机械页码定位，可规模化）

通用性：不绑定具体论文；任何 PDF/问题组合可用。
LLM 后端：火山 Ark coding plan（D:\\Viloong\\.env 的 ANTHROPIC_API_KEY，
OpenAI 兼容 /chat/completions），模型 glm-5.3-flash；embedding 用 PaperQA2 原生
sparse 模式（coding plan 无 embeddings 端点）。

用法：
    python discovery_loop/scout_pqa.py <pdf路径或目录> --question "..." [--k 3]
输出：stdout JSON 事件（question/answer/citations[]/anchor_grade）
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

# LLM 网关注入（litellm openai/ provider 读 OPENAI_API_BASE/OPENAI_API_KEY）
_ENV_KEY = None
for _line in Path(r"D:\Viloong\.env").read_text(encoding="utf-8").splitlines():
    if _line.startswith("ANTHROPIC_API_KEY="):
        _ENV_KEY = _line.split("=", 1)[1].strip()
        break
if _ENV_KEY:
    os.environ.setdefault("OPENAI_API_KEY", _ENV_KEY)
    os.environ.setdefault("OPENAI_API_BASE", "https://ark.cn-beijing.volces.com/api/coding/v3")
    os.environ.setdefault("OPENAI_BASE_URL", "https://ark.cn-beijing.volces.com/api/coding/v3")

MODEL = "openai/glm-5.3-flash"
ANCHOR_GRADE = "paperqa_cited"


def _collect_pdfs(target: Path) -> list[Path]:
    if target.is_file() and target.suffix.lower() == ".pdf":
        return [target]
    return sorted(target.rglob("*.pdf")) if target.is_dir() else []


async def _run(pdfs: list[Path], question: str, k: int) -> dict:
    from paperqa import Docs, Settings

    settings = Settings(llm=MODEL, summary_llm=MODEL, agent_llm=MODEL,
                        agent_economy=False, verbosity=0)
    settings.parsing.use_doc_details = False  # 跳过 S2/Crossref 联网元数据（429 源）
    settings.parsing.enrichment_llm = MODEL   # 默认 gpt-4o 会打到 coding plan 404
    settings.embedding = "sparse"
    settings.answer.answer_max_sources = k

    docs = Docs()
    n_ok = 0
    for pdf in pdfs:
        try:
            await docs.aadd(pdf, settings=settings,
                            citation=f"{pdf.stem} (local PDF: {pdf.name})")
            n_ok += 1
        except Exception as e:  # 单篇失败不阻塞整批（诚实留痕）
            print(f"[warn] add 失败 {pdf.name}: {type(e).__name__}: {str(e)[:120]}",
                  file=sys.stderr)
    res = await docs.aquery(question, settings=settings)
    cites = []
    for ctx in list(res.contexts)[:k]:
        # paperqa 2026.8.12 的 Context 字段：id(含 docname+页码)/context/text/score
        cites.append({"id": str(ctx.id), "text": str(ctx.text)[:400],
                      "score": getattr(ctx, "score", None)})
    return {"question": question, "answer": str(res.answer).strip(),
            "citations": cites, "n_docs_indexed": n_ok,
            "anchor_grade": ANCHOR_GRADE}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("target", help="PDF 文件或目录")
    ap.add_argument("--question", required=True)
    ap.add_argument("--k", type=int, default=3)
    args = ap.parse_args()

    pdfs = _collect_pdfs(Path(args.target))
    if not pdfs:
        print(json.dumps({"error": "no PDF found", "target": args.target},
                         ensure_ascii=False))
        return 1
    out = asyncio.run(_run(pdfs, args.question, args.k))
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if out["answer"] and out["citations"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
