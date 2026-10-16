#!/usr/bin/env python3
"""Read the scout spider's items: one verdict per candidate host. --write-seeds appends OK hosts as seed lines.
usage: scout_report.py items [--write-seeds seeds_weekly.txt --cap 40 --mode auto]"""
import argparse, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from items_io import read_items

def verdicts(rows):
    by = {}
    for r in rows:
        if r.get("host"): by.setdefault(r["host"], []).append(r)
    out = {}
    for h, rs in by.items():
        if any(r.get("robots") == "denied" for r in rs): v = "ROBOTS_DENIED"
        elif any(r.get("blocked") in (True, "true", "True") for r in rs): v = "BLOCKED"
        elif any(r.get("status") == 200 and int(r.get("readable_chars") or 0) >= 1000 for r in rs): v = "OK"
        elif any(r.get("status") == 200 for r in rs): v = "THIN"
        elif any(r.get("error") for r in rs): v = "ERROR"
        else: v = "NO_ANSWER"
        best = max((int(r.get("readable_chars") or 0) for r in rs), default=0)
        out[h] = (v, best, max((int(r.get("sitemap_n") or 0) for r in rs), default=0), rs[0].get("url"))
    return out

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("items"); ap.add_argument("--write-seeds"); ap.add_argument("--cap", default="40"); ap.add_argument("--mode", default="auto")
    a = ap.parse_args()
    v = verdicts(read_items(a.items))
    order = {"OK": 0, "THIN": 1, "BLOCKED": 2, "ROBOTS_DENIED": 3, "ERROR": 4, "NO_ANSWER": 5}
    for h, (k, best, sm, url) in sorted(v.items(), key=lambda x: (order[x[1][0]], x[0])):
        print(f"{k:14}{h:34} readable={best:>6} sitemaps={sm}")
    cnt = {}
    for k, *_ in v.values(): cnt[k] = cnt.get(k, 0) + 1
    print("summary:", cnt)
    if a.write_seeds:
        with open(a.write_seeds, "a", encoding="utf-8") as f:
            for h, (k, best, sm, url) in sorted(v.items()):
                if k == "OK": f.write(f"{url} cap={a.cap} mode={a.mode}\n")

if __name__ == "__main__":
    main()
