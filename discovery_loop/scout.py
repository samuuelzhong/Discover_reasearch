"""Stage 1 — Scout: real literature only.

Every record comes from a live API (OpenAlex / arXiv) or a local PDF whose text we
extract ourselves. Nothing is recalled from model memory: the only text that can be
quoted later is text that was fetched in this run and hashed into state.db.

CLI:
  python -m discovery_loop.scout --run <id> search "query" --n 12
  python -m discovery_loop.scout --run <id> pdf "../文献收集/x.pdf"
  python -m discovery_loop.scout --run <id> list
  python -m discovery_loop.scout --run <id> quote "some sentence" [--cite doi:...]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

from .core import Run, norm_ws

UA = "HydroDiscoveryLoop/0.1 (research prototype; mailto:research@example.org)"
PDF_SCRIPT = Path(
    r"D:\\workbuddy\\resources\\app.asar.unpacked\\resources\\plugins\\workbuddy-builtin\\skills\\workbuddy-pdf\\scripts\\run.sh"
)


def _get(url: str, timeout: int = 30, retries: int = 4) -> bytes:
    """HTTP with backoff. 429/5xx are retried, never silently swallowed."""
    import time
    import urllib.error

    last: Exception | None = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            last = e
            if e.code in (429, 500, 502, 503, 504):
                # 预算耗尽类 429（Retry-After 为小时级）重试无意义——当天必然失败，立即放弃
                ra = e.headers.get("Retry-After") if e.headers else None
                if ra and ra.strip().isdigit() and int(ra) > 600:
                    raise RuntimeError(f"budget exhausted (Retry-After {int(ra)//3600}h): {url}") from e
                time.sleep(4 * (i + 1))
                continue
            raise
        except Exception as e:
            last = e
            time.sleep(2 * (i + 1))
    raise RuntimeError(f"fetch failed after {retries} tries: {url} :: {last}")


def _rebuild_abstract(inv: dict | None) -> str:
    if not inv:
        return ""
    slots: list[tuple[int, str]] = []
    for word, positions in inv.items():
        for p in positions:
            slots.append((p, word))
    slots.sort()
    return " ".join(w for _, w in slots)


def search_openalex(query: str, n: int = 10, from_year: int | None = None) -> list[dict]:
    # 注意：加引号=精确短语匹配（词序敏感，长查询恒 0 命中）；裸词=词 AND/相关性排序。
    filt = f"title_and_abstract.search:{query}"
    if from_year:
        filt += f",from_publication_date:{from_year}-01-01"
    params = {
        "filter": filt,
        "per-page": str(n),
        "mailto": "research@example.org",
        "select": "id,doi,title,publication_year,abstract_inverted_index,primary_location,authorships,cited_by_count,type",
    }
    url = "https://api.openalex.org/works?" + urllib.parse.urlencode(params)
    data = json.loads(_get(url))
    out = []
    for w in data.get("results", []):
        doi = (w.get("doi") or "").replace("https://doi.org/", "")
        venue = ((w.get("primary_location") or {}).get("source") or {}).get("display_name") or ""
        authors = ", ".join(
            (a.get("author") or {}).get("display_name", "") for a in (w.get("authorships") or [])[:6]
        )
        out.append(
            {
                "cite_id": f"doi:{doi}" if doi else f"openalex:{w['id'].split('/')[-1]}",
                "source": "openalex",
                "doi": doi,
                "title": (w.get("title") or "").strip(),
                "year": w.get("publication_year"),
                "venue": venue,
                "authors": authors,
                "abstract": _rebuild_abstract(w.get("abstract_inverted_index")),
                "url": w.get("doi") or w.get("id"),
                "cited_by": w.get("cited_by_count"),
            }
        )
    return out


ATOM = "{http://www.w3.org/2005/Atom}"


def search_arxiv(query: str, n: int = 10) -> list[dict]:
    terms = " AND ".join(f'abs:"{t}"' for t in query.split() if len(t) > 3)
    q = urllib.parse.quote(terms or f"all:{query}")
    url = f"https://export.arxiv.org/api/query?search_query={q}&start=0&max_results={n}&sortBy=relevance"
    raw = _get(url)
    root = ET.fromstring(raw)
    out = []
    for e in root.findall(f"{ATOM}entry"):
        aid = (e.findtext(f"{ATOM}id") or "").rsplit("/abs/", 1)[-1]
        out.append(
            {
                "cite_id": f"arxiv:{aid}",
                "source": "arxiv",
                "arxiv_id": aid,
                "title": " ".join((e.findtext(f"{ATOM}title") or "").split()),
                "year": int((e.findtext(f"{ATOM}published") or "2026")[:4]),
                "venue": "arXiv",
                "authors": ", ".join(a.findtext(f"{ATOM}name") or "" for a in e.findall(f"{ATOM}author")[:6]),
                "abstract": " ".join((e.findtext(f"{ATOM}summary") or "").split()),
                "url": f"https://arxiv.org/abs/{aid}",
            }
        )
    return out


def search_s2(query: str, n: int = 10) -> list[dict]:
    """Semantic Scholar Graph API — good abstracts for hydrology journals."""
    params = {"query": query, "limit": str(n),
              "fields": "title,abstract,year,venue,authors,externalIds,citationCount"}
    url = "https://api.semanticscholar.org/graph/v1/paper/search?" + urllib.parse.urlencode(params)
    data = json.loads(_get(url))
    out = []
    for w in data.get("data", []):
        ext = w.get("externalIds") or {}
        doi = ext.get("DOI", "")
        aid = ext.get("ArXiv", "")
        out.append({
            "cite_id": f"doi:{doi}" if doi else (f"arxiv:{aid}" if aid else f"s2:{w.get('paperId','')[:12]}"),
            "source": "semanticscholar",
            "doi": doi,
            "arxiv_id": aid,
            "title": (w.get("title") or "").strip(),
            "year": w.get("year"),
            "venue": w.get("venue") or "Semantic Scholar",
            "authors": ", ".join(a.get("name", "") for a in (w.get("authors") or [])[:6]),
            "abstract": (w.get("abstract") or "").strip(),
            "url": f"https://doi.org/{doi}" if doi else f"https://arxiv.org/abs/{aid}" if aid else "",
            "cited_by": w.get("citationCount"),
        })
    return out


S2_PAPER_FIELDS = "title,abstract,year,venue,authors,externalIds,citationCount"


def _oaf_node(x, *path):
    """Walk OpenAIRE's XML-in-JSON tree; return last node or {} (fields may be dict/list/str)."""
    cur = x
    for key in path:
        if not isinstance(cur, dict):
            return {}
        cur = cur.get(key)
        if cur is None:
            return {}
    return cur if cur is not None else {}


