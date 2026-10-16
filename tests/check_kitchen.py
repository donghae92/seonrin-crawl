"""Assertions over the rehearsal outputs in $R3K_DIR. Exit 0 only if every check passes."""
import collections, csv, json, os, re, subprocess, sys, tempfile
DIR = os.environ.get("R3K_DIR", "/tmp/r3k")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
fails = []


def ck(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail and not ok else ""))
    if not ok: fails.append(name)


def rows(n): return [json.loads(l) for l in open(os.path.join(DIR, n)) if l.strip()]


r0, r1, sc = rows("items0.jsonl"), rows("items1.jsonl"), rows("scout.jsonl")
log = open(os.path.join(DIR, "req.log")).read().splitlines()
hits = collections.Counter(l.split(" ", 1)[1] for l in log)
by = lambda rs, h: [r for r in rs if r.get("host") == h]
A, B, C, DEAD, D = "127.0.0.1:18201", "localhost:18202", "127.0.0.1:18203", "127.0.0.1:18299", "127.0.0.1:18204"

# 1 strict cap (counts scheduled pages: ok + blocked + error rows)
ck("cap A<=10", len(by(r0, A)) <= 10, len(by(r0, A))); ck("cap B<=8", len(by(r0, B)) <= 8, len(by(r0, B)))
ck("cap C<=12", len(by(r0, C)) <= 12, len(by(r0, C)))
# 2 recent mode + robots deny
pa = {r["url"].rsplit("/", 1)[1] for r in by(r0, A) if r.get("status") == 200}
ck("A recent = 9 newest pages", pa == {f"p{i}" for i in range(9)}, sorted(pa))
ck("A robots-denied page never requested", hits["/private/secret"] == 0, hits["/private/secret"])
ck("A denied page leaves a visible error row", any("IgnoreRequest" in (r.get("error") or "") for r in by(r0, A)))
# 3 links mode, block, outlinks
ck("B has blocked row", any(r.get("blocked") for r in by(r0, B)))
seed = [r for r in by(r0, B) if r.get("source") == "seed"][0]
ck("B outlinks recorded", A in seed["outlink_hosts"] and C in seed["outlink_hosts"], seed.get("outlink_hosts"))
# 4 sitemap index + gz + rotate + 429 once
c0 = {r["url"] for r in by(r0, C)}; c1 = {r["url"] for r in by(r1, C)}
ck("C rotate slices disjoint", not (c0 & c1), len(c0 & c1)); ck("C slice sizes = cap", len(c0) == 12 and len(c1) == 12, (len(c0), len(c1)))
ck("C 429 recorded as blocked", any(r.get("blocked") and r.get("status") == 429 for r in by(r0, C)))
st0 = open(os.path.join(DIR, "items0.jsonl.log")).read()
ck("429 answered exactly once and never retried", "'downloader/response_status_count/429': 1," in st0 and "retry/reason_count/429" not in st0)
# 5 dead host visible
ck("dead host leaves an error row", any("unreachable" in (r.get("error") or "") for r in by(r0, DEAD)))
# 6 extraction
ok = [r for r in r0 if r.get("status") == 200 and r.get("text")]
tra = [r for r in ok if r["extractor"] == "trafilatura"]
if tra:
    ck("menu text removed", all("사이트맵" not in r["text"] for r in tra))
    ck("Korean author kept", all(r["author"] == "김철수" for r in tra if r["host"] in (A, B, C)), "")
    ck("date kept", all((r["published"] or "").startswith("2026-10-") for r in tra))
else:
    ck("fallback extractor still yields text", bool(ok) and all(r["extractor"] == "xpath" for r in ok))
if os.path.exists(os.path.join(DIR, "items0_fb.jsonl")):
    fb = rows("items0_fb.jsonl")
    ck("fallback run: all xpath", all(r.get("extractor") == "xpath" for r in fb if r.get("text")))
    ck("fallback run fetches the same pages", {r["url"] for r in fb if r.get("status") == 200} == {r["url"] for r in r0 if r.get("status") == 200})
