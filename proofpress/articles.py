"""Articles and drafts on disk.

Frontmatter is deliberately simple: `key: value` lines between `---` fences.
Lists are comma-separated. Required: title, meta_description, slug.
"""
import datetime as dt
import re
import shutil

from . import backlog as bl
from .project import require_project, slugify

REQUIRED = ("title", "meta_description", "slug")
DRAFT_FILES = re.compile(r"^(brief\.md|sources\.md|draft-\d+\.md|scan-\d+\.txt|scorecard-\d+\.md|notes\.md)$")


class ArticleError(Exception):
    pass


def split(raw):
    if raw.startswith("---"):
        end = raw.find("\n---", 3)
        if end != -1:
            return raw[3:end], raw[end + 4:].lstrip("\n")
    return "", raw


def parse_meta(fm):
    meta = {}
    for line in fm.splitlines():
        if ":" in line and not line.startswith((" ", "\t", "#")):
            k, v = line.split(":", 1)
            meta[k.strip()] = v.strip().strip('"')
    return meta


def parse(path, strict=True):
    raw = path.read_text(encoding="utf-8")
    fm, body = split(raw)
    meta = parse_meta(fm)
    if strict:
        missing = [k for k in REQUIRED if not meta.get(k)]
        if missing:
            raise ArticleError(f"{path.name}: frontmatter missing {', '.join(missing)}")
    m = re.match(r"^#\s+(.+)\n", body)
    meta["h1"] = meta.get("title", "")
    if m:
        meta["h1"] = m.group(1).strip()
        body = body[m.end():]
    meta.setdefault("published", dt.date.today().isoformat())
    meta["updated"] = meta.get("updated") or meta["published"]
    return meta, body


def list_articles(project):
    r = require_project(project)
    out = []
    for p in sorted((r / "content/articles").glob("*.md")):
        try:
            meta, _ = parse(p)
        except ArticleError as e:
            out.append({"file": p.name, "error": str(e)})
            continue
        out.append({
            "slug": meta["slug"], "title": meta["title"], "description": meta["meta_description"],
            "keyword": meta.get("primary_keyword", ""), "secondary_keywords": meta.get("secondary_keywords", ""),
            "cluster": meta.get("cluster", ""), "intent": meta.get("intent", ""),
            "published": meta["published"], "updated": meta["updated"], "file": p.name,
        })
    out.sort(key=lambda a: a.get("published", ""), reverse=True)
    return out


def draft_dir(project, slug):
    d = require_project(project) / "content/drafts" / slugify(slug)
    d.mkdir(parents=True, exist_ok=True)
    return d


def write_draft_file(project, slug, filename, content):
    if not DRAFT_FILES.match(filename):
        raise ArticleError("filename must be brief.md, sources.md, notes.md, draft-N.md, scan-N.txt or scorecard-N.md")
    p = draft_dir(project, slug) / filename
    p.write_text(content, encoding="utf-8")
    return str(p)


def read_draft_file(project, slug, filename):
    p = require_project(project) / "content/drafts" / slugify(slug) / filename
    if not p.exists():
        raise ArticleError(f"{p} does not exist")
    return p.read_text(encoding="utf-8")


def latest_draft(project, slug):
    d = require_project(project) / "content/drafts" / slugify(slug)
    drafts = sorted(d.glob("draft-*.md"), key=lambda p: int(re.findall(r"\d+", p.stem)[0]))
    return drafts[-1] if drafts else None


def approve(project, slug, draft=None):
    """Copy the chosen (or latest) draft to content/articles/<slug>.md and mark the backlog row approved."""
    r = require_project(project)
    slug = slugify(slug)
    src = (r / "content/drafts" / slug / draft) if draft else latest_draft(r, slug)
    if not src or not src.exists():
        raise ArticleError(f"no draft found for '{slug}'")
    meta, _ = parse(src)
    if meta["slug"] != slug:
        raise ArticleError(f"draft frontmatter slug '{meta['slug']}' does not match '{slug}'")
    dst = r / "content/articles" / f"{slug}.md"
    shutil.copy(src, dst)
    kw = meta.get("primary_keyword") or slug
    rows = bl.read(r)
    row = bl.find(rows, kw) or bl.find(rows, slug)
    if row:
        bl.update(r, row["keyword"], status="approved", slug=slug)
    return str(dst)
