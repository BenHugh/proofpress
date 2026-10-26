"""Static site build: content/articles/*.md -> public/.

Rebuilds every page on every run so older articles pick up links to newer ones.
Produces: homepage, blog index, one page per article (Article + FAQPage + BreadcrumbList
JSON-LD, canonical, Open Graph), sitemap.xml, robots.txt, 404.html, articles.json, and
the host-specific config file for the chosen deploy provider (_headers / vercel.json).
"""
import datetime as dt
import html
import json
import re
import shutil
from pathlib import Path

from .articles import ArticleError, parse
from .project import load, require_project

PKG = Path(__file__).resolve().parent
START, END = "<!-- PROOFPRESS:ARTICLES:START -->", "<!-- PROOFPRESS:ARTICLES:END -->"
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August",
          "September", "October", "November", "December"]


class BuildError(Exception):
    pass


def _md():
    try:
        import markdown
    except ImportError:
        raise BuildError("missing dependency: pip install markdown")
    return markdown


def esc(s):
    return html.escape(str(s or ""), quote=True)


def md_to_html(body):
    body = re.sub(r"^---\s*$", "", body, flags=re.M)
    return _md().markdown(body, extensions=["tables", "sane_lists", "attr_list"])


def extract_faq(body):
    m = re.search(r"^##\s+(FAQ|FAQs|Frequently asked questions|常见问题|よくある質問)\s*$", body, re.M | re.I)
    if not m:
        return []
    rest = body[m.end():]
    stop = re.search(r"^(##\s|---\s*$)", rest, re.M)
    section = rest[: stop.start()] if stop else rest
    qa = []
    for block in re.split(r"^###\s+", section, flags=re.M)[1:]:
        q, _, a = block.partition("\n")
        a = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", a)
        a = re.sub(r"[*_`]", "", a).strip()
        if q.strip() and a:
            qa.append((q.strip(), " ".join(a.split())))
    return qa


def nice_date(iso, lang):
    if not re.match(r"\d{4}-\d{2}-\d{2}$", iso or ""):
        return iso or ""
    d = dt.date.fromisoformat(iso)
    if (lang or "en").startswith("en"):
        return f"{MONTHS[d.month - 1]} {d.day}, {d.year}"
    return iso


def load_articles(project, settings):
    r = require_project(project)
    base = settings["site"]["base_url"].rstrip("/")
    blog = settings["site"].get("blog_path", "blog").strip("/")
    arts = []
    for p in sorted((r / "content/articles").glob("*.md")):
        meta, body = parse(p)
        slug = meta["slug"]
        arts.append({
            "slug": slug, "meta": meta, "body": body,
            "title": meta["title"], "description": meta["meta_description"],
            "keyword": meta.get("primary_keyword", ""), "cluster": meta.get("cluster", ""),
            "intent": meta.get("intent", ""), "published": meta["published"], "updated": meta["updated"],
            "path": f"/{blog}/{slug}/", "url": f"{base}/{blog}/{slug}/",
        })
    arts.sort(key=lambda x: x["published"], reverse=True)
    return arts


def buttons_html(settings):
    out = []
    for i, b in enumerate(settings["cta"].get("buttons") or []):
        if b.get("url") and b.get("label"):
            cls = "btn" if i == 0 else "btn btn-alt"
            out.append(f'<a class="{cls}" href="{esc(b["url"])}" rel="noopener">{esc(b["label"])}</a>')
    return "\n".join(out)


def cta_html(settings):
    c = settings["cta"]
    btns = buttons_html(settings)
    if not (c.get("heading") or c.get("text") or btns):
        return ""
    return (f'<section class="cta-box">'
            + (f'<h2>{esc(c["heading"])}</h2>' if c.get("heading") else "")
            + (f'<p>{esc(c["text"])}</p>' if c.get("text") else "")
            + btns + "</section>")


def card_list(arts):
    items = [f'<li><a href="{a["path"]}">{esc(a["title"])}</a><p>{esc(a["description"])}</p></li>' for a in arts]
    return '<ul class="cards">' + "\n".join(items) + "</ul>"


def article_jsonld(settings, art, hero_url=None):
    site, meta = settings["site"], art["meta"]
    base = site["base_url"].rstrip("/")
    blog = site.get("blog_path", "blog").strip("/")
    ld = [{
        "@context": "https://schema.org", "@type": "Article",
        "headline": meta["h1"][:110], "description": art["description"],
        "datePublished": art["published"], "dateModified": art["updated"],
        "author": {"@type": "Organization", "name": site.get("author") or site.get("name")},
        "publisher": {"@type": "Organization", "name": site.get("name")},
        "mainEntityOfPage": art["url"],
    }, {
        "@context": "https://schema.org", "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "Home", "item": base + "/"},
            {"@type": "ListItem", "position": 2, "name": site.get("blog_label") or "Blog", "item": f"{base}/{blog}/"},
            {"@type": "ListItem", "position": 3, "name": meta["h1"], "item": art["url"]},
        ],
    }]
    if hero_url:
        ld[0]["image"] = hero_url
    faq = extract_faq(art["body"])
    if faq:
        ld.append({
            "@context": "https://schema.org", "@type": "FAQPage",
            "mainEntity": [{"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": a}} for q, a in faq],
        })
    return ld


