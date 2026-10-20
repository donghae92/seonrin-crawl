#!/usr/bin/env python3
"""zyte_curriculum - what Zyte studies next when it has nothing to do (stdlib only; uses tools/zyte_ctl.py for the Zyte API, the key and the landing door).

Zyte here has ONE unit (one job at a time) and no Periodic Jobs, so something outside must start the next job. This is that something.
The curriculum is a file kept in Drive `Dev/zyte색인/지침/` (curriculum_v3.json, machine form of 색인_커리큘럼_v3.1.md). Point this tool at it once:
the first line of ~/.config/zy/curriculum_path (or env ZY_CURRICULUM) is the path of that file.

  zyte_curriculum.py plan                 source, the switch, one word per lesson, the next lesson
  zyte_curriculum.py plan on|off          the switch of the idle filler (kept in ~/.config/zy/curriculum_switch.json, never in the curriculum file)
  zyte_curriculum.py plan next            show what would start, send nothing
  zyte_curriculum.py plan run [LESSON]    start a lesson now (the due one if none is named)
  zyte_curriculum.py plan reset LESSON    forget how often a lesson has run
  zyte_curriculum.py plan hosts           places named by lessons that nobody approved yet, one per line
  zyte_curriculum.py approve HOST...      approve places (after robots.txt and terms were read); kept in ~/.config/zy/approved_hosts.txt
  zyte_curriculum.py tick [--why]         run every minute (LaunchAgent): Zyte idle -> start the next due lesson; --why says why not

A lesson word: due | wait Nd | later MM-DD (its week has not begun) | approve (a place is not approved) | blocked (needs another lesson first) | done.
Order: lesson rank = priority + 100 x (whole weeks since its week began); so the running week comes first (layer 2, layer 3, tools), older weeks follow,
background lessons (high priority numbers) last. Each pass moves every site's rotating sitemap window one slice on (slice = passes so far).
Nothing starts unless the switch is on, nothing runs or waits in Zyte, Zyte has been idle for min_idle_minutes, fewer than max_jobs_per_day lessons
started today, and the landing door is configured (a job without it keeps its data only 7 days in Zyte)."""
import argparse, json, os, re, sys
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import zyte_ctl as zc

if os.environ.get("ZY_APP_BASE"):                       # test hook: point the Zyte helpers at a fake server
    zc.API = os.environ["ZY_APP_BASE"]
DIR = os.path.expanduser(os.environ.get("ZY_DIR", "~/.config/zy"))
SEEDLINE = re.compile(r"^https://[^\s|,]+( (cap=\d{1,4}|mode=(auto|recent|rotate|links)))*$")
ARGS = {"seeded": {"seedlines": lambda v: len(v) <= 1800 and 1 <= len(v.split("|")) <= 10 and all(SEEDLINE.match(x) for x in v.split("|")),
                   "lesson": lambda v: re.fullmatch(r"[a-z0-9-]{1,40}", v) is not None,
                   "slice": lambda v: re.fullmatch(r"\d{1,2}", v) is not None},
        "scout": {"hosts": lambda v: re.fullmatch(r"https://[^,\s]+(,https://[^,\s]+){0,9}", v) is not None}}


class Stop(Exception):
    pass


def jload(p, d):
    try:
        return json.load(open(p, encoding="utf-8"))
    except (OSError, ValueError):
        return d