def _oaf_text(x) -> str:
    """Scalar/text out of dict{'$':..} | list[dict{'$':..}] | str."""
    if isinstance(x, dict):
        return str(x.get("$") or "")
    if isinstance(x, list):
        return " ".join(_oaf_text(i) for i in x).strip()
    return str(x or "")


def search_openaire(query: str, n: int = 10) -> list[dict]:
    """OpenAIRE API — openalex/s2 日预算耗尽时的替补源（Crossref 聚合，含 DOI）。"""
    url = ("https://api.openaire.eu/search/publications?"
           + urllib.parse.urlencode({"keywords": query, "size": str(n), "format": "json", "page": "1"}))
    data = json.loads(_get(url))
    out = []
    results = _oaf_node(data, "response", "results", "result")
    results = results if isinstance(results, list) else [results]
    for res in results:
        r = _oaf_node(res, "metadata", "oaf:entity", "oaf:result")
        title = _oaf_text(r.get("title")).strip()
        if not title:
            continue
        doi = ""
        pid = r.get("pid")
        pid = pid if isinstance(pid, list) else [pid] if pid else []
        for p in pid:
            if isinstance(p, dict) and p.get("@classid") == "doi":
                doi = _oaf_text(p).replace("https://doi.org/", "")
                break
        year = None
        da = _oaf_text(r.get("dateofacceptance"))
        if da[:4].isdigit():
            year = int(da[:4])
        desc = r.get("description")
        if isinstance(desc, dict):
            desc = desc.get("$")
        elif isinstance(desc, list):
            desc = " ".join(_oaf_text(x) for x in desc)
        creators = r.get("creator")
        creators = creators if isinstance(creators, list) else [creators] if creators else []
        journal = r.get("journal")
        venue = (_oaf_text(journal) or "OpenAIRE")
        oid = _oaf_text(_oaf_node(res, "header", "dri:objIdentifier"))
        out.append({
            "cite_id": f"doi:{doi}" if doi else f"openaire:{oid[:16]}",
            "source": "openaire",
            "doi": doi,
            "title": title,
            "year": year,
            "venue": venue,
            "authors": ", ".join(_oaf_text(c) for c in creators[:6]),
            "abstract": (desc or "").strip(),
            "url": f"https://doi.org/{doi}" if doi else "",
            "cited_by": None,
        })
    return out


