"""Publishing approved articles.

mode "site"      -> build the whole static site, then deploy it (see deploy.py)
mode "existing"  -> push each approved article into a site the user already has:
    markdown-repo   write Markdown + hero image into an Astro / Hugo / Next / Eleventy repo, commit (and push)
    wordpress       create or update a post through the REST API (draft by default)
    webhook         POST a JSON payload to any URL (Zapier, Make, n8n, your own endpoint)
"""
import base64
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

from . import backlog as bl
from .articles import parse
from .build import BuildError, article_body_html, article_jsonld, build, load_articles
from .deploy import DeployError, deploy
from .project import load, publish_readiness, require_project, save_state, state


class PublishError(Exception):
    pass


def _targets(r, s, slug):
    arts = load_articles(r, s) if (s["site"].get("base_url") or "").strip() else _arts_no_base(r, s)
    if slug:
        arts = [a for a in arts if a["slug"] == slug]
        if not arts:
            raise PublishError(f"no approved article with slug '{slug}' in content/articles/")
        return arts
    rows = bl.read(r)
    done = {x["slug"] for x in rows if x["status"] == "published" and x["slug"]}
    return [a for a in arts if a["slug"] not in done]


def _arts_no_base(r, s):
    s2 = json.loads(json.dumps(s))
    s2["site"]["base_url"] = "https://example.invalid"
    return load_articles(r, s2)


def _mark_published(r, slugs):
    rows = bl.read(r)
    today = dt.date.today().isoformat()
    for row in rows:
        if row["slug"] in slugs and row["status"] in ("approved", "drafting"):
            row["status"] = "published"
            row["published_at"] = row["published_at"] or today
    bl.write(r, rows)


# ------------------------------------------------------------------ markdown repo

def _yaml(v):
    return json.dumps(v, ensure_ascii=False)


def frontmatter_for(preset, art, image_url):
    m = art["meta"]
    if preset == "astro":
        fm = {"title": m["title"], "description": m["meta_description"], "pubDate": art["published"], "updatedDate": art["updated"]}
        if image_url:
            fm["heroImage"] = image_url
    elif preset == "hugo":
        fm = {"title": m["title"], "description": m["meta_description"], "date": art["published"], "lastmod": art["updated"], "slug": art["slug"]}
        if image_url:
            fm["images"] = [image_url]
    else:
        fm = {k: v for k, v in m.items() if k not in ("h1",)}
        if image_url:
            fm["image"] = image_url
    if m.get("primary_keyword"):
        fm.setdefault("keywords", [k.strip() for k in ([m["primary_keyword"]] + m.get("secondary_keywords", "").split(",")) if k.strip()])
    return "---\n" + "\n".join(f"{k}: {_yaml(v)}" for k, v in fm.items()) + "\n---\n\n"


def _git(repo, args, log):
    cmd = ["git", "-C", str(repo)] + args
    log.append("$ " + " ".join(cmd))
    res = subprocess.run(cmd, capture_output=True, text=True)
    out = (res.stdout + res.stderr).strip()
    if out:
        log.append(out[-2000:])
    if res.returncode != 0:
        raise PublishError(f"git {' '.join(args)} failed: {out[-800:]}")
    return out


def to_markdown_repo(r, s, arts, log, dry):
    c = s["publish"]["markdown_repo"]
    repo = Path(c["repo_path"]).expanduser()
    if not repo.exists():
        raise PublishError(f"{repo} does not exist")
    content_dir = repo / c["content_dir"].strip("/")
    image_dir = repo / c["image_dir"].strip("/") if c.get("image_dir") else None
    written = []
    for a in arts:
        hero = r / f"static/images/{a['slug']}.png"
        image_url = None
        if hero.exists() and image_dir:
            image_url = c.get("image_url_prefix", "").rstrip("/") + f"/{a['slug']}.png"
            if not dry:
                image_dir.mkdir(parents=True, exist_ok=True)
                shutil.copy2(hero, image_dir / hero.name)
            written.append(str(image_dir / hero.name))
        if c.get("file_layout") == "folder":
            dst = content_dir / a["slug"] / "index.md"
        else:
            dst = content_dir / f"{a['slug']}.md"
        body = re.sub(r"^---\s*$", "", a["body"], flags=re.M).lstrip()
        text = frontmatter_for(c.get("frontmatter", "astro"), a, image_url) + body
        if not dry:
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_text(text, encoding="utf-8")
        written.append(str(dst))
        if a["meta"].get("download"):
            log.append(f"note: {a['slug']} links to {a['meta']['download']}; copy that file into your site's public folder")
    log += [("would write " if dry else "wrote ") + w for w in written]
    if c.get("commit", True) and (repo / ".git").exists() and not dry:
        _git(repo, ["add", "-A", "--"] + written, log)
        if _git(repo, ["status", "--porcelain"], log).strip():
            _git(repo, ["commit", "-m", "ProofPress: " + ", ".join(a["slug"] for a in arts)[:200]], log)
            if c.get("push"):
                _git(repo, ["push"], log)
    return written


# ------------------------------------------------------------------ http helpers

def _request(url, data=None, headers=None, method="POST"):
    req = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = resp.read().decode("utf-8", "replace")
            return resp.status, body
    except urllib.error.HTTPError as e:
        raise PublishError(f"{method} {url} -> HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:600]}")
    except urllib.error.URLError as e:
        raise PublishError(f"{method} {url} failed: {e.reason}")


# ------------------------------------------------------------------ wordpress

