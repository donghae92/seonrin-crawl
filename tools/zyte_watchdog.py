#!/usr/bin/env python3
"""zyte_watchdog - keeps Zyte working round the clock. No model, no tokens: plain calls to the Zyte API once a minute.

  zyte_watchdog.py loop [N]   every N seconds (default 60): look, and act when nothing moved   (LaunchAgent, KeepAlive)
  zyte_watchdog.py once       one look
  zyte_watchdog.py show       the state in words

The rule (owner, 2026-10-21):
  the cumulative count (pages + items over all jobs) did not change for 30 minutes  ->  "continue"
  the 3rd continue in a row without any change                                      ->  "restart" from the latest waypoint
  waypoint = the Zyte point (job, lesson, slice, counts) where change was seen again after a continue; the newest is the restart point.

continue : starts any LaunchAgent that is missing, fires the curriculum tick at once when a lesson is due, writes the job's last warnings into the log.
restart  : stops the stalled curriculum job (tag zy-curr only, never a manual one) and starts the waypoint's lesson again with the same slice.
           The spider has no per-page resume, so "from the waypoint" means the same lesson and the same window again.
hooks    : an executable file ~/.config/zy/hooks/continue or ~/.config/zy/hooks/restart is run first, with WD_JOB WD_LESSON WD_STALL_MIN WD_COUNT in its environment.

Healthy waiting is not a stall: curriculum off, or nothing due, or a job still counting, resets the clock.
An API failure is not a stall either: that round is skipped.  At most WD_MAX_RESTARTS restarts a day (default 4); after that it only writes a note.
Never starts the curriculum switch (owner's), never prints a key.  Files: ~/.config/zy/watchdog_state.json, ~/index-data/monitor/watchdog.json and watchdog.jsonl.
"""
import json, os, subprocess, sys, time, urllib.parse
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import zyte_ctl as zc
import zyte_curriculum as cu

STALL_MIN = float(os.environ.get("WD_STALL_MIN", "30"))
MAX_RESTARTS = int(os.environ.get("WD_MAX_RESTARTS", "4"))
OUT_DIR = os.path.expanduser(os.environ.get("ZY_WATCHDOG_DIR", "~/index-data/monitor"))
STATE = os.path.join(cu.DIR, "watchdog_state.json")
SUMMARY = os.path.join(OUT_DIR, "watchdog.json")
EVENTS = os.path.join(OUT_DIR, "watchdog.jsonl")
AGENTS = {"com.seonrin.zyte-curriculum": False, "com.seonrin.zyte-monitor": True, "com.seonrin.zyte-monitor-web": True}  # label: needs a live process
iso = lambda t: t.strftime("%Y-%m-%dT%H:%M:%SZ")