def _s2_paper_rec(p: dict) -> dict:
    """Normalize an S2 paper object to the scout record shape (same rules as search_s2)."""
    ext = p.get("externalIds") or {}
    doi, aid = ext.get("DOI", ""), ext.get("ArXiv", "")
    return {
        "cite_id": f"doi:{doi}" if doi else (f"arxiv:{aid}" if aid else f"s2:{p.get('paperId','')[:12]}"),
        "source": "semanticscholar",
        "doi": doi,
        "arxiv_id": aid,
        "title": (p.get("title") or "").strip(),
        "year": p.get("year"),
        "venue": p.get("venue") or "Semantic Scholar",
        "authors": ", ".join(a.get("name", "") for a in (p.get("authors") or [])[:6]),
        "abstract": (p.get("abstract") or "").strip(),
        "url": f"https://doi.org/{doi}" if doi else f"https://arxiv.org/abs/{aid}" if aid else "",
        "cited_by": p.get("citationCount"),
    }


def _post_json_s2(url: str, payload: dict, retries: int = 3) -> list | dict:
    """POST JSON with backoff. 只重试 429/5xx/网络错误；4xx（如 404）立即失败不假死。"""
    import time
    import urllib.error
    last: Exception | None = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                         headers={"User-Agent": UA, "Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code not in (429, 500, 502, 503, 504):
                raise  # 404 等：端点/ID 问题，重试无意义
            last = e
            time.sleep(min(8 * (i + 1), 30))
        except Exception as e:
            last = e
            time.sleep(min(8 * (i + 1), 30))
    raise RuntimeError(f"S2 POST failed after {retries} tries: {url} :: {last}")


def _s2_resolve(seed: str) -> str:
    """Resolve external id (DOI:/ARXIV:/...) to S2 internal paperId.

    recommendations 端点只认内部 paperId（DOI: 前缀会 404）；citations 端点两者皆收。
    """
    if not seed.startswith(("DOI:", "ARXIV:", "PMID:", "PMCID:", "ACL:", "MAG:", "CorpusId:")):
        return seed
    url = "https://api.semanticscholar.org/graph/v1/paper/batch?fields=paperId"
    resp = _post_json_s2(url, {"ids": [seed]})
    if isinstance(resp, list) and resp and resp[0] and resp[0].get("paperId"):
        return resp[0]["paperId"]
    raise RuntimeError(f"S2 cannot resolve seed to paperId: {seed}")


def recommend_s2(seed: str, n: int = 8) -> list[dict]:
    """S2 embedding-level recommendations from a seed paper.

    关键词召回的盲区补偿：'词不匹配但任务同构'的工作（如时序基础模型之于水文）
    靠语义相似度到达，不靠查询词。seed 格式：DOI:10.x/... 或 ARXIV:xxxx.xxxxx。
    端点：/recommendations/v1/papers/forpaper/{id}（2026-11-01 实测；
    /graph/v1/.../recommendations 已 404，batch 变体 405）。
    """
    url = ("https://api.semanticscholar.org/recommendations/v1/papers/forpaper/"
           + seed
           + "?" + urllib.parse.urlencode({"fields": S2_PAPER_FIELDS, "limit": str(n)}))
    data = json.loads(_get(url))
    return [_s2_paper_rec(p) for p in data.get("recommendedPapers", [])]


def forward_citations_s2(seed: str, n: int = 50) -> list[dict]:
    """S2 forward citations (谁引用了 seed) — 收束最新同域工作。

    引文雪球的另一半：references 只能看过去，forward citations 把"先例之后
    陆续跟进的工作"收进来，是发现最新先行工作（novelty 威胁）的主要通道。
    """
    url = ("https://api.semanticscholar.org/graph/v1/paper/"
           + urllib.parse.quote(seed, safe="")
           + "/citations?" + urllib.parse.urlencode({"fields": S2_PAPER_FIELDS, "limit": str(n)}))
    data = json.loads(_get(url))
    return [_s2_paper_rec(e.get("citingPaper") or {}) for e in data.get("data", [])]


def store_channel(run: Run, recs: list[dict], channel: str, seed: str) -> list[str]:
    """Store channel-retrieved records into the run DB (same provenance as search)."""
    ids = []
    for r in recs:
        if not r.get("title"):
            continue
        run.add_paper(
            cite_id=r["cite_id"], source=r["source"], title=r["title"],
            abstract=r.get("abstract", ""), year=r.get("year"), venue=r.get("venue", ""),
            authors=r.get("authors", ""), doi=r.get("doi", ""), arxiv_id=r.get("arxiv_id", ""),
            url=r.get("url", ""), extra={"channel": channel, "seed": seed, "cited_by": r.get("cited_by")},
        )
        ids.append(r["cite_id"])
    run.event("scout", channel, {"seed": seed, "n": len(ids)})
    run.cost("scout", "api_calls", 1, "requests", f"{channel}:{seed[:40]}")
    return ids


def search_datacite(query: str, n: int = 10) -> list[dict]:
    """DataCite — indexes arXiv DOIs, Zenodo/UCAR dataset records (CAMELS, CARAVAN etc.).

    Useful when OpenAlex/Crossref quota is exhausted: it is a registry, not a scraper,
    and its `descriptions` field gives verbatim text we can quote.
    """
    params = {"query": query, "page[size]": str(n), "sort": "relevance"}
    url = "https://api.datacite.org/dois?" + urllib.parse.urlencode(params)
    data = json.loads(_get(url))
    out = []
    for it in data.get("data", []):
        a = it.get("attributes", {})
        titles = a.get("titles") or []
        title = (titles[0].get("title") if titles else "").strip()
        desc = ""
        for d in a.get("descriptions") or []:
            if d.get("descriptionType") in ("Abstract", "Abstract "):
                desc = d.get("description", "")
                break
        if not desc and a.get("descriptions"):
            desc = a["descriptions"][0].get("description", "")
        doi = a.get("doi", "")
        year = a.get("publicationYear")
        out.append({
            "cite_id": f"doi:{doi}" if doi else f"datacite:{it.get('id','')[:12]}",
            "source": "datacite",
            "doi": doi,
            "title": title,
            "year": year,
            "venue": a.get("publisher") or "DataCite",
            "authors": ", ".join(c.get("name", "") for c in (a.get("creators") or [])[:6]),
            "abstract": (desc or "").strip(),
            "url": a.get("url") or (f"https://doi.org/{doi}" if doi else ""),
        })
    return out


def _pdf_to_text(pdf: Path) -> tuple[str, str]:
    """Extract PDF text. Prefer the local workbuddy-pdf CLI; fall back to pdftotext."""
    tmp = Path(tempfile.mkdtemp(prefix="dl-pdf-"))
    out_md = tmp / "content.md"
    if PDF_SCRIPT.exists() and shutil.which("sh"):
        cmd = ["sh", str(PDF_SCRIPT), str(pdf), str(out_md), "-f", "md", "-q"]
        try:
            subprocess.run(cmd, capture_output=True, timeout=600, check=False)
        except Exception:
            pass
        if out_md.exists() and out_md.stat().st_size > 2000:
            return out_md.read_text(encoding="utf-8", errors="ignore"), "workbuddy-pdf"
    if shutil.which("pdftotext"):
        try:
            subprocess.run(["pdftotext", "-layout", str(pdf), str(out_md)], check=False, timeout=300)
            if out_md.exists() and out_md.stat().st_size > 2000:
                return out_md.read_text(encoding="utf-8", errors="ignore"), "pdftotext"
        except Exception:
            pass
    # last resort: pypdf (pure python), useful when the CLI fails on a specific file
    try:
        from pypdf import PdfReader  # type: ignore

        reader = PdfReader(str(pdf))
        pages = []
        for pg in reader.pages:
            try:
                pages.append(pg.extract_text() or "")
            except Exception:
                continue
        text = "\n\n".join(p for p in pages if p.strip())
        if len(text) > 2000:
            out_md.write_text(text, encoding="utf-8")
            return text, "pypdf"
    except Exception:
        pass
    raise RuntimeError("no PDF extractor available (workbuddy-pdf CLI / pdftotext / pypdf)")


def ingest_pdf(run: Run, pdf_path: str, title: str | None = None) -> str:
    pdf = Path(pdf_path).expanduser().resolve()
    if not pdf.exists():
        raise FileNotFoundError(pdf)
    text, engine = _pdf_to_text(pdf)
    digest = hashlib.sha256(pdf.read_bytes()).hexdigest()[:12]
    cite_id = f"pdf:{digest}"
    first_line = next((l.strip("# ").strip() for l in text.splitlines() if len(l.strip()) > 20), pdf.stem)
    run.add_paper(
        cite_id=cite_id,
        source="local_pdf",
        title=title or first_line[:200],
        abstract=text[:4000],
        fulltext=text,
        year=None,
        venue=f"local PDF ({engine})",
        url=str(pdf),
        is_local=True,
        raw=pdf.read_bytes(),
        extra={"extractor": engine, "chars": len(text)},
    )
    run.event("scout", "pdf_ingested", {"cite_id": cite_id, "file": str(pdf), "chars": len(text)})
    run.cost("scout", "pdf_pages_est", len(text) / 1800, "pages", pdf.name)
    return cite_id


def search_and_store(run: Run, query: str, n: int = 10,
                     sources: tuple[str, ...] = ("arxiv", "datacite")) -> list[str]:
    ids: list[str] = []
    fn = {"openalex": search_openalex, "s2": search_s2, "arxiv": search_arxiv,
          "datacite": search_datacite, "openaire": search_openaire}
    for src in sources:
        try:
            recs = fn[src](query, n)
        except Exception as e:  # network hiccup must not silently fabricate
            run.event("scout", "search_failed", {"source": src, "query": query, "error": str(e)})
            continue
        kept = 0
        for r in recs:
            if not r.get("title"):
                continue
            run.add_paper(
                cite_id=r["cite_id"],
                source=r["source"],
                title=r["title"],
                abstract=r.get("abstract", ""),
                year=r.get("year"),
                venue=r.get("venue", ""),
                authors=r.get("authors", ""),
                doi=r.get("doi", ""),
                arxiv_id=r.get("arxiv_id", ""),
                url=r.get("url", ""),
                extra={"query": query, "cited_by": r.get("cited_by")},
            )
            ids.append(r["cite_id"])
            kept += 1
        run.event("scout", "search", {"source": src, "query": query, "n": kept})
        run.cost("scout", "api_calls", 1, "requests", f"{src}:{query[:40]}")
    return ids


def pick_sentence(run: Run, cite_id: str, keywords: list[str], min_len: int = 40) -> dict | None:
    """Pick a verbatim sentence from a stored abstract containing the keywords.

    The returned quote is always verified verbatim before being handed out — this is how
    hypotheses get citations that cannot be hallucinated: the text is copied from a
    fetched record, not generated.
    """
    row = run.get_paper(cite_id)
    if row is None:
        return None
    text = " ".join(((row["abstract"] or "") + " " + (row["fulltext"] or "")[:20000]).split())
    sents = re.split(r"(?<=[.!?])\s+", text)
    best = None
    for s in sents:
        if len(s) < min_len:
            continue
        hits = sum(1 for k in keywords if k.lower() in s.lower())
        if hits == 0:
            continue
        score = hits / max(len(keywords), 1) + min(len(s), 400) / 4000
        if best is None or score > best[0]:
            best = (score, s)
    if not best:
        return None
    quote = best[1].strip()
    for _ in range(3):
        ok, detail = run.verify_quote(cite_id, quote, used_by="scout.pick")
        if ok:
            return {"cite_id": cite_id, "quote": quote, "title": row["title"], "year": row["year"],
                    "field": detail.get("field")}
        quote = quote[:-1].rsplit(".", 1)[0] + "." if "." in quote[:-1] else quote
    return None


def prune_offtopic(run: Run, keep_keywords: list[str], dry_run: bool = False) -> dict:
    """Drop records whose title+abstract contain none of the domain keywords.

    Curation is logged, not silent: querying 'CAMELS streamflow' also returns the
    cosmology CAMELS project and a 3D-body paper, which would otherwise pollute the report.
    """
    kept, dropped = [], []
    for row in run.papers():
        blob = f"{row['title']} {row['abstract']}".lower()
        if any(k.lower() in blob for k in keep_keywords):
            kept.append(row["cite_id"])
        else:
            dropped.append({"cite_id": row["cite_id"], "title": row["title"][:90]})
    if not dry_run:
        for d in dropped:
            run.db.execute("DELETE FROM papers WHERE cite_id=?", (d["cite_id"],))
        run.db.commit()
        run.event("scout", "prune", {"dropped": dropped, "kept": len(kept)})
    return {"kept": len(kept), "dropped": dropped}


def verify(run: Run, quote: str, cite_id: str | None = None) -> dict:
    """Verify a quote against stored literature; optionally scoped to one paper."""
    if cite_id:
        ok, detail = run.verify_quote(cite_id, quote, used_by="scout.verify")
        return {"ok": ok, "cite_id": cite_id, **detail}
    hits = []
    for row in run.papers():
        ok, detail = run.verify_quote(row["cite_id"], quote, used_by="scout.verify")
        if ok:
            hits.append({"cite_id": row["cite_id"], "title": row["title"], **detail})
    return {"ok": bool(hits), "hits": hits}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="discovery_loop.scout")
    ap.add_argument("--run", required=True)
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("search")
    s.add_argument("query")
    s.add_argument("--n", type=int, default=10)
    s.add_argument("--sources", default="openalex,arxiv,s2,openaire",
                   help="comma-separated subset of: openalex,s2,arxiv,datacite")

    # 引文/语义通道：不依赖查询词的第二、第三召回路径（雪球 forward + embedding 推荐）
    s2r = sub.add_parser("s2rec")
    s2r.add_argument("seed", help="S2 paper id: DOI:10.x/... 或 ARXIV:xxxx.xxxxx")
    s2r.add_argument("--n", type=int, default=8)
    s2c = sub.add_parser("s2cites")
    s2c.add_argument("seed", help="S2 paper id: DOI:10.x/... 或 ARXIV:xxxx.xxxxx")
    s2c.add_argument("--n", type=int, default=50)

    p = sub.add_parser("pdf")
    p.add_argument("path")
    p.add_argument("--title", default=None)

    sub.add_parser("list")
    q = sub.add_parser("quote")
    q.add_argument("text")
    q.add_argument("--cite", default=None)

    a = ap.parse_args(argv)
    run = Run(a.run)
    if a.cmd == "search":
        sources = tuple(s.strip() for s in a.sources.split(",") if s.strip())
        ids = search_and_store(run, a.query, a.n, sources)
        for cid in ids:
            row = run.get_paper(cid)
            print(f"{cid}\t{row['year']}\t{row['title'][:70]}")
        return 0
    if a.cmd in ("s2rec", "s2cites"):
        recs = recommend_s2(a.seed, a.n) if a.cmd == "s2rec" else forward_citations_s2(a.seed, a.n)
        ids = store_channel(run, recs, a.cmd, a.seed)
        for cid in ids:
            row = run.get_paper(cid)
            print(f"{cid}\t{row['year']}\t{row['title'][:70]}")
        return 0
    if a.cmd == "pdf":
        cid = ingest_pdf(run, a.path, a.title)
        row = run.get_paper(cid)
        print(f"ingested {cid}: {row['title'][:80]} ({len(row['fulltext'])} chars)")
        return 0
    if a.cmd == "list":
        for row in run.papers():
            n_claims = len(run.verified_claims(row["cite_id"]))
            print(f"{row['cite_id']}\t{row['year']}\tclaims={n_claims}\t{row['title'][:64]}")
        return 0
    if a.cmd == "quote":
        res = verify(run, a.text, a.cite)
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0 if res.get("ok") else 3
    return 1


if __name__ == "__main__":
    sys.exit(main())
