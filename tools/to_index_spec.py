#!/usr/bin/env python3
"""Zyte items (CSV/JSONL) -> spec records (doc / passage / lexical / rejected) that pass ~/index-spec/schemas.json.
Everything the spec decides comes from its reference implementation (index_spec_ref.py): ids, url normalisation,
domain_grade, chunking (40..800 chars, 120 overlap), lexical terms, angles. No field is invented here.
category comes from a category map (spec: the seed file decides, a collector never judges a topic); a host with no
category is rejected as `seed_out`. collector = the machine that runs this converter (mini by default).
usage: to_index_spec.py items --out DIR --category-map FILE [--spec DIR] [--collector mini] [--min-chars 200]
category map: one line per host:  <host as in the items' host column>  <category_id>   ('#' comments allowed)
--source/--grade are accepted and ignored (source is `web`; grade is derived by the spec)."""
import argparse, importlib.util, json, os, re, sys
from datetime import datetime, timezone, timedelta
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from items_io import read_items

KST = timezone(timedelta(hours=9))
OFFICIAL = (".go.kr", ".or.kr", ".ac.kr", ".gov", ".edu")
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def load_spec(spec_dir=None):
    d = spec_dir or os.environ.get("INDEX_SPEC") or os.path.expanduser("~/index-spec")
    path = os.path.join(d, "index_spec_ref.py")
    if not os.path.isfile(path):
        sys.exit(f"index spec reference not found: {path} (use --spec DIR)")
    sp = importlib.util.spec_from_file_location("index_spec_ref", path)
    m = importlib.util.module_from_spec(sp)
    sys.modules["index_spec_ref"] = m
    sp.loader.exec_module(m)
    return m


def read_category_map(path):
    out = {}
    for line in open(path, encoding="utf-8"):
        line = line.split("#", 1)[0].split()
        if len(line) >= 2:
            out[line[0]] = line[1]
    return out


def to_kst(iso):
    try:
        t = datetime.fromisoformat(iso)
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        return t.astimezone(KST).replace(microsecond=0).isoformat()
    except Exception:
        return None


def trace_priority(host, author, published):
    return int(host.endswith(OFFICIAL)) + int(bool(published)) + int(bool(author))


def convert(rows, spec, categories, collector="mini", min_chars=200):
    docs, passages, lexicals, rejected, seen, prio = [], [], [], [], set(), {}
    at = spec.now_kst()

    def reject(url, reason, note=""):
        r = {"kind": "rejected", "spec": spec.SPEC, "url": url or "", "reason": reason, "at": at, "collector": collector}
        if note:
            r["note"] = note
        rejected.append(r)

    for r in rows:
        url, text = r.get("url"), (r.get("text") or "")
        if r.get("blocked") in (True, "true", "True"): reject(url, "blocked"); continue
        if r.get("error"): reject(url, "fetch_fail", str(r.get("error"))[:200]); continue
        if r.get("status") != 200: reject(url, "fetch_fail", f"status {r.get('status')}"); continue
        if len(text) < min_chars: reject(url, "empty", "too_short"); continue
        host = r.get("host") or ""
        cat = categories.get(host)
        if not cat: reject(url, "seed_out", f"no category for host {host}"); continue
        chash = spec.sha256(text)
        if chash in seen: reject(url, "duplicate"); continue
        pieces = spec.chunk_text(text)
        if not pieces: reject(url, "empty", "no_passage"); continue
        seen.add(chash)
        name = (r.get("author") or "").strip()
        grade = spec.domain_grade(url)
        author = None
        if name:   # name read by the crawler from page metadata (jsonld/meta); the exact source tag is not kept in items
            author = {"name": name, "type": spec.classify_author(name, name, grade, "meta"), "affiliation": "",
                      "evidence": "meta", "evidence_text": name}
        pub = r.get("published")
        doc = spec.make_doc(url=url, source="web", collector=collector, body_text=text,
                            seed={"category": cat, "url": url}, title=(r.get("title") or "").strip(),
                            site_name=(r.get("site_name") or "").strip(), author=author,
                            published_at=pub if pub and DATE.match(pub) else None,
                            lang=r.get("lang") if re.fullmatch(r"[a-z]{2}", r.get("lang") or "") else "und")
        doc["fetched_at"] = to_kst(r.get("fetched_at") or "") or doc["fetched_at"]
        ps = spec.make_passages(doc, [("body", "", p) for p in pieces])
        docs.append(doc); passages.extend(ps); lexicals.extend(spec.lexical_records(doc, ps))
        prio[doc["doc_id"]] = trace_priority(host, name, pub)
    return docs, passages, lexicals, rejected, prio


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("items"); ap.add_argument("--out", required=True)
    ap.add_argument("--category-map", required=True); ap.add_argument("--spec")
    ap.add_argument("--collector", default="mini"); ap.add_argument("--min-chars", type=int, default=200)
    ap.add_argument("--source"); ap.add_argument("--grade")   # accepted, ignored
    a = ap.parse_args()
    spec = load_spec(a.spec)
    docs, passages, lexicals, rej, prio = convert(read_items(a.items), spec, read_category_map(a.category_map),
                                                  a.collector, a.min_chars)
    os.makedirs(a.out, exist_ok=True)
    for name, data in (("docs", docs), ("passages", passages), ("lexical", lexicals), ("rejected", rej)):
        with open(os.path.join(a.out, f"{name}.jsonl"), "w", encoding="utf-8") as f:
            for x in data: f.write(json.dumps(x, ensure_ascii=False) + "\n")
    trace = [d for d, p in prio.items() if p >= 2]
    with open(os.path.join(a.out, "trace_candidates.txt"), "w") as f:
        f.write("".join(d + "\n" for d in trace))
    s = {"docs": len(docs), "passages": len(passages), "lexical": len(lexicals), "rejected": len(rej),
         "trace_candidates_docs": len(trace), "lexical_only_docs": len(docs) - len(trace),
         "avg_passage_chars": round(sum(len(p["text"]) for p in passages) / max(1, len(passages)), 1)}
    json.dump(s, open(os.path.join(a.out, "summary.json"), "w"), ensure_ascii=False, indent=1)
    print(json.dumps(s, ensure_ascii=False))


if __name__ == "__main__":
    main()
