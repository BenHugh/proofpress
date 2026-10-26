"""ProofPress MCP server (stdio, JSON-RPC 2.0, no dependencies).

Gives any MCP client (Claude Code, Claude Desktop, Cursor, Codex...) tools to run the
pipeline: read the product definition and rules, pick keywords, save drafts, scan
them, approve, draw hero images, build and publish. `get_instructions` returns the
full pipeline playbook, so the server also works in clients that don't load skills.

Run:  python3 mcp/server.py      (or: cli/proofpress-mcp)
Default project: $PROOFPRESS_PROJECT, overridable per call with "project".
"""
import json
import os
import sys
import traceback
from pathlib import Path

from . import __version__
from . import articles, backlog as bl, project as pj
from .slop import format_report, scan

REPO = Path(__file__).resolve().parent.parent
SKILL_DIR = REPO / "skills/proofpress"
PROTOCOLS = ["2025-06-18", "2025-03-26", "2024-11-05"]

P = {"project": {"type": "string", "description": "Project folder. Optional if PROOFPRESS_PROJECT is set."}}


def _schema(props=None, required=None):
    s = {"type": "object", "properties": dict(P, **(props or {}))}
    if required:
        s["required"] = required
    return s


TOOLS = [
    ("get_instructions", "Read the ProofPress playbook. Call with topic 'pipeline' before writing anything; other topics hold the detailed rules each step refers to.",
     _schema({"topic": {"type": "string", "enum": ["pipeline", "intent", "structure", "anti-slop", "rubric", "fact-check", "publishing"]}}, ["topic"])),
    ("init_project", "Create a new ProofPress project folder (safe to re-run).",
     {"type": "object", "properties": {"path": {"type": "string"}, "name": {"type": "string"}}, "required": ["path"]}),
    ("project_status", "Check settings, product definition, backlog and publishing. Errors block writing; tell the user to fix them in the settings UI (proofpress ui).",
     _schema()),
    ("read_context", "Read the project's rules the writer must follow: product (what exists / doesn't), voice (audience and tone), factcheck (claims to verify and approved sources), settings (site, CTA, quality thresholds).",
     _schema({"file": {"type": "string", "enum": ["product", "voice", "factcheck", "settings"]}}, ["file"])),
    ("backlog_list", "List keyword backlog rows, optionally filtered by status.",
     _schema({"status": {"type": "string", "enum": bl.STATUSES}})),
    ("backlog_next", "Return the highest-priority 'todo' keyword, or null when the backlog is empty (then stop and ask the user for keywords).",
     _schema()),
    ("backlog_update", "Change a backlog row (status, slug, notes). Setting status=drafting fills the slug automatically.",
     _schema({"keyword": {"type": "string"}, "status": {"type": "string", "enum": bl.STATUSES}, "slug": {"type": "string"}, "notes": {"type": "string"}}, ["keyword"])),
    ("backlog_add", "Add a keyword the USER asked for. Never add keywords on your own initiative.",
     _schema({"keyword": {"type": "string"}, "cluster": {"type": "string"}, "priority": {"type": "string", "enum": ["1", "2", "3"]},
              "intent_hint": {"type": "string", "enum": bl.INTENTS}, "notes": {"type": "string"}}, ["keyword"])),
    ("list_articles", "List approved articles (slug, title, keyword, cluster, intent). Use it for the cannibalisation check and for internal links.",
     _schema()),
    ("save_draft_file", "Write a working file for an article: brief.md, sources.md, notes.md, draft-N.md, scorecard-N.md.",
     _schema({"slug": {"type": "string"}, "filename": {"type": "string"}, "content": {"type": "string"}}, ["slug", "filename", "content"])),
    ("read_draft_file", "Read a working file back (brief.md, draft-N.md, scorecard-N.md...).",
     _schema({"slug": {"type": "string"}, "filename": {"type": "string"}}, ["slug", "filename"])),
    ("slop_scan", "Run the mechanical anti-slop scanner on a saved draft (slug + filename) or on raw text. Saves scan-N.txt next to draft-N.md. Hard failures must reach 0.",
     _schema({"slug": {"type": "string"}, "filename": {"type": "string"}, "text": {"type": "string"}, "keyword": {"type": "string"}})),
    ("approve_article", "Copy a passing draft into content/articles/<slug>.md and mark the backlog row approved. Only after the scorecard passes.",
     _schema({"slug": {"type": "string"}, "draft": {"type": "string", "description": "e.g. draft-2.md; default latest"}}, ["slug"])),
    ("make_hero_image", "Draw the 1200x630 hero / Open Graph image for an article (needs Pillow).",
     _schema({"slug": {"type": "string"}, "title": {"type": "string"}}, ["slug"])),
    ("build_site", "Static-site mode: rebuild public/ (pages, sitemap, schema). Reports broken internal links.",
     _schema()),
    ("publish", "Publish approved articles with the configured target. Use dry_run first if the user hasn't published before.",
     _schema({"slug": {"type": "string"}, "dry_run": {"type": "boolean"}})),
]

TOPIC_FILES = {
    "pipeline": "SKILL.md",
    "intent": "references/intent-playbook.md",
    "structure": "references/article-structure.md",
    "anti-slop": "references/anti-slop.md",
    "rubric": "references/scoring-rubric.md",
    "fact-check": "references/fact-check.md",
    "publishing": "references/publishing.md",
}


def _project(args):
    p = args.get("project") or os.environ.get("PROOFPRESS_PROJECT")
    if not p:
        raise pj.ProjectError("no project given: pass 'project' or set PROOFPRESS_PROJECT")
    return p


