"""ProofPress command line.

    proofpress init ~/my-site [--name "My Product"]
    proofpress ui [--project ~/my-site]           settings page in your browser
    proofpress status                              what's missing before writing / publishing
    proofpress backlog list|next|set|add
    proofpress articles                            approved articles (for cannibalisation checks)
    proofpress scan content/drafts/<slug>/draft-1.md --keyword "..."
    proofpress approve --slug <slug> [--draft draft-2.md]
    proofpress hero --slug <slug>
    proofpress build
    proofpress deploy [--dry-run]
    proofpress publish [--slug <slug>] [--dry-run]

--project defaults to $PROOFPRESS_PROJECT, then the current folder.
"""
import argparse
import json
import os
import sys

from . import __version__
from . import articles, backlog as bl, project as pj
from .slop import format_report, scan


def _proj(a):
    return a.project or os.environ.get("PROOFPRESS_PROJECT") or os.getcwd()


def _print(obj):
    print(json.dumps(obj, indent=2, ensure_ascii=False))


def cmd_init(a):
    res = pj.init(a.dir, a.name)
    print(f"project ready at {res['project']}")
    for c in res["created"]:
        print(f"  created {c}")
    print(f"\nNext: proofpress ui --project {res['project']}")


def cmd_ui(a):
    from .ui_server import serve
    serve(_proj(a), port=a.port, open_browser=not a.no_open)


def cmd_status(a):
    res = pj.validate(_proj(a))
    res["backlog"] = bl.summary(_proj(a))
    _print(res)
    if res["errors"]:
        sys.exit(1)


def cmd_backlog(a):
    p = _proj(a)
    if a.action == "list":
        rows = bl.read(p)
        if a.status:
            rows = [r for r in rows if r["status"] == a.status]
        _print(rows)
    elif a.action == "next":
        r = bl.next_todo(p)
        _print(r or {"message": "backlog has no todo rows"})
    elif a.action == "set":
        if not a.keyword:
            sys.exit("--keyword is required")
        _print(bl.update(p, a.keyword, status=a.status, slug=a.slug, notes=a.notes))
    elif a.action == "add":
        if not a.keyword:
            sys.exit("--keyword is required")
        _print(bl.add(p, a.keyword, a.cluster or "", a.priority or "2", a.intent or "", a.notes or ""))


def cmd_articles(a):
    _print(articles.list_articles(_proj(a)))


def cmd_scan(a):
    lang, extra = a.lang or "en", []
    proj = a.project or os.environ.get("PROOFPRESS_PROJECT")
    if proj:
        try:
            s = pj.load(proj)
            lang = a.lang or s["site"].get("language") or "en"
            extra = s["quality"].get("extra_banned_phrases") or []
        except pj.ProjectError:
            pass
    text = open(a.path, encoding="utf-8").read()
    res = scan(text, a.keyword or "", lang, extra)
    print(format_report(res), end="")
    sys.exit(0 if res["passed"] else 1)


def cmd_approve(a):
    print(articles.approve(_proj(a), a.slug, a.draft))


def cmd_hero(a):
    from .hero import make
    print(make(_proj(a), a.slug, a.title))


def cmd_build(a):
    from .build import build
    res = build(_proj(a))
    print(f"built {len(res['articles'])} article(s) into {res['public']}")
    for u in res["articles"]:
        print("  " + u)
    if res["broken_links"]:
        print("BROKEN INTERNAL LINKS:")
        for b in res["broken_links"]:
            print("  " + b)
        sys.exit(1)


def cmd_deploy(a):
    from .deploy import deploy
    res = deploy(_proj(a), dry_run=a.dry_run)
    print("\n".join(x for x in res["log"] if x))
    print(("DRY RUN, nothing uploaded. " if a.dry_run else "Deployed: ") + res["url"])


def cmd_publish(a):
    from .publish import publish
    res = publish(_proj(a), slug=a.slug, dry_run=a.dry_run)
    print("\n".join(x for x in res.get("log", []) if x))
    if res.get("message"):
        print(res["message"])
    if res.get("url"):
        print(("DRY RUN: " if a.dry_run else "Live: ") + res["url"])
    if res.get("published"):
        print("published: " + ", ".join(res["published"]))


def main(argv=None):
    ap = argparse.ArgumentParser(prog="proofpress", description="Fact-checked SEO article pipeline.")
    ap.add_argument("--version", action="version", version=f"proofpress {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add(name, fn, help_):
        p = sub.add_parser(name, help=help_)
        p.add_argument("--project", help="project folder (default: $PROOFPRESS_PROJECT or current folder)")
        p.set_defaults(fn=fn)
        return p

    p = sub.add_parser("init", help="create a project folder")
    p.add_argument("dir")
    p.add_argument("--name")
    p.set_defaults(fn=cmd_init)

    p = add("ui", cmd_ui, "open the settings page")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--no-open", action="store_true")

    add("status", cmd_status, "check settings, backlog and publishing")

    p = add("backlog", cmd_backlog, "read or change the keyword backlog")
    p.add_argument("action", choices=["list", "next", "set", "add"])
    p.add_argument("--keyword")
    p.add_argument("--status", choices=bl.STATUSES)
    p.add_argument("--slug")
    p.add_argument("--cluster")
    p.add_argument("--priority", choices=["1", "2", "3"])
    p.add_argument("--intent")
    p.add_argument("--notes")

    add("articles", cmd_articles, "list approved articles")

    p = add("scan", cmd_scan, "anti-slop scan of a draft")
    p.add_argument("path")
    p.add_argument("--keyword")
    p.add_argument("--lang")

    p = add("approve", cmd_approve, "copy a passing draft into content/articles")
    p.add_argument("--slug", required=True)
    p.add_argument("--draft")

    p = add("hero", cmd_hero, "draw the hero / OG image")
    p.add_argument("--slug", required=True)
    p.add_argument("--title")

    add("build", cmd_build, "build the static site into public/")

    p = add("deploy", cmd_deploy, "upload public/ with the chosen provider")
    p.add_argument("--dry-run", action="store_true")

    p = add("publish", cmd_publish, "build+deploy (site mode) or push articles to your existing site")
    p.add_argument("--slug")
    p.add_argument("--dry-run", action="store_true")

    a = ap.parse_args(argv)
    try:
        a.fn(a)
    except (pj.ProjectError, bl.BacklogError, articles.ArticleError) as e:
        sys.exit(f"error: {e}")
    except Exception as e:  # surface friendly messages from build/deploy/publish/hero
        name = type(e).__name__
        if name in ("BuildError", "DeployError", "PublishError", "HeroError"):
            sys.exit(f"error: {e}")
        raise


if __name__ == "__main__":
    main()
