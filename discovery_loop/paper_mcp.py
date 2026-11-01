"""Stage 1b — Paper-as-tool: a real MCP server per paper (stdio, JSON-RPC 2.0).

Why this file matters
---------------------
Phase ② of the loop talks *about* papers. If that talk comes from the model's memory,
it hallucinates. So we expose the paper as tools and force every statement to come back
as a verbatim span with (char_start, char_end) into text we extracted ourselves.

Tools
-----
paper_info      metadata + hash + extraction engine
search          BM25-ish passage retrieval, returns verbatim passages + offsets
read_section    read a named section
check_claim     given a claim, return supporting passages + a lexical-support verdict
                (explicitly *not* entailment; the caller must read the spans)
quote_check     exact-substring verification of a quotation
outline         section list with char ranges

Protocol: MCP 2024-11-05, methods initialize / tools/list / tools/call / ping.
No third-party dependency; safe to launch from any MCP host.

Launch:
  python -m discovery_loop.paper_mcp serve --paper <file.pdf|file.md> --name drsi
  python -m discovery_loop.paper_mcp client-info --paper <...>     # prints mcpServers JSON
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections import Counter
from pathlib import Path

from .scout import _pdf_to_text

PROTO = "2024-11-05"
TOOLS = [
    {
        "name": "paper_info",
        "description": "Metadata for this paper: title, source path, extraction engine, char count, sha256.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "outline",
        "description": "List detected sections with character ranges, to plan reading.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "read_section",
        "description": "Return the full text of a section (by name or 0-based index).",
        "inputSchema": {
            "type": "object",
            "properties": {"name": {"type": "string"}, "index": {"type": "integer"}},
        },
    },
    {
        "name": "search",
        "description": "Retrieve the most relevant verbatim passages for a query (BM25). Returns char offsets.",
        "inputSchema": {
            "type": "object",
            "properties": {"query": {"type": "string"}, "k": {"type": "integer", "default": 5}},
            "required": ["query"],
        },
    },
    {
        "name": "check_claim",
        "description": (
            "Given a natural-language claim, return the passages that lexically support or contradict it, "
            "plus a verdict: supported_span_found / weak / no_support_found. Lexical support only — "
            "not entailment. If verdict is no_support_found the claim must not be quoted as the paper's finding."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"statement": {"type": "string"}},
            "required": ["statement"],
        },
    },
    {
        "name": "quote_check",
        "description": "Verify a quotation is verbatim in this paper; returns offsets and surrounding context.",
        "inputSchema": {
            "type": "object",
            "properties": {"quote": {"type": "string"}},
            "required": ["quote"],
        },
    },
]

_TOKEN = re.compile(r"[a-z0-9]+")
STOP = set(
    """the a an of to in for on and or with by from as at is are was were be been being that this these those
    we our it its their they them than then which who whom what when where how why not no can could may might
    using used use into over under between within across during both each more most less least such other""".split()
)


def tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN.findall((text or "").lower()) if t not in STOP and len(t) > 1]


class Paper:
    def __init__(self, path: str, name: str | None = None):
        p = Path(path).expanduser().resolve()
        self.path = p
        self.name = name or p.stem[:24]
        if p.suffix.lower() == ".pdf":
            self.text, self.engine = _pdf_to_text(p)
        else:
            self.text = p.read_text(encoding="utf-8", errors="ignore")
            self.engine = "plain"
        self.paras = self._paragraphs()
        self.sections = self._sections()
        self.df: Counter = Counter()
        self.para_tokens = []
        for para in self.paras:
            toks = tokenize(para["text"])
            self.para_tokens.append(Counter(toks))
            for t in set(toks):
                self.df[t] += 1
        self.N = max(1, len(self.paras))
        self.avg_len = sum(sum(c.values()) for c in self.para_tokens) / self.N

    def _paragraphs(self) -> list[dict]:
        out, start = [], 0
        for m in re.finditer(r"\n\s*\n", self.text):
            chunk = self.text[start : m.start()]
            if len(chunk.strip()) > 40:
                out.append({"text": chunk.strip(), "start": start})
            start = m.end()
        if start < len(self.text):
            tail = self.text[start:]
            if len(tail.strip()) > 40:
                out.append({"text": tail.strip(), "start": start})
        return out

    def _sections(self) -> list[dict]:
        heads = [(m.start(), m.group(0).strip()) for m in re.finditer(r"(?m)^#{1,3} .+$", self.text)]
        if not heads:
            heads = [(m.start(), m.group(0).strip()) for m in re.finditer(
                r"(?m)^(?:\d+(?:\.\d+)*)\s+[A-Z][A-Za-z \-]{4,60}$", self.text)]
        secs = []
        for i, (pos, name) in enumerate(heads):
            end = heads[i + 1][0] if i + 1 < len(heads) else len(self.text)
            secs.append({"index": i, "title": re.sub(r"^#+\s*", "", name)[:90], "start": pos, "end": end})
        return secs


    def sentence_spans(self, paragraph: dict, limit: int = 12) -> list[dict]:
        """Split one paragraph into sentences carrying absolute char offsets."""
        text, base = paragraph["text"], paragraph["char_start"]
        out, pos = [], 0
        for m in re.finditer(r"[^.!?\n]{25,400}[.!?]", text):
            seg = m.group(0).strip()
            if len(seg) < 25:
                continue
            out.append({"char_start": base + m.start(), "char_end": base + m.start() + len(m.group(0)),
                        "text": seg})
            pos += 1
            if pos >= limit:
                break
        return out

    def bm25(self, query: str, k: int = 5) -> list[dict]:
        q = tokenize(query)
        if not q:
            return []
        k1, b = 1.5, 0.75
        scores = []
        for i, tf in enumerate(self.para_tokens):
            dl = sum(tf.values())
            s = 0.0
            for term in q:
                if term not in tf:
                    continue
                idf = math.log(1 + (self.N - self.df[term] + 0.5) / (self.df[term] + 0.5))
                s += idf * (tf[term] * (k1 + 1)) / (tf[term] + k1 * (1 - b + b * dl / self.avg_len))
            if s > 0:
                scores.append((s, i))
        scores.sort(reverse=True)
        out = []
        for s, i in scores[:k]:
            p = self.paras[i]
            out.append({"score": round(s, 3), "char_start": p["start"],
                        "char_end": p["start"] + len(p["text"]), "text": p["text"][:1400]})
        return out

    def coverage(self, statement: str, passage: str) -> float:
        q = set(tokenize(statement))
        if not q:
            return 0.0
        p = set(tokenize(passage))
        return len(q & p) / len(q)


def _text(payload) -> dict:
    return {"content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False, indent=2)}]}


def call_tool(paper: Paper, name: str, args: dict) -> dict:
    if name == "paper_info":
        return _text({
            "name": paper.name, "path": str(paper.path), "engine": paper.engine,
            "chars": len(paper.text), "paragraphs": len(paper.paras),
            "sections": len(paper.sections), "first_400": paper.text[:400],
        })
    if name == "outline":
        return _text({"sections": [
            {"index": s["index"], "title": s["title"], "chars": s["end"] - s["start"]}
            for s in paper.sections]})
    if name == "read_section":
        idx = args.get("index")
        if idx is None:
            q = (args.get("name") or "").lower()
            for s in paper.sections:
                if q and q in s["title"].lower():
                    idx = s["index"]
                    break
        if idx is None or not (0 <= idx < len(paper.sections)):
            return _text({"error": "section not found", "available": [s["title"] for s in paper.sections]})
        s = paper.sections[idx]
        return _text({"title": s["title"], "text": paper.text[s["start"]:s["end"]][:12000]})
    if name == "search":
        passages = paper.bm25(args["query"], int(args.get("k", 5)))
        return _text({"query": args["query"], "n": len(passages), "passages": passages})
    if name == "check_claim":
        st = args["statement"]
        passages = paper.bm25(st, 4)
        sents = []
        for p in passages:
            for sp in paper.sentence_spans(p):
                sp["lexical_coverage"] = round(paper.coverage(st, sp["text"]), 3)
                sents.append(sp)
        sents.sort(key=lambda x: -x["lexical_coverage"])
        best_sent = sents[0]["lexical_coverage"] if sents else 0.0
        best_pass = max((paper.coverage(st, p["text"]) for p in passages), default=0.0)
        best = round(max(best_sent, best_pass), 3)
        if best >= 0.55:
            verdict = "supported_span_found"
        elif best >= 0.35:
            verdict = "partial_support"
        else:
            verdict = "no_support_found"
        return _text({
            "statement": st, "verdict": verdict, "best_coverage": best,
            "best_sentence_coverage": best_sent,
            "note": ("lexical support only, not entailment. partial_support means some key terms co-occur but "
                     "the relation is not stated; no_support_found => do not cite this paper."),
            "evidence_sentences": sents[:3],
            "passages": [{**p, "lexical_coverage": round(paper.coverage(st, p["text"]), 3)} for p in passages][:2],
        })
    if name == "quote_check":
        needle = " ".join(args["quote"].split()).lower()
        hay = " ".join(paper.text.split()).lower()
        pos = hay.find(needle)
        if pos < 0:
            return _text({"ok": False, "reason": "not verbatim in this paper"})
        return _text({"ok": True, "char_start_normalized": pos,
                      "context": paper.text[max(0, pos - 200): pos + len(args["quote"]) + 200]})
    raise ValueError(f"unknown tool {name}")


def serve(paper: Paper) -> int:
    def send(obj):
        sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
        sys.stdout.flush()

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            send({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}})
            continue
        mid, method, params = msg.get("id"), msg.get("method"), msg.get("params") or {}
        if method == "initialize":
            send({"jsonrpc": "2.0", "id": mid, "result": {
                "protocolVersion": PROTO,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": f"paper-{paper.name}", "version": "0.1.0"}}})
        elif method == "tools/list":
            send({"jsonrpc": "2.0", "id": mid, "result": {"tools": TOOLS}})
        elif method == "tools/call":
            try:
                res = call_tool(paper, params.get("name", ""), params.get("arguments") or {})
                send({"jsonrpc": "2.0", "id": mid, "result": res})
            except Exception as e:
                send({"jsonrpc": "2.0", "id": mid,
                      "result": {"content": [{"type": "text", "text": f"error: {e}"}], "isError": True}})
        elif method in ("notifications/initialized", "initialized"):
            continue
        elif method == "ping":
            send({"jsonrpc": "2.0", "id": mid, "result": {}})
        elif mid is not None:
            send({"jsonrpc": "2.0", "id": mid,
                  "error": {"code": -32601, "message": f"method not found: {method}"}})
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="discovery_loop.paper_mcp")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("serve")
    s.add_argument("--paper", required=True)
    s.add_argument("--name", default=None)
    i = sub.add_parser("client-info")
    i.add_argument("--paper", required=True)
    i.add_argument("--name", default="paper")
    a = ap.parse_args(argv)
    if a.cmd == "serve":
        return serve(Paper(a.paper, a.name))
    if a.cmd == "client-info":
        path = Path(a.paper).expanduser().resolve()
        cfg = {"mcpServers": {f"paper-{a.name}": {
            "command": sys.executable,
            "args": ["-m", "discovery_loop.paper_mcp", "serve", "--paper", str(path), "--name", a.name],
            "env": {}}}}
        print(json.dumps(cfg, ensure_ascii=False, indent=2))
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