def parse(s):
    t = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def event(kind, msg, **kw):
    os.makedirs(OUT_DIR, exist_ok=True)
    rec = {"t": iso(datetime.now(timezone.utc)), "kind": kind, "msg": msg, **kw}
    with open(EVENTS, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print("%s %s %s" % (rec["t"], kind, msg), flush=True)


def recent_events(n=20):
    try:
        lines = open(EVENTS, encoding="utf-8").read().splitlines()[-n:]
        return [json.loads(l) for l in lines]
    except (OSError, ValueError):
        return []


def count(j):
    return int(j.get("responses_received") or 0) + int(j.get("items_scraped") or 0)


def update_count(state, jobs):
    """Adds what every job gained since the last look to the cumulative count. True when anything moved."""
    seen, moved, first = state.setdefault("seen", {}), False, not state.get("baseline")
    for j in jobs:
        c, prev = count(j), seen.get(j["id"])
        if prev is None:
            seen[j["id"]] = c
            if not first and c > 0:                      # a job that was not there before: that is a change
                state["cum"] = state.get("cum", 0) + c; moved = True
            elif not first:
                moved = True
        elif c > prev:
            state["cum"] = state.get("cum", 0) + (c - prev); seen[j["id"]] = c; moved = True
    state["baseline"] = True
    while len(seen) > 200:
        seen.pop(next(iter(seen)))
    return moved


def mode(run, pend, now):
    if not cu.enabled():
        return "off"
    if run or pend:
        return "running"
    cur, st = cu.cur_load(), cu.jload(cu.state_path(), {})
    cd = st.get("curr_day") or {}
    if (cd.get("n", 0) if cd.get("date") == now.strftime("%Y-%m-%d") else 0) >= int(cur.get("max_jobs_per_day", 4)):
        return "idle_none"                                # the day's limit is a healthy wait, not a stall
    return "idle_due" if cu.pick(cur, st, now) else "idle_none"


def make_waypoint(state, jobs, now):
    j = jobs[0] if jobs else None
    topic = cu.jload(os.path.join(cu.DIR, "current_topic.json"), {})
    lid = topic.get("lesson")
    runs = (((cu.jload(cu.state_path(), {}).get("lessons") or {}).get(lid) or {}).get("runs", 0)) if lid else 0
    wp = {"at": iso(now), "job": j and j["id"], "lesson": lid, "slice": ((runs - 1) % 100) if runs else None,
          "pages": int((j or {}).get("responses_received") or 0), "items": int((j or {}).get("items_scraped") or 0)}
    state.setdefault("waypoints", []).append(wp)
    state["waypoints"] = state["waypoints"][-20:]
    event("waypoint", "change seen again after a continue: %s lesson=%s pages=%s" % (wp["job"], lid, wp["pages"]), waypoint=wp)


def kick_agents():
    uid, out = os.getuid(), []

    def sh(*cmd):
        try:
            return subprocess.run(list(cmd), capture_output=True, text=True, timeout=20)
        except Exception as e:                            # no launchctl, or it hangs: say so and go on
            out.append("%s failed: %s" % (cmd[1], type(e).__name__))

    for label, live in AGENTS.items():
        r = sh("launchctl", "list", label)
        if r is None:
            continue
        if r.returncode != 0:
            plist = os.path.expanduser("~/Library/LaunchAgents/%s.plist" % label)
            if os.path.exists(plist):
                sh("launchctl", "bootstrap", "gui/%d" % uid, plist)
                out.append("%s was not loaded, loaded again" % label)
            else:
                out.append("%s is not loaded and has no plist" % label)
        elif live and '"PID"' not in r.stdout:
            sh("launchctl", "kickstart", "gui/%d/%s" % (uid, label))
            out.append("%s had no process, started" % label)
    return out


def run_hook(name, ctx):
    p = os.path.join(cu.DIR, "hooks", name)
    if os.path.isfile(p) and os.access(p, os.X_OK):
        env = dict(os.environ, **{"WD_" + k.upper(): str(v) for k, v in ctx.items()})
        try:
            r = subprocess.run([p], env=env, timeout=120, capture_output=True, text=True)
            return "hook %s exit %s" % (name, r.returncode)
        except Exception as e:
            return "hook %s failed: %s" % (name, type(e).__name__)
    return ""


def last_warnings(job):
    num = str(job["id"]).split("/", 1)[1] if str(job["id"]).count("/") == 2 else str(job["id"])
    q = {"format": "json", "count": 3, "startts": 0, "filter": '["level",">=",[30]]'}
    try:
        return [str(l.get("message"))[:160] for l in zc.call("%s/logs/%s/%s?%s" % (zc.STORE, zc.PROJECT, num, urllib.parse.urlencode(q)))]
    except Exception as e:
        return ["could not read the job log: %s" % type(e).__name__]


def do_continue(state, md, run, now, ctx):
    notes = [x for x in [run_hook("continue", ctx)] if x] + kick_agents()
    if md == "idle_due":
        started, why = cu.fill(now)
        notes.append("tick: started %s %s" % started if started else "tick: nothing started (%s)" % why)
    elif run:
        notes.append("last warnings: %s" % (" | ".join(last_warnings(run[0])) or "none"))
    event("continue", "no change for %d min (%s), continue number %d" % (ctx["stall_min"], md, ctx["count"]), notes=notes)


def do_restart(state, run, pend, now, ctx):
    day = now.strftime("%Y-%m-%d"); rs = state.get("restarts") or {}
    n = rs.get("n", 0) if rs.get("date") == day else 0
    if n >= MAX_RESTARTS:
        event("note", "restart wanted but %d restarts were already made today; only a note" % n)
        return
    notes, stopped = [x for x in [run_hook("restart", ctx)] if x], False
    for j in run + pend:
        if "zy-curr" in (j.get("tags") or []):
            try:
                zc.call("%s/jobs/stop.json" % zc.API, {"project": zc.PROJECT, "job": j["id"]})
                notes.append("stopped %s" % j["id"]); stopped = True
            except Exception as e:
                notes.append("could not stop %s: %s" % (j["id"], type(e).__name__))
        else:
            notes.append("left %s alone (not a curriculum job)" % j["id"])
    wp = (state.get("waypoints") or [None])[-1]
    lid = (wp or {}).get("lesson") or cu.jload(os.path.join(cu.DIR, "current_topic.json"), {}).get("lesson")
    cur, st = cu.cur_load(), cu.jload(cu.state_path(), {})
    L = {x["id"]: x for x in cur.get("lessons", [])}.get(lid)
    if (run or pend) and not stopped:
        notes.append("no curriculum job could be stopped; not starting a second one")
    elif L:
        try:
            ls = cu.lesson_state(st, lid)
            if (wp or {}).get("slice") is not None:
                ls["runs"] = int(wp["slice"])          # same slice again: launch adds one and uses runs % 100
            jid = cu.launch(L, st, now)
            cu.jsave(cu.state_path(), st)
            notes.append("started %s again as %s from waypoint %s" % (lid, jid, (wp or {}).get("at", "none (job start)")))
        except Exception as e:
            notes.append("could not start %s again: %s" % (lid, str(e)[:120]))
    else:
        notes.append("no lesson known for the restart point; the curriculum tick will pick the next one")
    state["restarts"] = {"date": day, "n": n + 1}
    event("restart", "continue did not help three times; restart from the latest waypoint", notes=notes)


def cycle(now=None):
    now = now or datetime.now(timezone.utc)
    state = cu.jload(STATE, {})
    try:
        run, pend, fin = zc.jobs("running", 5), zc.jobs("pending", 20), zc.jobs("finished", 5)
    except (SystemExit, Exception) as e:                  # an API failure is not a stall: skip this round
        if not state.get("last_err") or (now - parse(state["last_err"])).total_seconds() > 600:
            event("error", "could not read Zyte: %s %s" % (type(e).__name__, str(e)[:120]))
            state["last_err"] = iso(now); cu.jsave(STATE, state)
        return state
    gap = (now - parse(state["at"])).total_seconds() / 60 if state.get("at") else 0
    moved = update_count(state, run + pend + fin)
    md = mode(run, pend, now)
    if gap > 10 or not state.get("last_change"):          # the watchdog was away (or is new): the clock starts now
        state["last_change"] = iso(now)
        if gap > 10:
            event("note", "watchdog was away for %d min; the clock starts now" % gap)
    if md in ("off", "idle_none") or moved:
        state["last_change"] = iso(now)
        if moved and state.get("pending_waypoint"):
            make_waypoint(state, (run or fin), now); state["pending_waypoint"] = False
        if state.get("stall"):
            event("note", "moving again; the continue counter goes back to 0")
        state["stall"] = 0
    else:
        idle = (now - parse(state["last_change"])).total_seconds() / 60
        since_act = (now - parse(state["last_action"])).total_seconds() / 60 if state.get("last_action") else 1e9
        if idle >= STALL_MIN and since_act >= STALL_MIN:
            n = state.get("stall", 0) + 1
            ctx = {"count": n, "stall_min": int(idle), "job": (run or [{}])[0].get("id", ""), "lesson": cu.jload(os.path.join(cu.DIR, "current_topic.json"), {}).get("lesson", "")}
            try:
                if n < 3:
                    state["stall"] = n; state["pending_waypoint"] = True      # counted even if the action below fails
                    do_continue(state, md, run, now, ctx)
                else:
                    do_restart(state, run, pend, now, ctx); state["stall"] = 0; state["pending_waypoint"] = False
                    state["last_change"] = iso(now)
            except Exception as e:
                event("error", "action failed: %s %s" % (type(e).__name__, str(e)[:120]))
            state["last_action"] = iso(now)
    state["at"] = iso(now); state["mode"] = md
    cu.jsave(STATE, state)
    wp = (state.get("waypoints") or [None])[-1]
    cu.jsave(SUMMARY, {"at": state["at"], "mode": md, "stall": state.get("stall", 0), "last_change": state["last_change"], "cumulative": state.get("cum", 0),
                       "latest_waypoint": wp, "restarts_today": (state.get("restarts") or {}).get("n", 0), "events": recent_events()})
    return state


def show():
    s = cu.jload(STATE, {})
    if not s:
        print("no state yet"); return
    print("at %s mode %s stall %s/3 cumulative %s last change %s" % (s.get("at"), s.get("mode"), s.get("stall", 0), s.get("cum", 0), s.get("last_change")))
    print("latest waypoint: %s" % ((s.get("waypoints") or [None])[-1],))
    for e in recent_events(8):
        print(e["t"], e["kind"], e["msg"])


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "once"
    if cmd == "show":
        show()
    elif cmd == "once":
        cycle()
    elif cmd == "loop":
        every = int(sys.argv[2]) if len(sys.argv) > 2 else 60
        while True:
            try:
                cycle()
            except Exception as e:                        # a bad moment must not stop the watchdog
                event("error", "round failed: %s %s" % (type(e).__name__, str(e)[:120]))
            time.sleep(every)
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
