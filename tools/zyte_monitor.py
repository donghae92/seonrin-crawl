#!/usr/bin/env python3
"""zyte_monitor - what Zyte is doing right now, as gauges and a log. No model, no tokens: plain calls to the Zyte API every few seconds.

  zyte_monitor.py loop [N]    every N seconds (default 15) write status.json for monitor/index.html  (LaunchAgent, runs for ever)
  zyte_monitor.py once        write status.json once
  zyte_monitor.py watch [N]   the same in this terminal: topic, two gauges, the log (Ctrl-C to leave)

The page address stays the same. The TOPIC is read from the job that runs now: when a lesson with another topic starts, the page changes by itself.
Read-only: it never starts or stops anything and never prints a key. Output: ~/index-data/monitor/status.json (env ZY_MONITOR_OUT)."""
import argparse, json, os, sys, time, urllib.parse
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import zyte_ctl as zc
import zyte_curriculum as cu

OUT = os.path.expanduser(os.environ.get("ZY_MONITOR_OUT", "~/index-data/monitor/status.json"))
EVENTS = os.path.join(os.path.dirname(OUT), "events.jsonl")
iso = lambda t: t.strftime("%Y-%m-%dT%H:%M:%SZ")


def short(jid):
    return jid.split("/", 1)[1] if str(jid).count("/") == 2 else str(jid)


def topic_of(job):
    """Topic of the job on screen: the file the curriculum wrote when it started the job, else the lesson whose last job it was, else 'manual'."""
    if not job:
        return {"title": "지금은 일이 없음", "stage": None, "week": None, "lesson": None, "planned_pages": 0}
    t = cu.jload(os.path.join(cu.DIR, "current_topic.json"), {})
    if t.get("job") == job.get("id"):
        return t
    st, cur = cu.jload(cu.state_path(), {}), cu.cur_load()
    for lid, ls in (st.get("lessons") or {}).items():
        if ls.get("last_job") == job.get("id"):
            L = next((x for x in cur.get("lessons", []) if x.get("id") == lid), {})
            return {"title": L.get("title") or lid, "stage": L.get("stage"), "week": L.get("week"), "lesson": lid, "planned_pages": cu.planned_pages(L) if L else 0}
    return {"title": "수동 작업 · %s" % job.get("spider", "?"), "stage": None, "week": None, "lesson": None, "planned_pages": 0}


def zyte_warnings(job):
    q = {"format": "json", "count": 20, "startts": 0, "filter": '["level",">=",[30]]'}
    rows = zc.call("%s/logs/%s/%s?%s" % (zc.STORE, zc.PROJECT, short(job["id"]), urllib.parse.urlencode(q)))
    out = []
    for l in rows if isinstance(rows, list) else []:
        ms = l.get("time")
        t = iso(datetime.fromtimestamp(ms / 1000, timezone.utc)) if isinstance(ms, (int, float)) else ""
        out.append({"t": t, "src": "zyte", "msg": str(l.get("message"))[:220]})
    return out[::-1]


def add_events(prev, now_snap):
    ev, t = [], now_snap["at"]
    pj, nj = (prev or {}).get("job") or {}, now_snap.get("job") or {}
    pt, nt = ((prev or {}).get("topic") or {}).get("title"), now_snap["topic"].get("title")
    if nj.get("id") and nj.get("id") != pj.get("id"):
        ev.append("작업 %s 표시 — %s (%s)" % (short(nj["id"]), nt, nj.get("state")))
    elif nj.get("id") and nj.get("state") != pj.get("state") and nj.get("state") == "finished":
        ev.append("작업 %s 끝 — %s · 쪽 %s · 항목 %s · 오류 %s" % (short(nj["id"]), nj.get("reason") or "finished", nj.get("pages"), nj.get("items"), nj.get("errors")))
    if pt and nt and pt != nt:
        ev.append("주제 바뀜: %s → %s" % (pt, nt))
    if not nj.get("id") and pj.get("id"):
        ev.append("Zyte가 쉬는 중")
    if ev:
        os.makedirs(os.path.dirname(EVENTS), exist_ok=True)
        with open(EVENTS, "a", encoding="utf-8") as f:
            for e in ev:
                f.write(json.dumps({"t": t, "src": "monitor", "msg": e}, ensure_ascii=False) + "\n")
    return ev


def last_events(n=30):
    try:
        lines = open(EVENTS, encoding="utf-8").read().splitlines()[-200:]
    except OSError:
        return []
    return [json.loads(l) for l in lines[-n:] if l.strip()]


