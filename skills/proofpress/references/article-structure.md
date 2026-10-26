# Article structure

Every article follows this skeleton, in this order. It's designed so search engines can rank the page and AI answer engines can lift a clean answer and cite it.

## Frontmatter

```
---
title: Best Plant Watering Apps in 2026 (Free and Paid)
meta_description: Six plant watering apps compared on reminders, plant ID and price, plus when a simple calendar reminder is enough.
slug: best-plant-watering-app
primary_keyword: best plant watering app
secondary_keywords: plant watering reminder app, plant care app
intent: buying guide
cluster: apps
country: all
published: 2026-10-26
updated: 2026-10-26
hero_alt: Article cover reading Best Plant Watering Apps
download:
---
```

- `title`: contains the primary keyword (exact or a natural variant) near the start, ideally under 60 characters. A year only for buying guides and lists that will be refreshed.
- `meta_description`: 140 to 160 characters, a specific promise, no clickbait.
- `slug`: must match the slug in the backlog row.
- Plain `key: value` lines only (the parser is deliberately simple). Lists are comma-separated.
- `download`: optional path under `/downloads/` for file-intent articles; `download_label` optionally sets the button text.

## Body skeleton

```
# {Title}

{Short answer: 40 to 60 words. Directly answers the one question from the brief. No preamble, no "In this article".}

## The longer answer
{120 to 200 words. A self-contained explanation an AI engine could quote as-is: the key facts, the main options or steps, the most important caveat. Names things specifically.}

## {Section 1} ... ## {Section N}
{H2s that read like the questions people actually ask. H3s for sub-steps or individual items. Tables when comparing.}

## {Product section, e.g. "Where <Product> fits"}
{100 to 200 words. What the product does for this exact job, from context/product.md only. One honest limitation relevant to this topic.}

## FAQ
### {Question 1?}
{2 to 4 sentence answer.}
### {Question 2?}
...
{4 to 6 questions taken from People Also Ask / related searches. Don't repeat sections verbatim.}

---

{CTA: one or two sentences + the official link from context/product.md.}

*Last reviewed: {Month YYYY}. {Disclaimer from context/factcheck.md when the article touches those topics.}*
```

The `---` line after the FAQ matters: it tells the build where the last FAQ answer ends, so the CTA doesn't leak into the FAQ schema. It isn't rendered. The build turns the H1 into the page heading, the `## FAQ` H3s into FAQPage schema, and adds the hero image, breadcrumbs, related articles and the site CTA box automatically. Don't add those by hand.

For non-English sites, the FAQ heading can be `## 常见问题` or `## よくある質問`; the build recognises those too.

## Length

Length follows intent, not a word count target:
- How-to / definition: 900 to 1,500 words
- Buying guide / comparison: 1,500 to 2,500 words
- Template / list: 800 to 1,400 words plus the download

Stop when the question is fully answered. Padding hurts the "helpful" score.

## Keyword use

- Primary keyword: in the title, the short answer, one H2 if it reads naturally, and the meta description. That's enough. The scanner warns above about 1.5% density and fails above 2.5%.
- Secondaries and natural variants appear where they naturally fit.
- Never write a sentence just to hold a keyword.

## Links

- **Internal:** 2 to 4 links to existing articles from `list_articles` where genuinely relevant, as `/<blog_path>/<slug>/`, plus the homepage. Never link to articles that don't exist yet; the build adds related articles automatically as the site grows, and fails on broken internal links.
- **External:** an approved source for every claim that `context/factcheck.md` says must be verified (inline, descriptive anchor text). Competitors' own pages in lists.
- **Product:** only the official links in `context/product.md`, in the product section and CTA.

## Formatting

- Paragraphs: 1 to 3 sentences, rarely 4.
- Bullets for genuinely list-shaped content, not to chop prose.
- Tables in Markdown pipe syntax.
- No emoji, no em dashes, no bold on random phrases. Bold only for item names in a list or a single key warning.
