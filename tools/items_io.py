import csv, json, sys
csv.field_size_limit(10**9)

def read_items(path):
    """Zyte CSV export or local JSONL -> list of dicts; the string 'null' and '' become None."""
    rows = []
    if str(path).endswith(".jsonl"):
        rows = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]
    else:
        rows = list(csv.DictReader(open(path, encoding="utf-8-sig")))
    for r in rows:
        for k, v in list(r.items()):
            if v in ("null", "", "None"):
                r[k] = None
            elif isinstance(v, str) and k in ("status", "depth"):
                try: r[k] = int(v)
                except ValueError: pass
    return rows
