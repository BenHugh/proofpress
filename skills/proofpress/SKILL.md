---
name: proofpress
description: Fact-checked SEO article pipeline (ProofPress). Picks the next keyword from the user's backlog, works out search intent, researches, writes, fact-checks every product and YMYL claim against the user's own product definition and approved sources, runs anti-AI-slop passes, has an independent reviewer score it (rewrite until it passes or hand back), then draws a hero image and publishes to a new static site or the user's existing site (Markdown repo, WordPress, webhook). Use whenever the user asks to write, draft, publish, refresh or rewrite an SEO article or blog post, says "write the next article", "publish the approved articles", mentions ProofPress, their keyword backlog, or product definition, even if they don't name the skill.
---

# ProofPress: fact-checked SEO article pipeline

One keyword in, one published, genuinely useful article out. Search engines don't penalise content for being AI-written; they penalise content that isn't helpful, original and written for people. Every step below exists to catch a specific way AI articles fail: wrong topic, wrong intent, invented product features, invented facts, robotic prose. Don't skip steps to save time. A slower, true article beats a fast, wrong one.

## Where things are

**The project folder** belongs to the user and holds all state. Ask for its path once if it isn't obvious (check `$PROOFPRESS_PROJECT`, then the current folder for `proofpress.json`).

```
<project>/
├── proofpress.json          # all settings (edited in the settings UI)
├── backlog.csv              # keyword backlog: the ONLY source of topics
├── context/product.md       # what the product does and does NOT do  (read in full every run)
├── context/voice.md         # reader and tone                         (read every run)
├── context/factcheck.md     # claims to verify + approved sources     (read every run)
├── content/articles/<slug>.md   # approved articles
└── content/drafts/<slug>/   # brief.md, sources.md, draft-N.md, scan-N.txt, scorecard-N.md
```

**The tools.** Use whichever is available:
- **MCP tools** (server `proofpress`): `project_status`, `read_context`, `backlog_next`, `backlog_update`, `list_articles`, `save_draft_file`, `slop_scan`, `approve_article`, `make_hero_image`, `build_site`, `publish`, `get_instructions`.
- **CLI**: `proofpress <command> --project <dir>`. If `proofpress` isn't on PATH, it's at `../../cli/proofpress` relative to this SKILL.md (in a plugin install: `${CLAUDE_PLUGIN_ROOT}/cli/proofpress`).

**Settings are the user's job.** If something is missing (no product features, empty backlog, no site URL), don't invent it and don't edit `proofpress.json` yourself. Tell the user what's missing and to run `proofpress ui --project <dir>`, which opens the settings page where they fill in the product definition, keywords, voice, fact-check rules and publishing target.

Talk to the user in the language they use with you. Write the article in the site's language (`site.language` in settings; `context/voice.md` says it too).

## Pipeline at a glance

| Step | What happens | Gate |
|---|---|---|
| 0 | `project_status` | Any error → stop, tell the user what to fill in the UI |
| 1 | Pick keyword from backlog | No `todo` row → stop and ask the user |
| 2 | Search intent + SERP + cannibalisation check | Overlaps an existing article → stop, suggest updating it |
| 3 | Research + fact sheet | Unverifiable claim → it doesn't go in |
| 4 | Write draft | — |
| 5 | Scanner + two anti-slop passes | 0 hard failures |
| 6 | Independent scoring | Below pass mark or any hard fail → rewrite (max rewrites from settings), then hand back |
| 7 | Approve, hero image, publish | Publishing not configured → stop after approval |

Make a task list with these steps when the tooling supports it, so the user can follow along.

## Step 0: Check the project

Run `project_status` (`proofpress status`). Errors block the run: report them in plain words and stop. Warnings: mention the ones that affect this article (e.g. empty "does NOT exist" list, no CTA) and carry on. Read `context/product.md`, `context/voice.md` and `context/factcheck.md` in full now, and `read_context settings` for the pass mark and max rewrites.

## Step 1: Pick the keyword

- If the user named a keyword, use that row. If it isn't in the backlog, ask whether to add it (`backlog_add` only with their OK). Don't silently write off-backlog.
- Otherwise `backlog_next`: the highest-priority `todo` row (1 = highest, ties → first in file).
- **No `todo` row → stop.** Tell the user the backlog is empty and suggest a few candidate keywords for them to approve and add. Never pick a "nearby" topic yourself: that's how sites drift into thin, off-niche content.
- `backlog_update` the row to `status=drafting` (this fills the slug).

Rows that share a `cluster` are secondaries for one article, not separate articles.

## Step 2: Decide search intent

Read `references/intent-playbook.md` (or `get_instructions intent`).

1. **Look at the live SERP.** Web-search the exact keyword and skim the top results. What format ranks (listicle, template, official page, forum thread)? What do they all cover? What do they all miss? The gap is where this article earns its place.
2. **Pick one primary intent** and write down the one question the article must answer in its first 60 words.
3. **Cannibalisation check.** `list_articles`. If an existing article already serves the same intent, stop and tell the user; usually the right move is to update that article and add the keyword to its secondaries.
4. Save `brief.md`: keyword, secondaries, audience/country focus, intent, the one question, SERP observations, the information gain you'll add (worked example, downloadable file, decision table, honest limits), and the outline.