def page(settings, title, desc, canonical, body, head_extra="", og_image=None, og_type="website"):
    site = settings["site"]
    blog = site.get("blog_path", "blog").strip("/")
    first = next((b for b in settings["cta"].get("buttons") or [] if b.get("url")), None)
    nav_cta = f'<a href="{esc(first["url"])}" rel="noopener">{esc(first["label"])}</a>' if first else ""
    footer = esc(site.get("footer_text") or settings["product"].get("one_liner") or "")
    return f"""<!doctype html>
<html lang="{esc(site.get('language') or 'en')}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
<meta name="description" content="{esc(desc)}">
<link rel="canonical" href="{esc(canonical)}">
<meta property="og:type" content="{og_type}">
<meta property="og:title" content="{esc(title)}">
<meta property="og:description" content="{esc(desc)}">
<meta property="og:url" content="{esc(canonical)}">
<meta property="og:site_name" content="{esc(site.get('name'))}">
{f'<meta property="og:image" content="{esc(og_image)}">' if og_image else ''}
<meta name="twitter:card" content="{'summary_large_image' if og_image else 'summary'}">
<link rel="stylesheet" href="/assets/site.css">
{head_extra}
</head>
<body>
<header class="site-header"><div class="wrap">
<a class="logo" href="/">{esc(site.get('name'))}</a>
<nav><a href="/{blog}/">{esc(site.get('blog_label') or 'Blog')}</a>{nav_cta}</nav>
</div></header>
<main class="wrap">
{body}
</main>
<footer class="site-footer"><div class="wrap">
{f'<p>{footer}</p>' if footer else ''}
<p><a href="/">Home</a> · <a href="/{blog}/">{esc(site.get('blog_label') or 'Blog')}</a></p>
</div></footer>
</body>
</html>
"""


def article_body_html(settings, art):
    """Article HTML without site chrome (also used by WordPress / webhook publishing)."""
    body_html = md_to_html(art["body"])
    dl = art["meta"].get("download")
    if dl:
        label = art["meta"].get("download_label") or "Download the free file"
        btn = f'<p class="download"><a class="btn" href="{esc(dl)}" download>{esc(label)}</a></p>'
        body_html = body_html.replace("</p>", "</p>\n" + btn, 1)
    return body_html


def host_files(settings, pub):
    prov = settings["publish"]["site_provider"]
    if prov in ("cloudflare", "netlify"):
        (pub / "_headers").write_text(
            "/*\n  Cache-Control: public, max-age=300\n"
            "/images/*\n  Cache-Control: public, max-age=604800\n"
            "/assets/*\n  Cache-Control: public, max-age=86400\n", encoding="utf-8")
    elif prov == "vercel":
        cfg = {
            "cleanUrls": False, "trailingSlash": True,
            "headers": [
                {"source": "/images/(.*)", "headers": [{"key": "Cache-Control", "value": "public, max-age=604800"}]},
                {"source": "/(.*)", "headers": [{"key": "Cache-Control", "value": "public, max-age=300"}]},
            ],
        }
        (pub / "vercel.json").write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")


