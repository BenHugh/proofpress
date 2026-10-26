"""Keyword backlog: backlog.csv in the project root.

Format (header row required, UTF-8):

    keyword,cluster,priority,intent_hint,status,slug,published_at,notes

keyword       the exact search phrase (required, unique)
cluster       topic group; rows in one cluster are secondaries for ONE article
priority      1 (highest) .. 3
intent_hint   buying guide | comparison | how-to | definition | troubleshooting | list | list (download)
status        todo | drafting | approved | published | blocked | skip
slug          filled by the pipeline
published_at  filled by the pipeline (YYYY-MM-DD)
notes         free text: secondaries, angle, warnings for the writer
"""
import csv
import datetime as dt
import io

from .project import require_project, slugify

COLUMNS = ["keyword", "cluster", "priority", "intent_hint", "status", "slug", "published_at", "notes"]
STATUSES = ["todo", "drafting", "approved", "published", "blocked", "skip"]
INTENTS = ["buying guide", "comparison", "how-to", "definition", "troubleshooting", "list", "list (download)"]


class BacklogError(Exception):
    pass


def _path(project):
    return require_project(project) / "backlog.csv"


def _norm(row, n):
    out = {c: (row.get(c) or "").strip() for c in COLUMNS}
    if not out["keyword"]:
        return None
    out["status"] = (out["status"] or "todo").lower()
    if out["status"] not in STATUSES:
        raise BacklogError(f"backlog row {n}: status '{out['status']}' must be one of {', '.join(STATUSES)}")
    p = out["priority"] or "2"
    if p not in ("1", "2", "3"):
        raise BacklogError(f"backlog row {n}: priority '{p}' must be 1, 2 or 3")
    out["priority"] = p
    return out


def parse_text(text):
    text = text.lstrip("﻿")
    if not text.strip():
        return []
    reader = csv.DictReader(io.StringIO(text))
    fields = [f.strip().lower() for f in (reader.fieldnames or [])]
    if "keyword" not in fields:
        raise BacklogError("backlog CSV needs a header row that includes 'keyword' (see the format hint)")
    reader.fieldnames = fields
    rows = []
    for n, raw in enumerate(reader, 2):
        r = _norm(raw, n)
        if r:
            rows.append(r)
    return rows


def read(project):
    p = _path(project)
    if not p.exists():
        return []
    return parse_text(p.read_text(encoding="utf-8"))


def to_text(rows):
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=COLUMNS, lineterminator="\n")
    w.writeheader()
    for r in rows:
        w.writerow({c: r.get(c, "") for c in COLUMNS})
    return buf.getvalue()


def write(project, rows):
    clean = []
    for n, r in enumerate(rows, 2):
        x = _norm(r, n)
        if x:
            clean.append(x)
    _path(project).write_text(to_text(clean), encoding="utf-8")
    return clean


def check(rows):
    msgs, seen = [], {}
    for r in rows:
        k = r["keyword"].lower()
        if k in seen:
            msgs.append(f"duplicate keyword in backlog: '{r['keyword']}'")
        seen[k] = 1
        if r["intent_hint"] and r["intent_hint"] not in INTENTS:
            msgs.append(f"unknown intent_hint '{r['intent_hint']}' for '{r['keyword']}' (allowed: {', '.join(INTENTS)})")
    return msgs


def next_todo(project):
    rows = read(project)
    todo = [(int(r["priority"]), i, r) for i, r in enumerate(rows) if r["status"] == "todo"]
    if not todo:
        return None
    todo.sort(key=lambda t: (t[0], t[1]))
    return todo[0][2]


def find(rows, keyword):
    k = keyword.strip().lower()
    for r in rows:
        if r["keyword"].lower() == k or (r["slug"] and r["slug"] == keyword.strip()):
            return r
    return None


def update(project, keyword, **fields):
    rows = read(project)
    r = find(rows, keyword)
    if not r:
        raise BacklogError(f"keyword '{keyword}' is not in the backlog")
    for k, v in fields.items():
        if v is None or k not in COLUMNS:
            continue
        r[k] = str(v)
    if fields.get("status") == "drafting" and not r["slug"]:
        r["slug"] = slugify(r["keyword"])
    if fields.get("status") == "published" and not fields.get("published_at"):
        r["published_at"] = dt.date.today().isoformat()
    write(project, rows)
    return r


def add(project, keyword, cluster="", priority="2", intent_hint="", notes=""):
    rows = read(project)
    if find(rows, keyword):
        raise BacklogError(f"keyword '{keyword}' is already in the backlog")
    rows.append({"keyword": keyword, "cluster": cluster, "priority": str(priority), "intent_hint": intent_hint,
                 "status": "todo", "slug": "", "published_at": "", "notes": notes})
    write(project, rows)
    return rows[-1]


def summary(project):
    rows = read(project)
    counts = {s: 0 for s in STATUSES}
    for r in rows:
        counts[r["status"]] += 1
    return {"total": len(rows), "by_status": counts}
