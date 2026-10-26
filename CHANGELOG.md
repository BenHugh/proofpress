# Changelog

## Unreleased

- **Go live on AWS** tab: enter a domain, connect your AWS account once (access keys or a CLI profile), and ProofPress creates the S3 bucket, ACM certificate, CloudFront distribution and URL-rewrite function, DNS records (automatic in Route 53, listed for you elsewhere), writes the settings, uploads the site and checks it's live. Resumable and idempotent.
- **Secrets** tab: API keys and passwords stored locally in `.proofpress/secrets.json` (mode 600, git-ignored); environment variables still take priority.
- S3 publishing uses the AWS SDK (boto3) when available, so the AWS CLI is no longer required. Uploads only changed files.
- Installer now adds `~/.local/bin` to PATH in your shell profile (`~/.zshrc`, `~/.bash_profile` / `~/.bashrc`, or `~/.profile`) so the `proofpress` command works after install. Set `PROOFPRESS_NO_PROFILE=1` to skip.

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
