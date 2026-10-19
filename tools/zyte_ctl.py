#!/usr/bin/env python3
"""Zyte Scrapy Cloud control + monitor for project 881926 (stdlib only).

Key is read at run time, never printed: env ZYTE_APIKEY, else macOS keychain
(service 'zyte-scrapycloud-apikey'). Store it once:
  security add-generic-password -a "$USER" -s zyte-scrapycloud-apikey -w   (prompts; paste key)

  zyte_ctl.py status                 project summary: running/pending + last finished jobs
  zyte_ctl.py job 1/3                one job: state, counts, errors
  zyte_ctl.py log 1/3 [-n 40]        newest log lines (WARNING+ by default; --all)
  zyte_ctl.py items 1/3 [-n 5]       first items
  zyte_ctl.py run SPIDER [k=v ...]   start a job (e.g. run seeded tier=daily cap=3)
  zyte_ctl.py stop 1/3               stop a job
  zyte_ctl.py land-check 1/5         compare Zyte item count with lines landed in R2 (read token)
  zyte_ctl.py land-file FILE.jl KEY  put a local jsonl file to R2 via the Worker (write token)

Landing: run injects job_settings LAND_URL/LAND_TOKEN so the job's pipeline writes to R2.
Config files ~/.config/zy/land_url, land_write, land_read (600), or env LAND_URL/LAND_WRITE/LAND_READ. Never printed.
  zyte_ctl.py watch [--every 30]     live refresh of status until Ctrl-C
"""
import argparse, base64, json, os, subprocess, sys, time, urllib.parse, urllib.request

PROJECT = "881926"
API = "https://app.zyte.com/api"
STORE = "https://storage.scrapinghub.com"


def key():
    k = os.environ.get("ZYTE_SC_API_KEY") or os.environ.get("ZYTE_APIKEY")
    for svc in ("zyte-scrapycloud-key", "zyte-sc-api-key", "zyte-scrapycloud-apikey"):
        if k:
            break
        r = subprocess.run(["security", "find-generic-password", "-s", svc, "-w"],
                           capture_output=True, text=True)
        k = r.stdout.strip()
    if not k:
        sys.exit("NO_KEY: set ZYTE_APIKEY or add keychain item zyte-scrapycloud-apikey")
    return k


def cfg(name, env):
    v = os.environ.get(env)
    if not v:
        try:
            v = open(os.path.expanduser(f"~/.config/zy/{name}")).read().strip()
        except OSError:
            v = ""
    return v


def land(name, env):
    v = cfg(name, env)
    if not v:
        sys.exit(f"NO_LAND_CONFIG: {name} (file ~/.config/zy/{name} or env {env})")
    return v


def worker(method, path, token, data=None):
    req = urllib.request.Request(land("land_url", "LAND_URL").rstrip("/") + path, data=data, method=method)
    req.add_header("Authorization", "Bearer " + token)
    req.add_header("User-Agent", "seonrin-index-collector/1.0")
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read()


def landed_lines(slug):
    """(files, lines) of every R2 file whose key contains /<slug>/."""
    tok, files, lines, cursor = land("land_read", "LAND_READ"), 0, 0, None
    while True:
        q = "/list?prefix=zyte/" + (("&cursor=" + urllib.parse.quote(cursor)) if cursor else "")
        r = json.loads(worker("GET", q, tok))
        for k in r["keys"]:
            if f"/{slug}/" in k["key"]:
                files += 1
                body = worker("GET", "/get?key=" + urllib.parse.quote(k["key"], safe="/"), tok)
                lines += sum(1 for l in body.splitlines() if l.strip())
        if not r["truncated"]:
            return files, lines
        cursor = r["cursor"]


def call(url, data=None):
    req = urllib.request.Request(url, data=urllib.parse.urlencode(data, doseq=True).encode() if data else None)
    req.add_header("Authorization", "Basic " + base64.b64encode((key() + ":").encode()).decode())
    with urllib.request.urlopen(req, timeout=30) as r:
        body = r.read().decode()
    try:
        return json.loads(body)
    except ValueError:
        return [json.loads(l) for l in body.splitlines() if l.strip()]


def jobs(state=None, count=10):
    q = {"project": PROJECT, "count": count}
    if state:
        q["state"] = state
    return call(f"{API}/jobs/list.json?" + urllib.parse.urlencode(q, doseq=True)).get("jobs", [])


def line(j):
    return (f"{j.get('id'):<10} {j.get('state','?'):<9} {j.get('spider','?'):<10} "
            f"items={j.get('items_scraped',0)} pages={j.get('responses_received',0)} "
            f"err={j.get('errors_count',0)} started={j.get('started_time','-')} {j.get('close_reason','')}")


