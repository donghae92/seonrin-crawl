#!/usr/bin/env python3
"""Per-site health of a collection run (the table used to judge a month of running).
usage: site_report.py items"""
import os, statistics as st, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from items_io import read_items

def main():
    rows = read_items(sys.argv[1])
    by = {}
    for r in rows:
        if r.get("host"): by.setdefault(r["host"], []).append(r)
    seen, dup = set(), {}
    print(f"{'host':32}{'rows':>5}{'ok':>5}{'blk':>4}{'err':>4}{'med_chars':>10}{'thin':>5}{'auth%':>6}{'date%':>6}{'dup%':>5}  extractor")
    for h, rs in sorted(by.items(), key=lambda x: -len(x[1])):
        ok = [r for r in rs if r.get("status") == 200 and r.get("text")]
        L = [len(r["text"]) for r in ok]
        d = sum(1 for r in ok if r.get("content_hash") in seen)
        for r in ok: seen.add(r.get("content_hash"))
        pc = lambda n: round(100 * n / len(ok)) if ok else 0
        ex = {}
        for r in ok: ex[r.get("extractor")] = ex.get(r.get("extractor"), 0) + 1
        print(f"{h:32}{len(rs):>5}{len(ok):>5}{sum(1 for r in rs if r.get('blocked') in (True,'true','True')):>4}"
              f"{sum(1 for r in rs if r.get('error')):>4}{(int(st.median(L)) if L else 0):>10}{sum(1 for l in L if l < 500):>5}"
              f"{pc(sum(1 for r in ok if r.get('author'))):>6}{pc(sum(1 for r in ok if r.get('published'))):>6}{pc(d):>5}  {ex}")

if __name__ == "__main__":
    main()