def build(project):
    r = require_project(project)
    s = load(r)
    site = s["site"]
    base = (site.get("base_url") or "").rstrip("/")
    if not base:
        raise BuildError("site.base_url is empty; set the final https:// domain in Settings > Site")
    blog = site.get("blog_path", "blog").strip("/")
    lang = site.get("language") or "en"
    pub = r / "public"
    if pub.exists():
        shutil.rmtree(pub)
    pub.mkdir(parents=True)

    static = r / "static"
    if static.exists():
        for p in static.rglob("*"):
            if p.is_file() and p.relative_to(static).as_posix() != "index.html" and p.name != ".DS_Store":
                dst = pub / p.relative_to(static)
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(p, dst)
    (pub / "assets").mkdir(exist_ok=True)
    css = (PKG / "assets/site.css").read_text(encoding="utf-8")
    for k, v in s["brand"].items():
        css = css.replace(f"--{k}-default", v)
    (pub / "assets/site.css").write_text(css, encoding="utf-8")

    try:
        arts = load_articles(r, s)
    except ArticleError as e:
        raise BuildError(str(e))

    valid = {"/", f"/{blog}/", "/sitemap.xml", "/robots.txt", "/404.html"}
    valid |= {x["path"] for x in arts}
    valid |= {"/" + q.relative_to(pub).as_posix() for q in pub.rglob("*") if q.is_file()}
    broken = []
    cta = cta_html(s)

    for art in arts:
        meta, slug = art["meta"], art["slug"]
        body_html = article_body_html(s, art)
        for href in re.findall(r'href="([^"]+)"', body_html):
            h = href.replace(base, "") if href.startswith(base) else href
            if h.startswith("/"):
                h = h.split("#")[0].split("?")[0]
                if h not in valid and h.rstrip("/") + "/" not in valid:
                    broken.append(f"{slug}: {href}")
        hero = f"/images/{slug}.png"
        has_hero = (pub / hero.lstrip("/")).exists()
        hero_html = (f'<img class="hero" src="{hero}" alt="{esc(meta.get("hero_alt") or art["title"])}" width="1200" height="630">'
                     if has_hero else "")
        related = [x for x in arts if x["slug"] != slug and x["cluster"] and x["cluster"] == art["cluster"]]
        related += [x for x in arts if x["slug"] != slug and x not in related]
        related = related[:3]
        rel_html = (f'<aside class="related"><h2>Related</h2>{card_list(related)}</aside>') if related else ""
        ld = article_jsonld(s, art, base + hero if has_hero else None)
        head = "\n".join(f'<script type="application/ld+json">{json.dumps(x, ensure_ascii=False)}</script>' for x in ld)
        upd = nice_date(art["updated"], lang)
        byline = " · ".join(x for x in [esc(site.get("author")), ("Updated " + upd) if lang.startswith("en") else upd] if x)
        body = f"""<nav class="crumbs"><a href="/">Home</a> › <a href="/{blog}/">{esc(site.get('blog_label') or 'Blog')}</a></nav>
<article>
<h1>{esc(meta['h1'])}</h1>
<p class="byline">{byline}</p>
{hero_html}
{body_html}
</article>
{cta}
{rel_html}"""
        out = pub / blog / slug / "index.html"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(page(s, art["title"], art["description"], art["url"], body, head,
                            base + hero if has_hero else None, "article"), encoding="utf-8")

    label = site.get("blog_label") or "Blog"
    intro = site.get("home_lede") or s["product"].get("one_liner") or ""
    blog_body = (f"<h1>{esc(label)}</h1>" + (f'<p class="lede">{esc(intro)}</p>' if intro else "")
                 + (card_list(arts) if arts else "<p>First articles coming soon.</p>"))
    (pub / blog).mkdir(parents=True, exist_ok=True)
    (pub / blog / "index.html").write_text(
        page(s, f"{label} | {site.get('name')}", intro or label, f"{base}/{blog}/", blog_body), encoding="utf-8")

    latest = card_list(arts[:6]) + f'<p><a href="/{blog}/">All {esc(label.lower())} →</a></p>'
    home_src = static / "index.html"
    if home_src.exists():
        h = home_src.read_text(encoding="utf-8")
        if START in h and END in h:
            h = h[: h.index(START) + len(START)] + "\n" + latest + "\n" + h[h.index(END):]
        else:
            print(f"WARNING: static/index.html has no {START} / {END} markers; homepage article list not updated")
        (pub / "index.html").write_text(h, encoding="utf-8")
    else:
        headline = site.get("home_headline") or site.get("name")
        home_body = (f'<section class="home-hero"><h1>{esc(headline)}</h1>'
                     + (f'<p class="lede">{esc(intro)}</p>' if intro else "")
                     + buttons_html(s) + f"</section><section><h2>Latest</h2>{START}\n{latest}\n{END}</section>")
        (pub / "index.html").write_text(page(s, site.get("name"), intro or site.get("name"), base + "/", home_body), encoding="utf-8")

    (pub / "404.html").write_text(page(s, f"Page not found | {site.get('name')}", "Page not found.", base + "/404.html",
                                       f'<h1>That page isn\'t here</h1><p><a href="/">Go home</a> or <a href="/{blog}/">browse the {esc(label.lower())}</a>.</p>'),
                                  encoding="utf-8")

    urls = [(base + "/", None), (f"{base}/{blog}/", arts[0]["updated"] if arts else None)] + [(x["url"], x["updated"]) for x in arts]
    sm = ['<?xml version="1.0" encoding="UTF-8"?>', '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    sm += [f"<url><loc>{esc(u)}</loc>{f'<lastmod>{lm}</lastmod>' if lm else ''}</url>" for u, lm in urls]
    sm.append("</urlset>")
    (pub / "sitemap.xml").write_text("\n".join(sm) + "\n", encoding="utf-8")
    (pub / "robots.txt").write_text(f"User-agent: *\nAllow: /\nSitemap: {base}/sitemap.xml\n", encoding="utf-8")
    manifest = [{k: x[k] for k in ("slug", "title", "description", "keyword", "cluster", "intent", "published", "updated", "path", "url")} for x in arts]
    (pub / "articles.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    host_files(s, pub)

    return {"public": str(pub), "articles": [x["url"] for x in arts], "broken_links": broken}
