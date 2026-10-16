#!/usr/bin/env python3
"""Which other sites do our seed sites point at? Rank outside hosts by how many DIFFERENT seed sites link to them.
usage: outlink_graph.py items --out candidates.csv [--min-sources 2] [--top 200]"""
import argparse, csv, glob, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from items_io import read_items
from urllib.parse import urlparse

BLOCK = {"facebook.com", "twitter.com", "x.com", "instagram.com", "youtube.com", "youtu.be", "linkedin.com",
         "google.com", "goo.gl", "apple.com", "play.google.com", "apps.apple.com", "kakao.com", "t.me", "line.me",
         "pinterest.com", "naver.com", "blog.naver.com", "tistory.com", "github.com", "w3.org", "adobe.com"}

def reg(h):
    return h[4:] if h.startswith("www.") else h

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("items"); ap.add_argument("--out", required=True)
    ap.add_argument("--min-sources", type=int, default=2); ap.add_argument("--top", type=int, default=200)
    ap.add_argument("--seeds-glob", default=os.path.join(os.path.dirname(__file__), "..", "crawler", "seeds_*.txt"))
    a = ap.parse_args()
    known = set()
    for f in glob.glob(a.seeds_glob):
        for l in open(f, encoding="utf-8"):
            if l.strip() and not l.startswith("#"):
                known.add(reg(urlparse(l.split()[0]).hostname or ""))
    g = {}
    for r in read_items(a.items):
        src, ol = r.get("host"), r.get("outlink_hosts")
        if not src or not ol: continue
        for part in ol.split(";"):
            h, _, c = part.rpartition(":")
            if not h or reg(h) in known or reg(h) in BLOCK or reg(h) == reg(src): continue
            e = g.setdefault(reg(h), {"sources": {}, "mentions": 0})
            e["sources"][src] = e["sources"].get(src, 0) + 1
            e["mentions"] += int(c or 1)
    rows = [(h, len(e["sources"]), e["mentions"], ";".join(sorted(e["sources"])[:5])) for h, e in g.items()
            if len(e["sources"]) >= a.min_sources]
    rows.sort(key=lambda x: (-x[1], -x[2], x[0]))
    with open(a.out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(["host", "distinct_seed_sites", "mentions", "linked_from"]); w.writerows(rows[:a.top])
    print(f"{len(g)} outside hosts seen, {len(rows)} linked from >= {a.min_sources} seed sites -> {a.out}")

if __name__ == "__main__":
    main()