def snapshot(prev):
    now = datetime.now(timezone.utc)
    try:
        running = zc.jobs("running", 5)
        pending = zc.jobs("pending", 20)
        job = running[0] if running else (zc.jobs("finished", 1) or [None])[0]
    except SystemExit as e:
        raise RuntimeError(str(e))
    topic = topic_of(job)
    pages = int((job or {}).get("responses_received") or 0)
    planned = int(topic.get("planned_pages") or 0)
    is_run = bool(job) and job.get("state") == "running"
    f1 = 1.0 if (job and not is_run) else (min(1.0, pages / planned) if planned else 0.0)
    cur = cu.cur_load(); st = cu.jload(cu.state_path(), {}); cd = st.get("curr_day") or {}
    today = now.strftime("%Y-%m-%d"); n = cd.get("n", 0) if cd.get("date") == today else 0; mx = int(cur.get("max_jobs_per_day", 4))
    snap = {"at": iso(now), "topic": topic, "pending": len(pending), "curriculum": "on" if cu.enabled() else "off",
            "job": ({"id": job["id"], "spider": job.get("spider"), "state": job.get("state"), "started": job.get("started_time"), "items": job.get("items_scraped", 0),
                     "pages": pages, "errors": job.get("errors_count", 0), "reason": job.get("close_reason")} if job else None),
            "gauges": [{"k": "job", "label": "이 작업의 진행", "v": round(f1, 3), "text": ("%s / %s 쪽" % (pages, planned) if planned else "%s 쪽" % pages)},
                       {"k": "day", "label": "오늘 시작한 수업", "v": round(min(1.0, n / mx), 3) if mx else 0.0, "text": "%d / %d" % (n, mx)}]}
    add_events(prev, snap)
    log = last_events(30)
    if job:
        try:
            log += zyte_warnings(job)
        except Exception as e:
            log.append({"t": snap["at"], "src": "monitor", "msg": "Zyte 로그를 못 읽음: %s" % type(e).__name__})
    snap["log"] = sorted(log, key=lambda x: x.get("t", ""), reverse=True)[:40]
    return snap


def write(snap):
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT + ".tmp", "w", encoding="utf-8") as f:
        json.dump(snap, f, ensure_ascii=False, indent=1)
    os.replace(OUT + ".tmp", OUT)


def tick():
    prev = cu.jload(OUT, None)
    try:
        snap = snapshot(prev)
    except Exception as e:                                    # a bad moment must not stop the monitor: say so on the page and go on
        snap = {"at": iso(datetime.now(timezone.utc)), "error": "%s: %s" % (type(e).__name__, str(e)[:160]), "topic": (prev or {}).get("topic") or {"title": "읽는 중 오류"},
                "job": (prev or {}).get("job"), "gauges": (prev or {}).get("gauges") or [], "log": (prev or {}).get("log") or [], "pending": 0, "curriculum": "?"}
    write(snap)
    return snap


def bar(v, w=30):
    k = int(round(max(0.0, min(1.0, v)) * w))
    return "█" * k + "░" * (w - k)


def show(snap):
    print("\033[2J\033[H", end="")
    t = snap.get("topic") or {}
    print("맥북모니터링 · %s" % snap.get("at"))
    print("주제  %s%s" % (t.get("title"), "  [%s%s]" % (t.get("stage") or "", " " + t["week"] if t.get("week") else "") if t.get("stage") else ""))
    j = snap.get("job") or {}
    print("작업  %s %s · 항목 %s · 오류 %s · 대기 %s · 수업표 %s" % (j.get("id", "-"), j.get("state", "-"), j.get("items", 0), j.get("errors", 0), snap.get("pending"), snap.get("curriculum")))
    if snap.get("error"):
        print("오류  %s" % snap["error"])
    for g in snap.get("gauges", []):
        print("%-12s %s %5.1f%%  %s" % (g["label"], bar(g["v"]), 100 * g["v"], g["text"]))
    print()
    for l in (snap.get("log") or [])[:18]:
        print("%s  %s" % ((l.get("t") or "")[11:19], l.get("msg")))


def main():
    ap = argparse.ArgumentParser(prog="zyte_monitor"); sub = ap.add_subparsers(dest="cmd", required=True)
    for n in ("loop", "watch"):
        x = sub.add_parser(n); x.add_argument("secs", nargs="?", type=int, default=15)
    sub.add_parser("once")
    a = ap.parse_args()
    if a.cmd == "once":
        tick(); print("wrote %s" % OUT); return 0
    try:
        while True:
            s = tick()
            if a.cmd == "watch":
                show(s)
            time.sleep(max(5, a.secs))
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
