#!/usr/bin/env python3
"""End-to-end smoke test. No network, no accounts.

    python3 tests/smoke_test.py

Covers: init, settings save + context generation, backlog parse/update, scanner,
approve, build (with and without Pillow), markdown-repo publish into a temp git repo,
deploy dry runs, and the MCP server over stdio.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from proofpress import articles, backlog as bl, project as pj  # noqa: E402
from proofpress.slop import scan  # noqa: E402

DEMO = ROOT / "examples/demo-project"
SLUG = "how-to-make-a-plant-watering-schedule"
failures = []


def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  ({detail})" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def main():
    tmp = Path(tempfile.mkdtemp(prefix="proofpress-test-"))
    try:
        run(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"\n{len(failures)} failure(s)" if failures else "\nall checks passed")
    sys.exit(1 if failures else 0)


def run(tmp):
    proj = tmp / "site"
    pj.init(proj, "Test")
    check("init creates settings", (proj / "proofpress.json").exists())
    check("init: status reports errors on empty project", bool(pj.validate(proj)["errors"]))

    demo = json.loads((DEMO / "proofpress.json").read_text(encoding="utf-8"))
    pj.save(proj, demo)
    check("context/product.md generated", "Per-plant watering schedules" in (proj / "context/product.md").read_text(encoding="utf-8"))

    shutil.copy(DEMO / "backlog.csv", proj / "backlog.csv")
    rows = bl.read(proj)
    check("backlog parses", len(rows) == 6)
    nxt = bl.next_todo(proj)
    check("backlog next = priority 1 todo", nxt and nxt["keyword"] == "best plant watering app")
    r = bl.update(proj, "best plant watering app", status="drafting")
    check("drafting fills slug", r["slug"] == "best-plant-watering-app")
    try:
        bl.parse_text("word\nfoo\n")
        check("CSV without keyword header rejected", False)
    except bl.BacklogError:
        check("CSV without keyword header rejected", True)

    text = (DEMO / f"content/articles/{SLUG}.md").read_text(encoding="utf-8")
    res = scan(text, "plant watering schedule", "en")
    check("demo article passes scanner", res["passed"], res["hard_failures"])
    bad = scan(text.replace("It gives each plant", "It seamlessly gives each plant — fast"), "", "en")
    check("scanner catches hype word and em dash", len(bad["hard_failures"]) >= 2)

    articles.write_draft_file(proj, SLUG, "draft-1.md", text)
    articles.approve(proj, SLUG)
    check("approve copies draft", (proj / f"content/articles/{SLUG}.md").exists())
    check("approve marks backlog", bl.find(bl.read(proj), SLUG)["status"] == "approved")

    try:
        import markdown  # noqa: F401
        has_md = True
    except ImportError:
        has_md = False
    if has_md:
        from proofpress.build import build
        out = build(proj)
        page = proj / f"public/blog/{SLUG}/index.html"
        check("build writes article page", page.exists())
        html = page.read_text(encoding="utf-8")
        check("article has FAQPage schema", '"FAQPage"' in html)
        check("no broken internal links", not out["broken_links"], out["broken_links"])
        check("sitemap lists article", SLUG in (proj / "public/sitemap.xml").read_text(encoding="utf-8"))
    else:
        print("skip build checks (pip install markdown)")

    try:
        from proofpress.hero import make
        make(proj, SLUG)
        check("hero image drawn", (proj / f"static/images/{SLUG}.png").exists())
    except Exception as e:
        print(f"skip hero ({e})")

    if has_md:
        from proofpress.publish import publish
        s = pj.load(proj)
        for prov, extra in [("s3", {"bucket": "b", "cloudfront_distribution_id": "E1"}), ("cloudflare", {"project_name": "p"}),
                            ("netlify", {"site_id": "x"}), ("vercel", {})]:
            s["publish"]["site_provider"] = prov
            if extra:
                s["publish"][prov].update(extra)
            pj.save(proj, s)
            res = publish(proj, dry_run=True)
            check(f"dry run {prov}", any(line.startswith(("$ ", "would upload")) for line in res["log"]), res["log"])

        if shutil.which("git"):
            repo = tmp / "repo"
            env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.com",
                       GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.com")
            os.environ.update({k: env[k] for k in ("GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL")})
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            s["publish"]["mode"] = "existing"
            s["publish"]["existing_target"] = "markdown-repo"
            s["publish"]["markdown_repo"]["repo_path"] = str(repo)
            pj.save(proj, s)
            res = publish(proj)
            md = repo / f"src/content/blog/{SLUG}.md"
            check("markdown-repo writes post", md.exists())
            check("astro frontmatter", md.exists() and "pubDate:" in md.read_text(encoding="utf-8"))
            log = subprocess.run(["git", "-C", str(repo), "log", "--oneline"], capture_output=True, text=True).stdout
            check("markdown-repo commits", "ProofPress" in log)
            check("backlog marked published", bl.find(bl.read(proj), SLUG)["status"] == "published")
            check("second publish is a no-op", publish(proj)["published"] == [])

    env = dict(os.environ, PROOFPRESS_PROJECT=str(proj))
    p = subprocess.Popen([sys.executable, str(ROOT / "mcp/server.py")], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         text=True, env=env)
    msgs = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "backlog_next", "arguments": {}}},
        {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "get_instructions", "arguments": {"topic": "pipeline"}}},
    ]
    out, _ = p.communicate("\n".join(json.dumps(m) for m in msgs) + "\n", timeout=20)
    replies = [json.loads(line) for line in out.splitlines() if line.strip()]
    check("mcp: 4 replies (notification gets none)", len(replies) == 4, len(replies))
    check("mcp: tools listed", len(replies[1]["result"]["tools"]) >= 15)
    check("mcp: backlog_next works", "keyword" in replies[2]["result"]["content"][0]["text"])
    check("mcp: playbook returned", "Pipeline at a glance" in replies[3]["result"]["content"][0]["text"])


if __name__ == "__main__":
    main()
