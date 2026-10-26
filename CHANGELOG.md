# Changelog

## 0.1.0 (2026-10-26)

First public release.

- Settings UI (`proofpress ui`, English/中文): site and brand, product definition, keyword backlog with CSV import/export, audience and voice, fact-check rules, publishing target, quality gate.
- Agent skill with the full pipeline and reference playbooks (intent, structure, anti-slop, scoring rubric, fact-checking, publishing).
- MCP server (stdio, no dependencies) with 16 tools, including `get_instructions` for clients without skill support.
- Anti-slop scanner (English word lists plus language-independent structural checks).
- Static site build: Article, BreadcrumbList and FAQPage JSON-LD, sitemap, robots, related articles, broken-link check, hero / Open Graph images.
- Deploy to AWS S3 + CloudFront, Cloudflare Pages, Netlify, Vercel, or any git-connected host.
- Publish into an existing site: Markdown repo (Astro / Hugo / plain frontmatter), WordPress REST API, webhook.
- Fictional demo project ("Leafnote") and a smoke test that runs without network access.