def call(name, args):
    if name == "get_instructions":
        f = SKILL_DIR / TOPIC_FILES[args["topic"]]
        text = f.read_text(encoding="utf-8")
        if args["topic"] == "pipeline":
            text += ("\n\n---\nYou are using the MCP tools, not the CLI. Map each CLI command in this playbook to the matching tool: "
                     "proofpress status -> project_status, backlog next/set -> backlog_next/backlog_update, articles -> list_articles, "
                     "scan -> slop_scan, approve -> approve_article, hero -> make_hero_image, build -> build_site, publish -> publish. "
                     "Read context files with read_context and reference docs with get_instructions. Write drafts with save_draft_file "
                     "if you have no file tools.")
        return text
    if name == "init_project":
        return pj.init(args["path"], args.get("name"))
    p = _project(args)
    if name == "project_status":
        res = pj.validate(p)
        res["backlog"] = bl.summary(p)
        return res
    if name == "read_context":
        if args["file"] == "settings":
            s = pj.load(p)
            return {k: s[k] for k in ("site", "brand", "cta", "quality", "publish")}
        pj.write_context(pj.root(p), pj.load(p))
        return (pj.root(p) / "context" / f"{args['file']}.md").read_text(encoding="utf-8")
    if name == "backlog_list":
        rows = bl.read(p)
        return [r for r in rows if not args.get("status") or r["status"] == args["status"]]
    if name == "backlog_next":
        return bl.next_todo(p)
    if name == "backlog_update":
        return bl.update(p, args["keyword"], status=args.get("status"), slug=args.get("slug"), notes=args.get("notes"))
    if name == "backlog_add":
        return bl.add(p, args["keyword"], args.get("cluster", ""), args.get("priority", "2"), args.get("intent_hint", ""), args.get("notes", ""))
    if name == "list_articles":
        return articles.list_articles(p)
    if name == "save_draft_file":
        return {"saved": articles.write_draft_file(p, args["slug"], args["filename"], args["content"])}
    if name == "read_draft_file":
        return articles.read_draft_file(p, args["slug"], args["filename"])
    if name == "slop_scan":
        s = pj.load(p)
        text = args.get("text")
        fn = args.get("filename")
        if not text:
            if not (args.get("slug") and fn):
                raise ValueError("pass either text, or slug + filename")
            text = articles.read_draft_file(p, args["slug"], fn)
        res = scan(text, args.get("keyword", ""), s["site"].get("language") or "en", s["quality"].get("extra_banned_phrases") or [])
        report = format_report(res)
        if args.get("slug") and fn and fn.startswith("draft-"):
            articles.write_draft_file(p, args["slug"], fn.replace("draft-", "scan-").replace(".md", ".txt"), report)
        return report
    if name == "approve_article":
        return {"approved": articles.approve(p, args["slug"], args.get("draft"))}
    if name == "make_hero_image":
        from .hero import make
        return {"image": make(p, args["slug"], args.get("title"))}
    if name == "build_site":
        from .build import build
        return build(p)
    if name == "publish":
        from .publish import publish
        return publish(p, slug=args.get("slug"), dry_run=bool(args.get("dry_run")))
    raise ValueError(f"unknown tool {name}")


def handle(msg):
    mid, method, params = msg.get("id"), msg.get("method"), msg.get("params") or {}
    if mid is None:  # notification
        return None
    if method == "initialize":
        req = params.get("protocolVersion")
        return {"jsonrpc": "2.0", "id": mid, "result": {
            "protocolVersion": req if req in PROTOCOLS else PROTOCOLS[0],
            "capabilities": {"tools": {}, "prompts": {}},
            "serverInfo": {"name": "proofpress", "version": __version__},
            "instructions": "ProofPress writes fact-checked SEO articles. Before writing, call get_instructions(topic='pipeline') and follow it step by step.",
        }}
    if method == "ping":
        return {"jsonrpc": "2.0", "id": mid, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": mid, "result": {"tools": [
            {"name": n, "description": d, "inputSchema": s} for n, d, s in TOOLS]}}
    if method == "tools/call":
        name, args = params.get("name"), params.get("arguments") or {}
        try:
            out = call(name, args)
            text = out if isinstance(out, str) else json.dumps(out, indent=2, ensure_ascii=False)
            return {"jsonrpc": "2.0", "id": mid, "result": {"content": [{"type": "text", "text": text}], "isError": False}}
        except Exception as e:
            known = type(e).__name__ in ("ProjectError", "BacklogError", "ArticleError", "BuildError", "DeployError", "PublishError", "HeroError", "ValueError", "KeyError")
            detail = str(e) if known else traceback.format_exc(limit=3)
            return {"jsonrpc": "2.0", "id": mid, "result": {"content": [{"type": "text", "text": f"error: {detail}"}], "isError": True}}
    if method == "prompts/list":
        return {"jsonrpc": "2.0", "id": mid, "result": {"prompts": [
            {"name": "write_next_article", "description": "Write, check and publish the next article from the backlog",
             "arguments": [{"name": "project", "description": "project folder", "required": False}]}]}}
    if method == "prompts/get":
        proj = (params.get("arguments") or {}).get("project") or os.environ.get("PROOFPRESS_PROJECT", "<project folder>")
        return {"jsonrpc": "2.0", "id": mid, "result": {"messages": [{"role": "user", "content": {"type": "text", "text":
            f"Use ProofPress to write the next article for the project at {proj}. Start with get_instructions(topic='pipeline') and follow every step."}}]}}
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"method not found: {method}"}}


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}}) + "\n")
            sys.stdout.flush()
            continue
        batch = msg if isinstance(msg, list) else [msg]
        out = [r for r in (handle(m) for m in batch) if r is not None]
        if out:
            sys.stdout.write(json.dumps(out if isinstance(msg, list) else out[0], ensure_ascii=False) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
