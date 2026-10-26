"""Local secrets: API keys and passwords entered in the settings page.

Stored in <project>/.proofpress/secrets.json with file mode 600, inside a folder that
carries its own .gitignore ("*"), so they are never committed even if the project
folder is a git repo. Environment variables always win over the file.
"""
import json
import os
from pathlib import Path

from .project import root

_INJECTED = set()  # keys this process copied from the file into os.environ

KNOWN = {
    "AWS_ACCESS_KEY_ID": "AWS access key ID",
    "AWS_SECRET_ACCESS_KEY": "AWS secret access key",
    "CLOUDFLARE_API_TOKEN": "Cloudflare API token",
    "CLOUDFLARE_ACCOUNT_ID": "Cloudflare account ID (only if you have several)",
    "NETLIFY_AUTH_TOKEN": "Netlify personal access token",
    "VERCEL_TOKEN": "Vercel token",
    "WP_APP_PASSWORD": "WordPress application password",
    "PROOFPRESS_WEBHOOK_SECRET": "Webhook shared secret",
}


def _path(project):
    d = root(project) / ".proofpress"
    d.mkdir(parents=True, exist_ok=True)
    gi = d / ".gitignore"
    if not gi.exists():
        gi.write_text("*\n", encoding="utf-8")
    return d / "secrets.json"


def _read(project):
    p = _path(project)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except ValueError:
            return {}
    return {}


def get(project, key):
    if os.environ.get(key) and key not in _INJECTED:
        return os.environ[key]
    return _read(project).get(key) or None


def set_many(project, values):
    """values: {KEY: "new value" | "" (delete)}. Unknown keys are refused."""
    data = _read(project)
    for k, v in values.items():
        if k not in KNOWN:
            raise ValueError(f"unknown secret {k}")
        v = (v or "").strip()
        if k in _INJECTED:
            os.environ.pop(k, None)
            _INJECTED.discard(k)
        if v:
            data[k] = v
        else:
            data.pop(k, None)
    p = _path(project)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    tmp.replace(p)
    return masked(project)


def _mask(v):
    if not v:
        return ""
    if len(v) <= 8:
        return "•" * len(v)
    return v[:4] + "•" * 6 + v[-4:]


def masked(project):
    data = _read(project)
    out = {}
    for k, label in KNOWN.items():
        if os.environ.get(k) and k not in _INJECTED:
            out[k] = {"label": label, "set": True, "source": "environment", "preview": _mask(os.environ[k])}
        elif data.get(k):
            out[k] = {"label": label, "set": True, "source": "settings page", "preview": _mask(data[k])}
        else:
            out[k] = {"label": label, "set": False, "source": "", "preview": ""}
    return out


def env_with_secrets(project):
    """os.environ plus every stored secret not already set, for subprocesses (npx wrangler, etc.)."""
    env = dict(os.environ)
    for k, v in _read(project).items():
        if k in KNOWN and v and not env.get(k):
            env[k] = v
    return env


def load_into_env(project):
    """Make saved secrets visible to this process (env vars set by the user still win)."""
    for k, v in _read(project).items():
        if k in KNOWN and v and (not os.environ.get(k) or k in _INJECTED):
            os.environ[k] = v
            _INJECTED.add(k)


def path_for_docs(project):
    return str(Path(_path(project)))
