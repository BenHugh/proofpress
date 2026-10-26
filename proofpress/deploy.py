"""Static-site deploy providers. Input is always public/; only the upload step differs.

    s3          aws s3 sync + CloudFront invalidation          (AWS CLI profile)
    cloudflare  wrangler pages deploy                           (CLOUDFLARE_API_TOKEN)
    netlify     netlify deploy --prod                           (NETLIFY_AUTH_TOKEN)
    vercel      vercel deploy --prod                            (VERCEL_TOKEN)
    git         copy public/ into a repo, commit, push          (your git credentials)
                -> use this when Cloudflare Pages / Netlify / Vercel / GitHub Pages
                   is already connected to a GitHub repo and deploys on push.
"""
import os
import shlex
import shutil
import subprocess
from pathlib import Path

from .project import load, publish_readiness, require_project, slugify


class DeployError(Exception):
    pass


def _run(cmd, log, env=None, cwd=None, dry=False):
    masked = list(cmd)
    for i, a in enumerate(masked[:-1]):
        if a == "--token":
            masked[i + 1] = "********"
    shown = shlex.join(masked)
    log.append("$ " + shown)
    if dry:
        return ""
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, env=env, cwd=cwd)
    except FileNotFoundError:
        raise DeployError(f"command not found: {cmd[0]}")
    out = (res.stdout or "") + (res.stderr or "")
    log.append(out.strip()[-3000:])
    if res.returncode != 0:
        raise DeployError(f"'{shown}' failed (exit {res.returncode}). Output:\n{out.strip()[-1500:]}")
    return out


def _need(binary, hint):
    if not shutil.which(binary):
        raise DeployError(f"{binary} not found. {hint}")


def _need_env(var):
    if not os.environ.get(var):
        raise DeployError(f"{var} is not set: add it on the settings page (Secrets tab) or as an environment variable")


def s3(s, pub, log, dry, project=None):
    c = s["publish"]["s3"]
    try:
        import boto3  # noqa: F401
        have_sdk = True
    except ImportError:
        have_sdk = False
    from . import secrets
    keys_saved = bool(secrets.get(project, "AWS_ACCESS_KEY_ID")) if project else False
    if have_sdk and (c.get("credentials") == "profile" or keys_saved):
        from .aws import AwsError, s3_upload
        try:
            s3_upload(project, s, pub, log, dry)
        except AwsError as e:
            raise DeployError(str(e))
        except Exception as e:
            from .aws import _explain
            raise DeployError(_explain(e))
        return
    prof = c.get("aws_profile") or "default"
    if not dry:
        _need("aws", "Install the AWS CLI (brew install awscli) and run aws configure / aws sso login.")
        _run(["aws", "sts", "get-caller-identity", "--profile", prof], log)
    imgs = ["--exclude", "*", "--include", "*.png", "--include", "*.jpg", "--include", "*.jpeg", "--include", "*.webp", "--include", "*.svg"]
    not_imgs = ["--exclude", "*.png", "--exclude", "*.jpg", "--exclude", "*.jpeg", "--exclude", "*.webp", "--exclude", "*.svg"]
    _run(["aws", "s3", "sync", f"{pub}/", f"s3://{c['bucket']}/", "--profile", prof] + imgs + ["--cache-control", "public, max-age=604800"], log, dry=dry)
    _run(["aws", "s3", "sync", f"{pub}/", f"s3://{c['bucket']}/", "--profile", prof, "--delete"] + not_imgs + ["--cache-control", "public, max-age=300"], log, dry=dry)
    _run(["aws", "cloudfront", "create-invalidation", "--profile", prof, "--distribution-id", c["cloudfront_distribution_id"],
          "--paths", "/*", "--query", "Invalidation.Id", "--output", "text"], log, dry=dry)


def cloudflare(s, pub, log, dry):
    if not dry:
        _need("npx", "Install Node.js (it ships npx).")
        _need_env("CLOUDFLARE_API_TOKEN")
    name = s["publish"]["cloudflare"]["project_name"]
    _run(["npx", "--yes", "wrangler", "pages", "deploy", str(pub), f"--project-name={name}", "--branch=main", "--commit-dirty=true"], log, dry=dry)


