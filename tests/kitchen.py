"""Kitchen control for the rehearsal. up: start fake sites detached and wait until healthy. down: stop them."""
import os, signal, subprocess, sys, time, urllib.request

DIR = os.environ.get("R3K_DIR", "/tmp/r3k")
PID = os.path.join(DIR, "sites.pid")
HERE = os.path.dirname(os.path.abspath(__file__))


def healthy():
    try:
        return urllib.request.urlopen("http://127.0.0.1:18201/robots.txt", timeout=2).status == 200
    except Exception:
        return False


def up():
    os.makedirs(DIR, exist_ok=True)
    if healthy():
        print("fake sites already up"); return 0
    env = dict(os.environ, R3K_LOG=os.path.join(DIR, "req.log"))
    p = subprocess.Popen([sys.executable, os.path.join(HERE, "fake_sites.py")], env=env, start_new_session=True,
                         stdin=subprocess.DEVNULL, stdout=open(os.path.join(DIR, "sites.out"), "w"), stderr=subprocess.STDOUT)
    open(PID, "w").write(str(p.pid))
    for _ in range(40):
        if healthy():
            print("fake sites up", p.pid); return 0
        time.sleep(0.25)
    print("fake sites did not come up", file=sys.stderr); return 1


def down():
    try:
        os.kill(int(open(PID).read()), signal.SIGTERM)
    except Exception:
        pass
    subprocess.run(["pkill", "-f", "tests/fake_sites.py"], check=False)
    print("fake sites down"); return 0


ROOT = os.path.dirname(HERE)
FAST = ["-s", "DOWNLOAD_DELAY=0", "-s", "AUTOTHROTTLE_ENABLED=False", "-s", "CONCURRENT_REQUESTS_PER_DOMAIN=4"]


def scrapy(args, out, env=None):
    cmd = ["scrapy", "crawl"] + args + ["-O", os.path.join(DIR, out)] + FAST
    log = open(os.path.join(DIR, out + ".log"), "w")
    r = subprocess.run(cmd, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, env=dict(os.environ, **(env or {})))
    if "Spider error" in open(os.path.join(DIR, out + ".log")).read():
        print("spider error in", out, file=sys.stderr); return 1
    return r.returncode


def crawl():
    open(os.path.join(DIR, "req.log"), "w").close()
    rc = scrapy(["seeded", "-a", "seeds=tests/seeds_test.txt", "-a", "slice=0"], "items0.jsonl")
    rc |= scrapy(["seeded", "-a", "seeds=tests/seeds_test.txt", "-a", "slice=1"], "items1.jsonl")
    print("crawl rc", rc); return rc


def fallback():
    rc = scrapy(["seeded", "-a", "seeds=tests/seeds_test.txt", "-a", "slice=0"], "items0_fb.jsonl", {"R3_NO_TRAFILATURA": "1"})
    print("fallback crawl rc", rc); return rc


def scout():
    rc = scrapy(["scout", "-a", "candidates=tests/candidates_test.txt"], "scout.jsonl")
    rc |= scrapy(["scout", "-a", "hosts=http://127.0.0.1:18201/,http://127.0.0.1:18204/,http://127.0.0.1:18299/"], "scout_hosts.jsonl")
    print("scout rc", rc); return rc


def post():
    tools = os.path.join(ROOT, "tools")
    items_all = os.path.join(DIR, "items_all.jsonl")
    with open(items_all, "w") as f:
        for n in ("items0.jsonl", "items1.jsonl", "items0.jsonl"):
            f.write(open(os.path.join(DIR, n)).read())
    steps = [[sys.executable, os.path.join(tools, "to_index_spec.py"), items_all, "--out", os.path.join(DIR, "convert")],
             [sys.executable, os.path.join(tools, "outlink_graph.py"), items_all, "--out", os.path.join(DIR, "graph.csv"), "--min-sources", "2"],
             [sys.executable, os.path.join(tools, "scout_report.py"), os.path.join(DIR, "scout.jsonl")],
             [sys.executable, os.path.join(tools, "site_report.py"), items_all]]
    rc = 0
    for c in steps:
        rc |= subprocess.run(c, stdout=subprocess.DEVNULL).returncode
    print("post rc", rc); return rc


if __name__ == "__main__":
    sys.exit({"up": up, "down": down, "crawl": crawl, "fallback": fallback, "scout": scout, "post": post}[sys.argv[1]]())