# 7 scout
sys.path.insert(0, os.path.join(ROOT, "tools"))
from scout_report import verdicts
v = verdicts(sc)
ck("scout A OK", v[A][0] == "OK", v.get(A)); ck("scout C OK", v[C][0] == "OK", v.get(C))
ck("scout B OK or BLOCKED", v[B][0] in ("OK", "BLOCKED"), v.get(B))
ck("scout robots-denied host", v[D][0] == "ROBOTS_DENIED", v.get(D))
ck("scout dead host ERROR", v[DEAD][0] == "ERROR", v.get(DEAD))
vh = verdicts(rows("scout_hosts.jsonl"))
ck("scout hosts= argument works without a file", (vh[A][0], vh[D][0], vh[DEAD][0]) == ("OK", "ROBOTS_DENIED", "ERROR"), vh)
ck("scout never fetched the denied site's pages", {l for l in log if l.startswith("18204 ")} == {"18204 /robots.txt"}, {l for l in log if l.startswith("18204 ")})
# 8 converter
SPEC_OK = os.path.isfile(os.path.join(os.environ.get("INDEX_SPEC") or os.path.expanduser("~/index-spec"), "index_spec_ref.py"))
if SPEC_OK:
    docs = [json.loads(l) for l in open(os.path.join(DIR, "convert", "docs.jsonl"))]
    ps = [json.loads(l) for l in open(os.path.join(DIR, "convert", "passages.jsonl"))]
    rej = [json.loads(l) for l in open(os.path.join(DIR, "convert", "rejected.jsonl"))]
    ck("convert: docs and passages exist", len(docs) > 0 and len(ps) >= len(docs))
    ck("convert: every passage 40..800 chars", all(40 <= len(p["text"]) <= 800 for p in ps))
    ck("convert: ids well-formed", all(re.fullmatch(r"[0-9a-f]{64}:[0-9a-f]{8}:\d{4}", p["passage_id"]) for p in ps))
    ck("convert: repeated rows rejected as duplicate", sum(r["reason"] == "duplicate" for r in rej) >= len({d["doc_id"] for d in docs}) - 1,
       collections.Counter(r["reason"] for r in rej))
    ck("convert: blocked/error rows rejected", {"blocked", "fetch_fail"} <= {r["reason"] for r in rej}, collections.Counter(r["reason"] for r in rej))
else:
    print("SKIP convert checks: ~/index-spec not found")
# 9 outlink graph
g = list(csv.DictReader(open(os.path.join(DIR, "graph.csv"))))
ck("graph: A is linked from >= 2 seed sites", any(x["host"] == A and int(x["distinct_seed_sites"]) >= 2 for x in g), g[:3])
# 10 merge_candidates
with tempfile.TemporaryDirectory() as t:
    for n, rowsx in (("s1.csv", [["insurance.terms", "금감원", "https://www.fss.or.kr/", "gov", "T1", "ko", "x", "https://www.fss.or.kr/a"],
                                  ["insurance.terms", "생보협", "https://www.klia.or.kr/", "assoc", "T2", "ko", "x", "https://www.klia.or.kr/a"]]),
                     ("s2.csv", [["insurance.claim", "금감원2", "https://www.fss.or.kr/", "gov", "T0", "ko", "y", "https://www.fss.or.kr/b"],
                                 ["life.traffic", "bad", "http://insecure.example/", "gov", "T1", "ko", "z", ""]])):
        with open(os.path.join(t, n), "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f); w.writerow(["subtopic", "name", "url", "org_type", "authority_tier", "language", "why", "sample_url"]); w.writerows(rowsx)
    out = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "merge_candidates.py"), os.path.join(t, "s1.csv"), os.path.join(t, "s2.csv"),
                          "--out-txt", os.path.join(t, "c.txt"), "--out-csv", os.path.join(t, "m.csv")], capture_output=True, text=True).stdout
    m = list(csv.DictReader(open(os.path.join(t, "m.csv"))))
    ck("merge: one row per host, best tier wins", [x["authority_tier"] for x in m if "fss.or.kr" in x["url"]] == ["T0"] and len(m) == 2, out)
    ck("merge: non-https row rejected", "not https" in out, out)
print("\nRESULT:", "ALL PASS" if not fails else f"{len(fails)} FAIL {fails}")
sys.exit(1 if fails else 0)
