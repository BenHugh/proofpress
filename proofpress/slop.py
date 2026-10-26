"""Mechanical anti-slop scanner.

Hard failures must be fixed before an article can pass; warnings are judgment calls.
Only body prose is checked for style: frontmatter, code blocks, tables and URLs are skipped.
The English word lists apply when the site language starts with "en"; the structural
checks (dashes, paragraph length, keyword stuffing, emoji, owner-banned phrases) run in
every language.
"""
import re
from collections import Counter

HYPE = [
    "game-changer", "game changer", "revolutionary", "cutting-edge", "cutting edge",
    "seamless", "seamlessly", "effortless", "effortlessly", "robust", "ultimate",
    "unparalleled", "next-level", "next level", "supercharge", "elevate", "empower",
    "transformative", "skyrocket", "must-have", "top-notch", "world-class",
    "best-in-class", "state-of-the-art", "hassle-free", "unlock your", "unlock the",
]
CORP_VERBS = [
    "leverage", "leveraging", "utilize", "utilizing", "utilise", "facilitate",
    "streamline", "streamlining", "harness", "delve", "delving", "foster",
    "bolster", "spearhead", "embark",
]
PHRASES = [
    "in today's fast-paced", "ever-evolving", "ever evolving", "when it comes to",
    "it's no secret", "look no further", "to the next level",
    "the world of", "a testament to", "plays a crucial role", "plays a vital role",
    "plays a pivotal role", "it's important to note", "it is important to note",
    "it's worth noting", "it is worth noting", "at the end of the day",
    "in conclusion", "in summary", "without further ado", "deep dive", "dive in",
    "dive into", "buckle up", "we've got you covered", "say goodbye to",
    "rest assured", "peace of mind", "navigate the", "navigating the",
    "great question", "i hope this helps", "let's explore", "here's the thing",
]
HOOKS = [
    r"\bever wondered\b", r"^have you ever\b", r"^tired of\b", r"^struggling to\b",
    r"what if i told you", r"\bsound familiar\?", r"^ready to\b",
]
UNSUPPORTED = [
    r"\bthe #1\b", r"\bnumber one (app|tool|choice)\b", r"\bwe tested\b", r"\bwe've tested\b",
    r"\bi tested\b", r"\bguarantee[sd]?\b", r"\btrusted by\b", r"\b100% accurate\b",
    r"\bthousands of (users|customers|people|businesses)\b", r"\bmillions of (users|customers|people)\b",
    r"\baudit-proof\b", r"\b(irs|fda|government)[- ]approved\b",
]
WEAK_TRANSITIONS = [
    "additionally", "furthermore", "moreover", "in addition", "overall",
    "ultimately", "that said", "consequently", "notably", "importantly",
]
CONTRACTABLE = [
    r"\bdo not\b", r"\bdoes not\b", r"\bdid not\b", r"\bis not\b", r"\bare not\b",
    r"\bcannot\b", r"\bcan not\b", r"\bwill not\b", r"\byou are\b", r"\bit is\b",
    r"\bthat is\b", r"\byou will\b", r"\bwe are\b", r"\bthey are\b", r"\byou have\b",
    r"\bwould not\b", r"\bshould not\b", r"\bhave not\b", r"\bhas not\b",
]
CONTRACTION_RE = re.compile(r"\b\w+'(t|s|re|ll|ve|d|m)\b", re.I)
EMOJI_RE = re.compile("[\U0001F300-\U0001FAFF☀-➿]")


def _split_frontmatter(text):
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            return text[: end + 4], text[end + 4:]
    return "", text


def _blocks(body):
    in_code, para, start = False, [], 0
    for i, line in enumerate(body.splitlines(), 1):
        s = line.strip()
        if s.startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            continue
        if not s or s.startswith("|") or s.startswith("<!--") or s == "---":
            if para:
                yield "p", " ".join(para), start
                para = []
            continue
        if s.startswith("#"):
            if para:
                yield "p", " ".join(para), start
                para = []
            yield "h", s.lstrip("#").strip(), i
            continue
        if re.match(r"^([-*+]|\d+\.)\s", s):
            if para:
                yield "p", " ".join(para), start
                para = []
            yield "li", re.sub(r"^([-*+]|\d+\.)\s+", "", s), i
            continue
        if not para:
            start = i
        para.append(s)
    if para:
        yield "p", " ".join(para), start


def _strip_md(t):
    t = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", t)
    t = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", t)
    t = re.sub(r"https?://\S+", "", t)
    return re.sub(r"[*_`]", "", t)


def _sentences(t):
    parts = re.split(r"(?<=[.!?。！？])\s*(?=[A-Z0-9\"'(぀-ヿ一-鿿])", t)
    return [p.strip() for p in parts if len(p.strip()) > 3]


def _words(text, cjk):
    if cjk:
        return re.findall(r"[぀-ヿ一-鿿]|[A-Za-z0-9']+", text)
    return text.split()


