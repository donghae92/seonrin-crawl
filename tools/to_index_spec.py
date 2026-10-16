#!/usr/bin/env python3
"""Zyte items (CSV/JSONL) -> docs.jsonl + passages.jsonl in the night-work chunk rules (master 2-2).
Chunking: collapse spaces, <=800 chars cut back to a sentence/line boundary (keep >= half), next passage
overlaps 120 chars, pieces < 40 chars dropped.  passage_id = doc_id(64):version[:8]:ord(4).
The spec-facing fields (source, grade) are arguments: the real spec (~/index-spec/schemas.json) decides
whether they are accepted - validate there before ingest.
usage: to_index_spec.py items --out DIR [--source web_crawl] [--grade B] [--min-chars 200]"""
import argparse, hashlib, json, os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from items_io import read_items

OFFICIAL = (".go.kr", ".or.kr", ".ac.kr", ".gov", ".edu")


def chunk_text(text, size=800, overlap=120, minlen=40):
    t = re.sub(r"[ \t\r\f\v]+", " ", text)
    t = re.sub(r"\n{2,}", "\n", t).strip()
    out, pos, n = [], 0, len(t)
    while pos < n:
        end = min(pos + size, n)
        if end < n:
            lo, cut = pos + size // 2, -1
            for m in ("다. ", ". ", "\n"):
                i = t.rfind(m, lo, end)
                if i >= 0:
                    cut = max(cut, i + len(m))
            if cut > 0:
                end = cut
        chunk = t[pos:end].strip()
        if len(chunk) >= minlen:
            out.append(chunk)
        if end >= n:
            break
        pos = max(end - overlap, pos + 1)
    return out


def trace_priority(host, author, published):
    return int(host.endswith(OFFICIAL)) + int(bool(published)) + int(bool(author))


def convert(rows, source, grade, min_chars):
    docs, passages, rejected, seen = [], [], [], set()
    for r in rows:
        url, text = r.get("url"), (r.get("text") or "")
        why = None
        if r.get("blocked") in (True, "true", "True"): why = "blocked"
        elif r.get("error"): why = "error"
        elif r.get("status") != 200: why = f"status_{r.get('status')}"
        elif len(text) < min_chars: why = "too_short"
        elif r.get("content_hash") in seen: why = "duplicate"
        if why:
            rejected.append({"url": url, "why": why}); continue
        seen.add(r.get("content_hash"))
        doc_id = hashlib.sha256(url.encode()).hexdigest()
        ver = r.get("content_hash") or hashlib.sha256(text.encode()).hexdigest()
        host = r.get("host") or ""
        pri = trace_priority(host, r.get("author") or r.get("site_name"), r.get("published"))
        pieces = chunk_text(text)
        if not pieces:
            rejected.append({"url": url, "why": "no_passage"}); continue
        docs.append({"doc_id": doc_id, "version": ver, "url": url, "host": host, "title": r.get("title"),
                     "author": r.get("author") or r.get("site_name"), "author_kind": "meta" if r.get("author") else ("site_name" if r.get("site_name") else None), "published": r.get("published"), "lang": r.get("lang"),
                     "fetched_at": r.get("fetched_at"), "source": source, "grade": grade, "chars": len(text),
                     "passages": len(pieces), "trace_priority": pri, "lexical_only": pri < 2,
                     "extractor": r.get("extractor")})
        for i, p in enumerate(pieces):
            passages.append({"passage_id": f"{doc_id}:{ver[:8]}:{i:04d}", "doc_id": doc_id, "ord": i, "text": p, "chars": len(p)})
    return docs, passages, rejected


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("items"); ap.add_argument("--out", required=True)
    ap.add_argument("--source", default="web_crawl"); ap.add_argument("--grade", default="B")
    ap.add_argument("--min-chars", type=int, default=200)
    a = ap.parse_args()
    docs, passages, rej = convert(read_items(a.items), a.source, a.grade, a.min_chars)
    os.makedirs(a.out, exist_ok=True)
    for name, data in (("docs", docs), ("passages", passages), ("rejected", rej)):
        with open(os.path.join(a.out, f"{name}.jsonl"), "w", encoding="utf-8") as f:
            for x in data: f.write(json.dumps(x, ensure_ascii=False) + "\n")
    lex = sum(d["lexical_only"] for d in docs)
    s = {"docs": len(docs), "passages": len(passages), "rejected": len(rej),
         "trace_candidates_docs": len(docs) - lex, "lexical_only_docs": lex,
         "avg_passage_chars": round(sum(p["chars"] for p in passages) / max(1, len(passages)), 1)}
    json.dump(s, open(os.path.join(a.out, "summary.json"), "w"), ensure_ascii=False, indent=1)
    print(json.dumps(s, ensure_ascii=False))


if __name__ == "__main__":
    main()