def to_wordpress(r, s, arts, log, dry):
    c = s["publish"]["wordpress"]
    pw = os.environ.get("WP_APP_PASSWORD")
    if not pw and not dry:
        raise PublishError("environment variable WP_APP_PASSWORD is not set (create an Application Password in WordPress: Users > Profile)")
    api = c["url"].rstrip("/") + "/wp-json/wp/v2"
    auth = "Basic " + base64.b64encode(f"{c['username']}:{pw or ''}".encode()).decode()
    st = state(r)
    ids = st.setdefault("wordpress", {})
    done = []
    for a in arts:
        html_body = article_body_html(s, a)
        payload = {"title": a["meta"]["title"], "content": html_body, "excerpt": a["description"],
                   "slug": a["slug"], "status": c.get("status") or "draft"}
        hero = r / f"static/images/{a['slug']}.png"
        if dry:
            log.append(f"would {'update' if a['slug'] in ids else 'create'} WordPress post '{a['slug']}' ({payload['status']})")
            continue
        if hero.exists() and not ids.get(a["slug"], {}).get("media"):
            _, body = _request(api + "/media", hero.read_bytes(), {
                "Authorization": auth, "Content-Type": "image/png",
                "Content-Disposition": f'attachment; filename="{hero.name}"'})
            media = json.loads(body)
            ids.setdefault(a["slug"], {})["media"] = media["id"]
            if a["meta"].get("hero_alt"):
                _request(f"{api}/media/{media['id']}", json.dumps({"alt_text": a["meta"]["hero_alt"]}).encode(),
                         {"Authorization": auth, "Content-Type": "application/json"})
        if ids.get(a["slug"], {}).get("media"):
            payload["featured_media"] = ids[a["slug"]]["media"]
        post_id = ids.get(a["slug"], {}).get("post")
        url = f"{api}/posts/{post_id}" if post_id else f"{api}/posts"
        _, body = _request(url, json.dumps(payload).encode(), {"Authorization": auth, "Content-Type": "application/json"})
        post = json.loads(body)
        ids.setdefault(a["slug"], {})["post"] = post["id"]
        log.append(f"{'updated' if post_id else 'created'} post {post['id']} ({post.get('status')}): {post.get('link')}")
        done.append(a["slug"])
        save_state(r, st)
    return done


# ------------------------------------------------------------------ webhook

def to_webhook(r, s, arts, log, dry):
    url = s["publish"]["webhook"]["url"]
    secret = os.environ.get("PROOFPRESS_WEBHOOK_SECRET", "")
    done = []
    for a in arts:
        hero = r / f"static/images/{a['slug']}.png"
        payload = {
            "event": "article.published",
            "site": s["site"].get("name"),
            "slug": a["slug"],
            "path": a["path"],
            "frontmatter": {k: v for k, v in a["meta"].items() if k != "h1"},
            "title": a["meta"]["title"],
            "h1": a["meta"]["h1"],
            "meta_description": a["description"],
            "markdown": a["body"],
            "html": article_body_html(s, a),
            "jsonld": article_jsonld(s, a),
            "hero_image_png_base64": base64.b64encode(hero.read_bytes()).decode() if hero.exists() else None,
        }
        if dry:
            log.append(f"would POST {a['slug']} to {url}")
            continue
        headers = {"Content-Type": "application/json"}
        if secret:
            headers["X-ProofPress-Secret"] = secret
        status, _ = _request(url, json.dumps(payload, ensure_ascii=False).encode("utf-8"), headers)
        log.append(f"POST {a['slug']} -> HTTP {status}")
        done.append(a["slug"])
    return done


# ------------------------------------------------------------------ entry point

def publish(project, slug=None, dry_run=False):
    r = require_project(project)
    s = load(r)
    pub = s["publish"]
    log = []
    if pub["mode"] == "site":
        try:
            res = build(r)
        except BuildError as e:
            raise PublishError(str(e))
        if res["broken_links"]:
            raise PublishError("build found broken internal links, fix them first: " + "; ".join(res["broken_links"]))
        log.append(f"built {len(res['articles'])} article(s) into public/")
        if pub["site_provider"] == "none":
            return {"mode": "site", "deployed": False, "log": log,
                    "message": "Built only: choose a deploy provider in Settings > Publishing, or upload public/ yourself."}
        try:
            d = deploy(r, dry_run=dry_run)
        except DeployError as e:
            raise PublishError(f"built, but not deployed: {e}")
        log += d["log"]
        if not dry_run:
            _mark_published(r, {a["slug"] for a in _arts_no_base(r, s)})
        return {"mode": "site", "deployed": not dry_run, "url": d["url"], "log": log}

    ok, missing = publish_readiness(s)
    if not ok:
        raise PublishError("fill these settings first: " + ", ".join(missing))
    arts = _targets(r, s, slug)
    if not arts:
        return {"mode": "existing", "published": [], "log": ["nothing to publish: every approved article is already published"]}
    t = pub["existing_target"]
    if t == "markdown-repo":
        to_markdown_repo(r, s, arts, log, dry_run)
        done = [a["slug"] for a in arts]
    elif t == "wordpress":
        done = to_wordpress(r, s, arts, log, dry_run)
    elif t == "webhook":
        done = to_webhook(r, s, arts, log, dry_run)
    else:
        raise PublishError(f"unknown target '{t}'")
    if not dry_run:
        _mark_published(r, set(done))
    return {"mode": "existing", "target": t, "published": [] if dry_run else done, "dry_run": dry_run, "log": log}
