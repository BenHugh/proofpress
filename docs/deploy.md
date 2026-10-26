# Deploy guides

Pick the target in the settings page (Publishing tab), then press **Dry run** to see exactly what will happen. Secrets are environment variables: set them in the terminal that runs `proofpress` or your agent, e.g. in `~/.zshrc`:

```bash
export CLOUDFLARE_API_TOKEN=...
```

---

## New static site

### Cloudflare Pages

1. Create the project once: `npx wrangler pages project create my-site --production-branch=main` (or in the dashboard: Workers & Pages > Create > Pages > Direct Upload).
2. Create an API token: My Profile > API Tokens > Create Token > "Edit Cloudflare Workers" template, or a custom token with **Account > Cloudflare Pages > Edit**. `export CLOUDFLARE_API_TOKEN=...` (and `CLOUDFLARE_ACCOUNT_ID` if you have several accounts).
3. Settings: Host = Cloudflare Pages, project name = `my-site`.
4. Add your domain under the Pages project > Custom domains, and set Site URL in ProofPress to it.

The build writes `public/_headers` so images are cached for a week and pages for five minutes.

### Netlify

1. Create a site (Add new site > Deploy manually, drop any folder). Copy Site configuration > Site details > **Site ID**.
2. User settings > Applications > Personal access tokens > New token. `export NETLIFY_AUTH_TOKEN=...`
3. Settings: Host = Netlify, Site ID.

### Vercel

1. Account Settings > Tokens > Create. `export VERCEL_TOKEN=...`
2. Settings: Host = Vercel (team scope only if you deploy to a team).
3. The first deploy creates a project named after your site. Add your domain in that project's Settings > Domains.

### Git repo (any host that deploys on push)

Use this if Cloudflare Pages, Netlify, Vercel or GitHub Pages already watches a GitHub repo.

1. Clone the repo locally. Point the host at it with **no build command** and the output folder set to the repo root (or the subfolder you choose below).
2. Settings: Host = Git repo, local repo folder, optional subfolder (e.g. `docs` for GitHub Pages), branch, push on.
3. ProofPress copies `public/` in, commits and pushes. It keeps a `.proofpress-files` list and only ever deletes files it put there itself.

### AWS S3 + CloudFront

One-time setup:

1. **S3 bucket**: private (Block Public Access on). No static website hosting needed.
2. **ACM certificate** in **us-east-1** for `example.com` and `www.example.com`, DNS-validated.
3. **CloudFront distribution**: origin = the bucket through **Origin Access Control**; let CloudFront update the bucket policy. Redirect HTTP to HTTPS, add your domain names and the certificate, default root object `index.html`, compression on.
4. **CloudFront Function** (viewer request) so `/blog/post/` serves `index.html`:
   ```js
   function handler(event) {
     var req = event.request;
     var uri = req.uri;
     if (uri.endsWith('/')) { req.uri += 'index.html'; }
     else if (!uri.split('/').pop().includes('.')) { req.uri += '/index.html'; }
     return req;
   }
   ```
5. **Error pages**: 403 and 404 → `/404.html`, response code 404.
6. **DNS**: A/AAAA alias records for the apex and `www` pointing at the distribution (Route 53 or your DNS).
7. Settings: Host = S3, bucket, distribution ID, AWS CLI profile.

The deploy profile needs `s3:ListBucket`, `s3:PutObject`, `s3:DeleteObject` on the bucket and `cloudfront:CreateInvalidation` on the distribution. Images are uploaded with a one-week cache, everything else with five minutes, then `/*` is invalidated (the first 1,000 invalidation paths a month are free).

### None (build only)

`proofpress build` writes the whole site to `public/`. Upload that folder anywhere that serves static files.

---

## Existing site

### Markdown repo (Astro, Hugo, Next.js, Eleventy, Jekyll...)

Settings:

| Field | Astro blog template | Hugo |
|---|---|---|
| Content folder | `src/content/blog` | `content/blog` (or `content/posts`) |
| Frontmatter style | Astro | Hugo |
| File layout | `slug.md` | `slug.md` or `slug/index.md` |
| Image folder | `public/images/blog` | `static/images/blog` |
| Image URL prefix | `/images/blog` | `/images/blog` |

- Set **Blog path** (Site tab) to the URL path your site uses for posts, so internal links match.
- If your content collection has a strict schema (Astro `z.object(...)`), make sure it accepts the fields ProofPress writes, or choose "Keep ProofPress fields" and map them yourself. Astro templates that type `heroImage` as `image()` expect a relative file path; either loosen it to `z.string()` or leave the image folder empty.
- With **Git push** on, a host that deploys on push publishes the post. With it off, you review the commit first.

### WordPress

1. WordPress needs HTTPS and the REST API (on by default).
2. Users > Profile > **Application Passwords** > add one named "ProofPress". `export WP_APP_PASSWORD="xxxx xxxx xxxx xxxx xxxx xxxx"`
3. Settings: WordPress URL, username, post status (`draft` recommended).

Each article becomes a post with the same slug, excerpt = meta description, and the hero image as the featured image. Re-publishing updates the same post (ids are kept in `.proofpress/state.json`). Security plugins that block the REST API or Application Passwords need an exception.

### Webhook

POST, `Content-Type: application/json`, header `X-ProofPress-Secret` when `PROOFPRESS_WEBHOOK_SECRET` is set:

```json
{
  "event": "article.published",
  "site": "Leafnote",
  "slug": "how-to-make-a-plant-watering-schedule",
  "path": "/blog/how-to-make-a-plant-watering-schedule/",
  "title": "...", "h1": "...", "meta_description": "...",
  "frontmatter": { "primary_keyword": "...", "intent": "how-to", "...": "..." },
  "markdown": "...", "html": "...",
  "jsonld": [ { "@type": "Article" }, { "@type": "BreadcrumbList" }, { "@type": "FAQPage" } ],
  "hero_image_png_base64": "iVBORw0..."
}
```

Any 2xx response counts as published.
