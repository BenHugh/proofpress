# Publishing

The user chooses the target in the settings UI (Publishing tab). You only run it. Secrets are environment variables, never files; if one is missing, stop and tell the user which.

## Mode 1: new static site (`publish.mode = site`)

`build_site` / `proofpress build` rebuilds everything from `content/articles/*.md` into `public/`:

```
public/
├── index.html              # generated homepage, or static/index.html with the latest articles
│                           #   injected between PROOFPRESS:ARTICLES:START / END markers
├── <blog_path>/index.html  # all articles, newest first
├── <blog_path>/<slug>/index.html
├── images/<slug>.png       # hero / OG images (from static/images)
├── downloads/...           # files (from static/downloads)
├── assets/site.css         # brand colours from settings
├── sitemap.xml, robots.txt, 404.html, articles.json
└── _headers or vercel.json # cache rules for Cloudflare/Netlify or Vercel
```

Each article page gets `<title>`, meta description, canonical, Open Graph + Twitter card, Article + BreadcrumbList + FAQPage JSON-LD, the hero image, related articles and the site CTA. The build fails on broken internal links.

`publish` then builds and deploys with the chosen host:

| Host | What runs | Secret |
|---|---|---|
| none | build only; the user uploads `public/` | – |
| s3 | `aws s3 sync` (images cached a week, pages 5 minutes) + CloudFront invalidation | AWS CLI profile |
| cloudflare | `npx wrangler pages deploy public` | `CLOUDFLARE_API_TOKEN` |
| netlify | `npx netlify-cli deploy --prod` | `NETLIFY_AUTH_TOKEN` |
| vercel | `npx vercel deploy --prod` | `VERCEL_TOKEN` |
| git | copy `public/` into a repo folder, commit, push; the host deploys on push | git credentials |

## Mode 2: the user's existing site (`publish.mode = existing`)

`publish` sends every approved, not-yet-published article (or one `slug`):

- **markdown-repo**: writes `<content_dir>/<slug>.md` (or `<slug>/index.md`) with Astro, Hugo or plain frontmatter, copies the hero image into the repo's image folder, then git commit (and push if enabled). Internal links use `/<blog_path>/<slug>/`, so `blog_path` must match the user's site.
- **wordpress**: creates the post through the REST API (status from settings, `draft` by default so the user reviews it), uploads the hero as the featured image, and updates the same post on later runs instead of duplicating it.
- **webhook**: POSTs JSON (slug, title, meta_description, frontmatter, markdown, html, jsonld, hero image as base64) to the URL; header `X-ProofPress-Secret` if `PROOFPRESS_WEBHOOK_SECRET` is set.

## Order of operations

1. First time with a project: `publish` with `dry_run=true` and show the user the commands or requests.
2. Then `publish`.
3. Successful publishes set the backlog rows to `published` with today's date.
4. For a brand-new domain, remind the user to verify it in Google Search Console and submit `sitemap.xml` once.
