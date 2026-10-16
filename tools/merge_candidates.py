#!/usr/bin/env python3
"""Merge the research sessions' CSVs (one per session) into crawler/candidates.txt.
Columns required: subtopic,name,url,org_type,authority_tier,language,why,sample_url
Rules: one row per host (best tier T0<T1<T2 wins), max 10 hosts per subtopic, https only.
usage: merge_candidates.py CSV... --out-txt crawler/candidates.txt --out-csv merged.csv"""
import argparse, csv, sys
from urllib.parse import urlparse

COLS = ["subtopic", "name", "url", "org_type", "authority_tier", "language", "why", "sample_url"]
RANK = {"T0": 0, "T1": 1, "T2": 2}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("csvs", nargs="+"); ap.add_argument("--out-txt", required=True); ap.add_argument("--out-csv", required=True)
    ap.add_argument("--per-subtopic", type=int, default=10)
    a = ap.parse_args()
    best, bad = {}, []
    for p in a.csvs:
        for i, r in enumerate(csv.DictReader(open(p, encoding="utf-8-sig")), 2):
            if any(c not in r for c in COLS): bad.append((p, i, "missing columns")); continue
            u = urlparse((r["url"] or "").strip())
            if u.scheme != "https" or not u.hostname: bad.append((p, i, "not https url")); continue
            if r["authority_tier"] not in RANK: bad.append((p, i, "tier must be T0/T1/T2")); continue
            h = u.hostname
            if h not in best or RANK[r["authority_tier"]] < RANK[best[h]["authority_tier"]]:
                best[h] = r
    per, kept = {}, []
    for h, r in sorted(best.items(), key=lambda x: (RANK[x[1]["authority_tier"]], x[0])):
        per[r["subtopic"]] = per.get(r["subtopic"], 0) + 1
        if per[r["subtopic"]] <= a.per_subtopic: kept.append(r)
    with open(a.out_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLS); w.writeheader(); w.writerows(kept)
    with open(a.out_txt, "w", encoding="utf-8") as f:
        f.write("# candidates for the scout spider (merged)\n")
        for r in kept: f.write(r["url"].strip() + "\n")
    print(f"{len(kept)} hosts kept from {len(best)} unique ({len(bad)} rows rejected)")
    for b in bad: print("rejected", *b)

if __name__ == "__main__":
    main()