def netlify(s, pub, log, dry):
    if not dry:
        _need("npx", "Install Node.js (it ships npx).")
        _need_env("NETLIFY_AUTH_TOKEN")
    _run(["npx", "--yes", "netlify-cli", "deploy", "--prod", f"--dir={pub}", f"--site={s['publish']['netlify']['site_id']}"], log, dry=dry)


def vercel(s, pub, r, log, dry):
    if not dry:
        _need("npx", "Install Node.js (it ships npx).")
        _need_env("VERCEL_TOKEN")
    # Vercel names a new project after the folder, so deploy from a folder named after the site.
    stage = r / ".proofpress/deploy" / slugify(s["site"].get("name") or "site")
    stage.mkdir(parents=True, exist_ok=True)
    for p in stage.iterdir():
        if p.name == ".vercel":
            continue
        shutil.rmtree(p) if p.is_dir() else p.unlink()
    for p in pub.iterdir():
        (shutil.copytree if p.is_dir() else shutil.copy2)(p, stage / p.name)
    cmd = ["npx", "--yes", "vercel", "deploy", str(stage), "--prod", "--yes", "--token", os.environ.get("VERCEL_TOKEN", "$VERCEL_TOKEN")]
    if s["publish"]["vercel"].get("scope"):
        cmd += ["--scope", s["publish"]["vercel"]["scope"]]
    _run(cmd, log, dry=dry)


MANIFEST = ".proofpress-files"


def git_static(s, pub, log, dry):
    c = s["publish"]["git"]
    repo = Path(c["repo_path"]).expanduser()
    if not (repo / ".git").exists():
        raise DeployError(f"{repo} is not a git repository")
    target = repo / c["subdir"].strip("/") if c.get("subdir") else repo
    target.mkdir(parents=True, exist_ok=True)
    old = set()
    mf = target / MANIFEST
    if mf.exists():
        old = set(x for x in mf.read_text(encoding="utf-8").splitlines() if x)
    new = sorted(p.relative_to(pub).as_posix() for p in pub.rglob("*") if p.is_file())
    log.append(f"copy {len(new)} files into {target} (removing {len(old - set(new))} files from the previous build only)")
    if not dry:
        for rel in old - set(new):
            f = target / rel
            if f.exists():
                f.unlink()
        for rel in new:
            dst = target / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(pub / rel, dst)
        mf.write_text("\n".join(new) + "\n", encoding="utf-8")
    _run(["git", "-C", str(repo), "add", "-A", str(target)], log, dry=dry)
    status = "" if dry else _run(["git", "-C", str(repo), "status", "--porcelain"], log)
    if status.strip() or dry:
        _run(["git", "-C", str(repo), "commit", "-m", "ProofPress: publish site"], log, dry=dry)
    else:
        log.append("nothing changed; no commit")
    if c.get("push", True):
        cmd = ["git", "-C", str(repo), "push"]
        if c.get("branch"):
            cmd += ["origin", c["branch"]]
        _run(cmd, log, dry=dry)


def deploy(project, dry_run=False):
    r = require_project(project)
    s = load(r)
    if s["publish"]["mode"] != "site":
        raise DeployError("publish.mode is 'existing'; use `proofpress publish` instead of deploy")
    prov = s["publish"]["site_provider"]
    ok, missing = publish_readiness(s)
    if prov == "none":
        raise DeployError("no deploy provider chosen (Settings > Publishing). The site is built in public/ and ready to upload by hand.")
    if not ok:
        raise DeployError("fill these settings first: " + ", ".join(missing))
    from . import secrets
    secrets.load_into_env(r)
    pub = r / "public"
    if not (pub / "index.html").exists():
        raise DeployError("public/ is empty; run `proofpress build` first")
    log = []
    if prov == "s3":
        s3(s, pub, log, dry_run, r)
    elif prov == "cloudflare":
        cloudflare(s, pub, log, dry_run)
    elif prov == "netlify":
        netlify(s, pub, log, dry_run)
    elif prov == "vercel":
        vercel(s, pub, r, log, dry_run)
    elif prov == "git":
        git_static(s, pub, log, dry_run)
    else:
        raise DeployError(f"unknown provider '{prov}'")
    return {"provider": prov, "dry_run": dry_run, "url": s["site"]["base_url"].rstrip("/") + "/", "log": log}
