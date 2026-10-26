"""1200x630 branded hero / Open Graph image, drawn locally (no image API, no cost).

Writes static/images/<slug>.png. Needs Pillow (pip install pillow).
"""
import random
import re

from . import articles
from .project import load, require_project, slugify

W, H = 1200, 630
BOLD = [
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/Library/Fonts/Arial Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
]
REGULAR = [
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/Library/Fonts/Arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    "C:/Windows/Fonts/arial.ttf",
]
CJK = [
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/noto-cjk/NotoSansCJK-Bold.ttc",
    "C:/Windows/Fonts/msyhbd.ttc",
]


class HeroError(Exception):
    pass


def _font(cands, size):
    from pathlib import Path
    from PIL import ImageFont

    for p in cands:
        if Path(p).exists():
            try:
                return ImageFont.truetype(p, size)
            except OSError:
                continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def _rgb(h, fallback):
    h = (h or fallback).lstrip("#")
    if len(h) != 6:
        h = fallback.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _wrap(draw, text, fnt, max_w, cjk):
    units = list(text) if cjk else text.split()
    lines, cur = [], ""
    for u in units:
        t = (cur + u) if cjk else (cur + " " + u).strip()
        if draw.textlength(t, font=fnt) <= max_w:
            cur = t
        else:
            if cur:
                lines.append(cur)
            cur = u
    if cur:
        lines.append(cur)
    return lines


def _title(project, slug):
    r = require_project(project)
    cands = [r / f"content/articles/{slug}.md"]
    d = articles.latest_draft(r, slug)
    if d:
        cands.append(d)
    for p in cands:
        if p.exists():
            m = re.search(r"^title:\s*(.+)$", p.read_text(encoding="utf-8"), re.M)
            if m:
                return m.group(1).strip().strip('"')
    raise HeroError(f"no title found for '{slug}'; pass a title")


def make(project, slug, title=None):
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        raise HeroError("Pillow is not installed: pip install pillow (or skip the hero image)")
    r = require_project(project)
    s = load(r)
    slug = slugify(slug)
    b = s["brand"]
    primary = _rgb(b.get("primary"), "#1F3A5F")
    accent = _rgb(b.get("accent"), "#F2B134")
    bg = _rgb(b.get("background"), "#FFF8EE")
    txt = _rgb(b.get("text"), "#1E1E1E")
    title = title or _title(r, slug)
    title = re.sub(r"\s*\((?:[^)]*)\)\s*$", "", title)
    cjk = bool(re.search(r"[\u3040-\u30ff\u4e00-\u9fff]", title))
    bold = CJK + BOLD if cjk else BOLD

    img = Image.new("RGB", (W, H), bg)
    d = ImageDraw.Draw(img)
    rnd = random.Random(slug)
    for _ in range(12):
        size = rnd.randint(30, 90)
        x, y = rnd.randint(860 + size // 2, 1200 - size // 4), rnd.randint(20, 610)
        shade = accent if rnd.random() < 0.6 else primary
        if rnd.random() < 0.5:
            d.ellipse([x - size // 2, y - size // 2, x + size // 2, y + size // 2], fill=shade)
        else:
            d.rounded_rectangle([x - size // 2, y - size // 2, x + size // 2, y + size // 2], radius=size // 4, fill=shade)
    d.rectangle([0, 0, 18, H], fill=primary)
    d.rectangle([820, 0, 826, H], fill=accent)

    size = 72 if not cjk else 64
    f = _font(bold, size)
    lines = _wrap(d, title, f, 700, cjk)
    while len(lines) > 4 and size > 40:
        size -= 6
        f = _font(bold, size)
        lines = _wrap(d, title, f, 700, cjk)
    y = 110
    for ln in lines[:5]:
        d.text((70, y), ln, font=f, fill=txt)
        y += int(size * 1.2)

    name = s["site"].get("name") or s["product"].get("name") or ""
    if name:
        nf = _font(CJK + BOLD if re.search(r"[\u3040-\u30ff\u4e00-\u9fff]", name) else BOLD, 32)
        w = int(d.textlength(name, font=nf)) + 60
        d.rounded_rectangle([70, 520, 70 + w, 578], radius=29, fill=primary)
        d.text((100, 531), name, font=nf, fill=(255, 255, 255))
        tag = s["product"].get("one_liner") or ""
        if tag:
            tf = _font(CJK + REGULAR if re.search(r"[\u3040-\u30ff\u4e00-\u9fff]", tag) else REGULAR, 22)
            room = 805 - (90 + w)
            while tag and d.textlength(tag, font=tf) > room:
                tag = tag[:-2]
            if tag != (s["product"].get("one_liner") or ""):
                tag = tag.rstrip() + "..."
            d.text((90 + w, 538), tag, font=tf, fill=primary)

    out = r / f"static/images/{slug}.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, optimize=True)
    return str(out)