def jsave(p, o):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    json.dump(o, open(p + ".tmp", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    os.replace(p + ".tmp", p)


def read_line(p):
    try:
        return open(p, encoding="utf-8").readline().strip()
    except OSError:
        return ""


def state_path():
    return os.path.join(DIR, "curriculum_state.json")


def switch_path():
    return os.path.join(DIR, "curriculum_switch.json")


def enabled():
    return jload(switch_path(), {}).get("enabled") is True


def cur_file():
    p = os.path.expanduser(os.environ.get("ZY_CURRICULUM") or read_line(os.path.join(DIR, "curriculum_path")) or "")
    return p if p and os.path.exists(p) else ""


def cur_load():
    p = cur_file()
    return jload(p, {"lessons": []}) if p else {"lessons": []}


def approved(cur):
    out = set(cur.get("approved_hosts") or [])
    try:
        for l in open(os.path.join(DIR, "approved_hosts.txt"), encoding="utf-8"):
            l = l.split("#")[0].strip()
            if l:
                out.add(l)
    except OSError:
        pass
    return out


def lesson_hosts(L):
    if L.get("spider", "seeded") == "scout":
        return []                                        # scouting is how a place gets looked at; it needs no approval
    return [urlparse(x.split()[0]).netloc for x in (L.get("seeds") or [])]


def planned_pages(L):
    if L.get("spider", "seeded") == "scout":
        return 3 * len(L.get("hosts") or [])
    return sum(int(m.group(1)) for x in (L.get("seeds") or []) for m in [re.search(r"\bcap=(\d+)", x)] if m)


def check(spider, args):
    if spider not in ARGS:
        raise Stop("spider %r is not part of a curriculum (seeded or scout)" % spider)
    for k, v in args.items():
        if k not in ARGS[spider]:
            raise Stop("argument %r does not belong to spider %s" % (k, spider))
        if not ARGS[spider][k](str(v)):
            raise Stop("argument %s=%s is outside its rule" % (k, str(v)[:60]))
    return {k: str(v) for k, v in args.items()}


def lesson_args(L, runs):
    if L.get("spider", "seeded") == "scout":
        return {"hosts": ",".join(L.get("hosts") or [])}
    return {"seedlines": "|".join(L.get("seeds") or []), "lesson": L.get("id", ""), "slice": str(runs % 100)}


def problems(cur):
    out, ids = [], set()
    if not cur.get("lessons"):
        return ["no curriculum file found: put the path of curriculum_v3.json on the first line of %s" % os.path.join(DIR, "curriculum_path")]
    for L in cur.get("lessons", []):
        i = L.get("id", "?")
        if not re.fullmatch(r"[a-z0-9-]{1,40}", str(i)) or i in ids:
            out.append("lesson id %r is missing, malformed or repeated" % i)
        ids.add(i)
        if not isinstance(L.get("priority"), int) or not isinstance(L.get("revisit_days"), int) or L.get("revisit_days", 0) < 1:
            out.append("%s: priority and revisit_days must be whole numbers (revisit_days >= 1)" % i)
        if L.get("passes") is not None and (not isinstance(L["passes"], int) or L["passes"] < 1):
            out.append("%s: passes must be null or a whole number >= 1" % i)
        if L.get("week") and L["week"] not in (cur.get("weeks") or {}):
            out.append("%s: week %r is not in weeks" % (i, L["week"]))
        try:
            check(L.get("spider", "seeded"), lesson_args(L, 0))
        except Stop as e:
            out.append("%s: %s" % (i, e))
    for L in cur.get("lessons", []):
        for a in L.get("after") or []:
            if a not in ids:
                out.append("%s: after %r is not a lesson" % (L.get("id"), a))
    return out


def lesson_state(st, lid):
    return st.setdefault("lessons", {}).setdefault(lid, {"runs": 0, "last_run": None, "last_job": None})


def week_begin(cur, L):
    w = (cur.get("weeks") or {}).get(L.get("week") or "")
    return datetime.strptime(w[0], "%Y-%m-%d").replace(tzinfo=timezone.utc) if w else None


def rank(cur, L, now):
    b = week_begin(cur, L)
    return L["priority"] + (100 * max(0, (now - b).days // 7) if b else 0)


def status(cur, st, L, now):
    """one word for one lesson: done | blocked | later MM-DD | approve | wait Nd | due"""
    ls = (st.get("lessons") or {}).get(L["id"], {})
    if L.get("passes") is not None and ls.get("runs", 0) >= L["passes"]:
        return "done"
    if any(((st.get("lessons") or {}).get(a) or {}).get("runs", 0) < 1 for a in (L.get("after") or [])):
        return "blocked"
    b = week_begin(cur, L)
    if b and now < b:
        return "later %s" % b.strftime("%m-%d")
    if any(h not in approved(cur) for h in lesson_hosts(L)):
        return "approve"
    if ls.get("last_run"):
        left = datetime.fromisoformat(ls["last_run"].replace("Z", "+00:00")) + timedelta(days=L["revisit_days"]) - now
        if left > timedelta(0):
            return "wait %dd" % (-(-left.total_seconds() // 86400))
    return "due"


def pick(cur, st, now):
    due = [L for L in cur.get("lessons", []) if status(cur, st, L, now) == "due"]
    due.sort(key=lambda L: (rank(cur, L, now), ((st.get("lessons") or {}).get(L["id"]) or {}).get("last_run") or "", L["id"]))
    return due[0] if due else None


def land_settings(no_land):
    if no_land:
        return {}
    url, tok = zc.cfg("land_url", "LAND_URL"), zc.cfg("land_write", "LAND_WRITE")
    if not (url and tok):
        raise Stop("the landing door is not configured (~/.config/zy/land_url and land_write, or env LAND_URL and LAND_WRITE); --no-land runs without it")
    return {"LAND_URL": url, "LAND_TOKEN": tok, "LAND_BATCH_ITEMS": 500}


def launch(L, st, now, dry=False, no_land=False):
    runs = ((st.get("lessons") or {}).get(L["id"]) or {}).get("runs", 0)
    spider = L.get("spider", "seeded"); args = check(spider, lesson_args(L, runs)); js = land_settings(no_land)
    if dry:
        print("spider %s" % spider)
        for k, v in args.items(): print("arg %s=%s" % (k, v))
        for k, v in js.items(): print("setting %s=%s" % (k, "***" if k == "LAND_TOKEN" else v))
        return None
    form = {"project": zc.PROJECT, "spider": spider, "add_tag": "zy-curr", **args}
    if js:
        form["job_settings"] = json.dumps(js)
    try:
        r = zc.call("%s/run.json" % zc.API, form)
    except SystemExit:
        raise
    except Exception as e:
        raise Stop("run.json failed: %s" % type(e).__name__)
    if not isinstance(r, dict) or r.get("status") != "ok":
        raise Stop("run.json answered %s" % str(r)[:120])
    ls = lesson_state(st, L["id"]); ls["runs"] += 1; ls["last_run"] = now.strftime("%Y-%m-%dT%H:%M:%SZ"); ls["last_job"] = r["jobid"]
    jsave(os.path.join(DIR, "current_topic.json"), {"job": r["jobid"], "lesson": L["id"], "title": L.get("title") or L["id"], "stage": L.get("stage"),
                                                     "layer": L.get("layer"), "week": L.get("week"), "planned_pages": planned_pages(L), "at": ls["last_run"]})
    return r["jobid"]


def fill(now):
    """(started, why): started is (lesson id, job id) or None; why is one phrase when nothing started."""
    if not enabled():
        return None, "curriculum is off"
    cur = cur_load()
    probs = problems(cur)
    if probs:
        return None, "curriculum problem: %s" % probs[0]
    for s in ("running", "pending"):
        if zc.jobs(s, 1):
            return None, "zyte has a %s job" % s
    fin = zc.jobs("finished", 1)
    t = (fin[0] if fin else {}).get("updated_time")
    if t:
        t = datetime.fromisoformat(str(t).replace("Z", "+00:00")); t = t if t.tzinfo else t.replace(tzinfo=timezone.utc)
        if now - t < timedelta(minutes=float(cur.get("min_idle_minutes", 20))):
            return None, "zyte finished a job less than %s minutes ago" % cur.get("min_idle_minutes", 20)
    st = jload(state_path(), {}); day = now.strftime("%Y-%m-%d"); cd = st.get("curr_day") or {}
    n = cd.get("n", 0) if cd.get("date") == day else 0
    if n >= int(cur.get("max_jobs_per_day", 4)):
        return None, "%d lessons already started today" % n
    L = pick(cur, st, now)
    if not L:
        return None, "no lesson is due"
    jid = launch(L, st, now)
    st["curr_day"] = {"date": day, "n": n + 1}; jsave(state_path(), st)
    return (L["id"], jid), ""


def main(argv=None):
    ap = argparse.ArgumentParser(prog="zyte_curriculum"); sub = ap.add_subparsers(dest="cmd", required=True)
    pl = sub.add_parser("plan"); pl.add_argument("action", nargs="?", default="show", choices=["show", "on", "off", "next", "run", "reset", "hosts"])
    pl.add_argument("lesson", nargs="?"); pl.add_argument("--dry", action="store_true"); pl.add_argument("--no-land", action="store_true")
    ap_ = sub.add_parser("approve"); ap_.add_argument("hosts", nargs="+")
    tk = sub.add_parser("tick"); tk.add_argument("--why", action="store_true")
    a = ap.parse_args(argv)
    try:
        now = datetime.now(timezone.utc)
        if a.cmd == "tick":
            started, why = fill(now)
            if started: print("fired curriculum %s %s" % started)
            elif a.why: print("nothing started: %s" % why)
            return 0
        if a.cmd == "approve":
            for h in a.hosts:
                if not re.fullmatch(r"[a-z0-9.-]{3,80}", h):
                    raise Stop("%r does not look like a host name (no https://, no path)" % h)
            have = approved(cur_load())
            os.makedirs(DIR, exist_ok=True)
            with open(os.path.join(DIR, "approved_hosts.txt"), "a", encoding="utf-8") as f:
                for h in a.hosts:
                    if h not in have:
                        f.write(h + "\n")
                    print("approved %s" % h)
            return 0
        cur = cur_load(); st = jload(state_path(), {}); byid = {L["id"]: L for L in cur.get("lessons", [])}
        if a.action in ("on", "off"):
            jsave(switch_path(), {"enabled": a.action == "on"})
        for pr in problems(cur):
            print("problem %s" % pr)
        if a.action in ("show", "on", "off"):
            print("source %s" % (cur_file() or "none"))
            print("curriculum %s" % ("on" if enabled() else "off"))
            for L in sorted(cur.get("lessons", []), key=lambda L: (rank(cur, L, now), L["id"])):
                print("%s %s" % (L["id"], status(cur, st, L, now)))
            nx = pick(cur, st, now); print("next %s" % (nx["id"] if nx else "none"))
        elif a.action == "hosts":
            seen, ok = [], approved(cur)
            for L in cur.get("lessons", []):
                for h in lesson_hosts(L):
                    if h not in ok and h not in seen:
                        seen.append(h); print(h)
        elif a.action == "next":
            L = pick(cur, st, now)
            if not L: print("next none")
            else:
                print("next %s" % L["id"]); launch(L, st, now, dry=True, no_land=a.no_land)
        elif a.action == "run":
            L = byid.get(a.lesson) if a.lesson else pick(cur, st, now)
            if a.lesson and not L: raise Stop("no lesson %r" % a.lesson)
            if not L: raise Stop("no lesson is due")
            if problems(cur): raise Stop("the curriculum has a problem; see `plan`")
            w = status(cur, st, L, now)
            if w == "approve": raise Stop("lesson %s names a place nobody approved (see `plan hosts`)" % L["id"])
            jid = launch(L, st, now, dry=a.dry, no_land=a.no_land)
            if jid: jsave(state_path(), st); print("started %s %s" % (L["id"], jid))
        elif a.action == "reset":
            if a.lesson not in byid: raise Stop("no lesson %r" % a.lesson)
            (st.get("lessons") or {}).pop(a.lesson, None); jsave(state_path(), st); print("reset %s" % a.lesson)
    except Stop as e:
        print("zyte_curriculum: %s" % e, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