def scan(text, keyword="", language="en", extra_banned=None):
    _, body = _split_frontmatter(text)
    blocks = [(k, _strip_md(t), n) for k, t, n in _blocks(body)]
    english = (language or "en").lower().startswith("en")
    cjk = (language or "").lower()[:2] in ("zh", "ja", "ko")
    hard, warn, info = [], [], []

    def find_terms(terms, label, regex=False, level=None):
        level = hard if level is None else level
        for k, t, n in blocks:
            for term in terms:
                pat = term if regex else r"(?<![\w-])" + re.escape(term.lower()) + r"(?![\w-])"
                targets = _sentences(t) if regex and term.startswith("^") else [t]
                for s in targets:
                    if re.search(pat, s.lower(), re.M):
                        shown = term.strip("^").replace("\\b", "")
                        level.append(f"line {n}: {label} '{shown}': {s[:110]}")
                        break

    if english:
        find_terms(HYPE, "hype word")
        find_terms(CORP_VERBS, "corporate verb")
        find_terms(PHRASES, "empty phrase")
        find_terms(HOOKS, "fake hook", regex=True)
        find_terms(UNSUPPORTED, "unsupported/over-claim", regex=True)
    if extra_banned:
        find_terms([x for x in extra_banned if x.strip()], "owner-banned phrase")

    for k, t, n in blocks:
        if "—" in t or " -- " in t:
            hard.append(f"line {n}: em dash: {t[:110]}")
        if re.search(r"\s–\s", t):
            hard.append(f"line {n}: en dash used as a dash: {t[:110]}")

    prose = [t for k, t, n in blocks if k in ("p", "li")]
    paras = [(t, n) for k, t, n in blocks if k == "p"]
    full = " ".join(prose)
    wc = len(_words(full, cjk))
    para_limit_hard, para_limit_warn = (220, 160) if cjk else (90, 70)

    if english:
        n_contr = len(CONTRACTION_RE.findall(full))
        n_unc = sum(len(re.findall(p, full, re.I)) for p in CONTRACTABLE)
        rate = wc / max(n_contr, 1)
        if wc > 300 and rate > 120:
            hard.append(f"contractions: only {n_contr} in {wc} words (1 per {rate:.0f}); aim for ~1 per 60-80")
        elif wc > 300 and rate > 80:
            warn.append(f"contractions: {n_contr} in {wc} words (1 per {rate:.0f}); aim for ~1 per 60-80")
        if n_unc > max(3, wc // 250):
            warn.append(f"{n_unc} uncontracted forms (do not, it is, you are...); contract most of them")

    for t, n in paras:
        w = len(_words(t, cjk))
        ns = len(_sentences(t))
        if w > para_limit_hard:
            hard.append(f"line {n}: paragraph of {w} words, split it")
        elif w > para_limit_warn or ns > 4:
            warn.append(f"line {n}: long paragraph ({w} words, {ns} sentences)")

    if english:
        hits = []
        for t, n in paras:
            for s in _sentences(t):
                first = s.lower().lstrip("\"'(")
                for wt in WEAK_TRANSITIONS:
                    if first.startswith(wt + ",") or first.startswith(wt + " "):
                        hits.append((n, wt))
        if len(hits) >= 3:
            hard.append(f"weak transitions used {len(hits)} times: " + ", ".join(f"{w} (l.{n})" for n, w in hits[:8]))
        else:
            warn += [f"line {n}: weak transition '{w}'" for n, w in hits]

        for t, n in paras:
            firsts = [s.split()[0].lower().strip("\"'(,") for s in _sentences(t) if s.split()]
            for w, cnt in Counter(firsts).items():
                if cnt >= 3:
                    hard.append(f"line {n}: {cnt} sentences in one paragraph start with '{w}'")
        all_firsts = [s.split()[0].lower().strip("\"'(,") for t in prose for s in _sentences(t) if s.split()]
        for i in range(len(all_firsts) - 2):
            if all_firsts[i] == all_firsts[i + 1] == all_firsts[i + 2] and all_firsts[i] not in ("the", "a"):
                warn.append(f"three consecutive sentences start with '{all_firsts[i]}'")
        if all_firsts:
            w, cnt = Counter(all_firsts).most_common(1)[0]
            if cnt / len(all_firsts) > 0.18 and cnt > 6:
                warn.append(f"'{w}' opens {cnt}/{len(all_firsts)} sentences ({cnt / len(all_firsts):.0%})")
        triplets = re.findall(r"\b(\w+), (\w+),? and (\w+)\b", full)
        if len(triplets) > max(4, wc // 300):
            warn.append(f"{len(triplets)} 'X, Y and Z' triplets; check for rule-of-three autopilot")

    exc = full.count("!") + full.count("！")
    if exc > 2:
        warn.append(f"{exc} exclamation marks")
    if EMOJI_RE.search(text):
        hard.append("emoji found")

    if keyword:
        kw = keyword.lower()
        cnt = full.lower().count(kw)
        kw_units = len(_words(kw, cjk)) or 1
        dens = cnt * kw_units / max(wc, 1) * 100
        msg = f"keyword '{keyword}': {cnt}x, density {dens:.1f}%"
        if dens > 2.5:
            hard.append(msg + " (stuffed, cut it back)")
        elif dens > 1.5:
            warn.append(msg + " (high)")
        else:
            info.append(msg)
        h1 = next((t for k, t, n in blocks if k == "h"), "")
        if kw not in h1.lower():
            warn.append("primary keyword not found verbatim in H1 (fine if a natural variant is used)")

    info.append(f"{wc} words of prose, {len(paras)} paragraphs")
    return {"passed": not hard, "hard_failures": hard, "warnings": warn, "info": info}


def format_report(res):
    lines = ["info: " + i for i in res["info"]]
    lines.append(f"\nHARD FAILURES ({len(res['hard_failures'])})")
    lines += ["  - " + h for h in res["hard_failures"]]
    lines.append(f"\nWARNINGS ({len(res['warnings'])})")
    lines += ["  - " + w for w in res["warnings"]]
    lines.append("\nRESULT: " + ("PASS (0 hard failures)" if res["passed"] else "FAIL (fix every hard failure)"))
    return "\n".join(lines) + "\n"