def status():
    print(f"[{time.strftime('%F %T')}] project {PROJECT}")
    for st in ("running", "pending"):
        js = jobs(st, 20)
        print(f"-- {st}: {len(js)}")
        for j in js:
            print("  ", line(j))
    print("-- finished (latest 8)")
    for j in jobs("finished", 8):
        print("  ", line(j))


def main():
    p = argparse.ArgumentParser()
    s = p.add_subparsers(dest="cmd", required=True)
    s.add_parser("status")
    e = s.add_parser("export"); e.add_argument("job"); e.add_argument("--out", default="var/zyte_backup")
    for n in ("job", "log", "items", "stop"):
        x = s.add_parser(n); x.add_argument("job")
        if n in ("log", "items"):
            x.add_argument("-n", type=int, default=40 if n == "log" else 5)
        if n == "log":
            x.add_argument("--all", action="store_true")
    r = s.add_parser("run"); r.add_argument("spider"); r.add_argument("args", nargs="*")
    lc = s.add_parser("land-check"); lc.add_argument("job")
    lf = s.add_parser("land-file"); lf.add_argument("file"); lf.add_argument("key")
    w = s.add_parser("watch"); w.add_argument("--every", type=int, default=30)
    a = p.parse_args()

    if a.cmd == "status":
        status()
    elif a.cmd == "watch":
        try:
            while True:
                os.system("clear"); status(); time.sleep(a.every)
        except KeyboardInterrupt:
            pass
    elif a.cmd == "job":
        for j in call(f"{API}/jobs/list.json?project={PROJECT}&job={PROJECT}/{a.job}").get("jobs", []):
            print(json.dumps(j, ensure_ascii=False, indent=1))
    elif a.cmd == "log":
        q = {"format": "json", "count": a.n, "startts": 0}
        if not a.all:
            q["filter"] = '["level",">=",[30]]'
        for l in call(f"{STORE}/logs/{PROJECT}/{a.job}?" + urllib.parse.urlencode(q)):
            print(l.get("level"), str(l.get("message"))[:300])
    elif a.cmd == "items":
        for it in call(f"{STORE}/items/{PROJECT}/{a.job}?format=json&count={a.n}"):
            print(json.dumps(it, ensure_ascii=False)[:400])
    elif a.cmd == "export":  # read-only backup of every item of one job
        req = urllib.request.Request(f"{STORE}/items/{PROJECT}/{a.job}?format=jl")
        req.add_header("Authorization", "Basic " + base64.b64encode((key() + ":").encode()).decode())
        body = urllib.request.urlopen(req, timeout=120).read()
        os.makedirs(a.out, exist_ok=True)
        path = os.path.join(a.out, f"{PROJECT}_{a.job.replace('/', '_')}.jl")
        open(path, "wb").write(body)
        print(path, len(body), "bytes", sum(1 for l in body.splitlines() if l.strip()), "lines")
    elif a.cmd == "run":
        d = {"project": PROJECT, "spider": a.spider}
        extra = [x.split("=", 1) for x in a.args]
        for k, v in extra:
            d[k] = v  # spider arguments are passed as plain form fields
        if cfg("land_url", "LAND_URL") and cfg("land_write", "LAND_WRITE"):
            d["job_settings"] = json.dumps({"LAND_URL": land("land_url", "LAND_URL"),
                                            "LAND_TOKEN": land("land_write", "LAND_WRITE"), "LAND_BATCH_ITEMS": 500})
        else:
            print("NOTE: no landing config -> job runs WITHOUT R2 landing", file=sys.stderr)
        print(call(f"{API}/run.json", d))
    elif a.cmd == "land-check":
        j = call(f"{API}/jobs/list.json?project={PROJECT}&job={PROJECT}/{a.job}").get("jobs", [])[0]
        n = j.get("items_scraped", 0)
        files, lines = landed_lines(f"{PROJECT}-{a.job.replace('/', '-')}")
        ok = n == lines and n > 0
        print(f"job {a.job} state={j.get('state')} zyte_items={n} r2_files={files} r2_lines={lines} -> {'PASS' if ok else 'FAIL'}")
        sys.exit(0 if ok else 1)
    elif a.cmd == "land-file":
        body = open(a.file, "rb").read()
        print(worker("PUT", "/put?key=" + urllib.parse.quote(a.key, safe="/"), land("land_write", "LAND_WRITE"), body).decode())
    elif a.cmd == "stop":
        print(call(f"{API}/jobs/stop.json", {"project": PROJECT, "job": f"{PROJECT}/{a.job}"}))


if __name__ == "__main__":
    main()