**Keywords that want a file** (template, checklist, spreadsheet, printable): the searcher wants the file. Make a real one (use the xlsx/pdf skills if available), save it under `<project>/static/downloads/`, set `download: /downloads/<file>` in the frontmatter, and make it the centrepiece.

## Step 3: Research and fact sheet

Every factual claim must trace back to one of three sources. Collect them in `sources.md` before writing.

**a) Product claims → `context/product.md` only.** Anything not listed under "What exists" doesn't exist. Respect tier and platform labels (Pro only, Android only, beta). Use only the official links listed there. Pricing: say exactly what the pricing line says, nothing more. If unsure whether something exists, leave it out or ask the user. Never fill a gap with "probably".

**b) Claims named in `context/factcheck.md` → approved sources, checked live during this run.** Read `references/fact-check.md`. Search and fetch the official page now; record claim, URL, page title, paraphrased wording and date checked. If you can't verify it today, it doesn't go in. If the site is YMYL, an unverified claim is a hard fail.

**c) Claims about other products (lists, comparisons) → their own website or store listing, fetched today.** Only what the listing says: features, price model, platforms, rating if shown, with the check date. No "I tested it" claims; nobody tested it. If a page can't be fetched, drop that claim or that product.

## Step 4: Write the draft

Follow `references/article-structure.md` exactly: frontmatter → H1 → short answer → longer answer → sections → product section → FAQ → `---` → CTA → last-reviewed line. Voice comes from `context/voice.md`. Use worked examples with obviously illustrative numbers rather than fake personal stories. Never invent anecdotes, testimonials, quotes, user counts, ratings or "our survey found" statistics.

Save as `draft-1.md` (then `draft-2.md`, `draft-3.md` on rewrites) with `save_draft_file` or straight into `content/drafts/<slug>/`.

## Step 5: Scanner and two anti-slop passes

Read `references/anti-slop.md`, then:

1. `slop_scan` the draft with the primary keyword (CLI: `proofpress scan <draft> --keyword "<kw>"`, save the output as `scan-N.txt`). It flags hype words, corporate verbs, empty phrases, fake hooks, over-claims, em/en dashes, weak transitions, repetitive openers, low contraction rate, long paragraphs, emoji, keyword stuffing and the owner's banned phrases.
2. **Pass 1 (obvious patterns):** fix every hard failure and whatever else the pass-1 list catches.
3. **Pass 2 (subtle signals):** read paragraph by paragraph: rhythm, openers, transitions, rule-of-three, section-ending summaries, symmetrical bullets. Rewrite sentences; don't just swap synonyms.
4. Re-scan until **0 hard failures**. Warnings need judgment, not blind compliance.

The English word lists only run for English sites; for other languages apply the same ideas by reading.

## Step 6: Score, then approve or revise

Score with `references/scoring-rubric.md`. **Use an independent reviewer** that didn't write the draft: a sub-agent if you can spawn one (give it the rubric, `context/product.md`, `context/factcheck.md`, `sources.md`, the brief and the draft, and ask for a scorecard only). Writers grade their own work too kindly. Save `scorecard-N.md`.

- **Any hard fail** → fails regardless of total.
- **Score ≥ pass mark and no hard fails** → approved: `approve_article` (`proofpress approve --slug <slug> --draft draft-N.md`).
- **Below pass mark** → back to step 4 with the scorecard's fixes, up to the max rewrites in settings (default 2). If the last draft still fails, stop: `backlog_update status=blocked`, and give the user the best draft, its scorecard and what's still wrong. Don't publish it.

Rewrites fix the specific weaknesses the scorecard names. Rewriting from scratch usually re-introduces old problems.

## Step 7: Hero image and publish

Read `references/publishing.md` for what each target does.

1. **Hero image:** `make_hero_image` (`proofpress hero --slug <slug>`). Write a real `hero_alt` in the frontmatter. If Pillow isn't installed, skip it and say so.
2. **Publish:** if the user hasn't published with this project before, do a dry run first (`publish dry_run=true` / `proofpress publish --dry-run`) and show them what will happen. Then `publish` (`proofpress publish`).
   - Static-site mode builds every page (sitemap, schema, internal links) and deploys with the chosen host. A broken internal link stops the build: fix the article.
   - Existing-site mode writes the article into their Markdown repo, WordPress (draft by default) or webhook.
   - If publishing isn't configured or a secret env var is missing, stop after approval and tell the user exactly what's missing. The article is safe in `content/articles/`.
3. The pipeline marks the backlog row `published`.

## What to tell the user at the end

Short, in their language: keyword and intent, final score (and how many rewrites), live URL or where it went (or "approved, not published: missing X"), claims you deliberately left out because they couldn't be verified, and the next `todo` keyword.

## Reference files

- `references/intent-playbook.md`: the intent types and what each must deliver.
- `references/article-structure.md`: the article skeleton, frontmatter, length, keyword use, links.
- `references/anti-slop.md`: pass 1 and pass 2 checklists.
- `references/scoring-rubric.md`: 100-point rubric and hard fails.
- `references/fact-check.md`: how to verify claims and cite them.
- `references/publishing.md`: build, deploy and existing-site targets.
