"""Local settings page: `proofpress ui`.

Standard library only. Binds to 127.0.0.1, checks the Host header and requires a
per-run token on every API call, so other sites in your browser can't talk to it.
"""
import json
import secrets
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from . import __version__
from . import articles, backlog as bl, project as pj
from . import secrets as pp_secrets

HERE = Path(__file__).resolve().parent


def make_handler(project_dir, token, port):
    allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}

    class H(BaseHTTPRequestHandler):
        server_version = "ProofPress/" + __version__

        def log_message(self, fmt, *args):
            pass

        def _send(self, code, body, ctype="application/json; charset=utf-8", extra=None):
            data = body if isinstance(body, bytes) else body.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(data)

        def _json(self, code, obj):
            self._send(code, json.dumps(obj, ensure_ascii=False))

        def _guard(self, api=True):
            if self.headers.get("Host") not in allowed_hosts:
                self._send(403, "forbidden host", "text/plain")
                return False
            if api and self.headers.get("X-ProofPress-Token") != token:
                self._send(403, "bad token", "text/plain")
                return False
            return True

        def _body(self):
            n = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(n) if n else b"{}"
            return json.loads(raw.decode("utf-8") or "{}")

        def _state(self):
            s = pj.load(project_dir)
            try:
                rows = bl.read(project_dir)
                bl_err = None
            except bl.BacklogError as e:
                rows, bl_err = [], str(e)
            nxt = None
            try:
                nxt = bl.next_todo(project_dir)
            except bl.BacklogError:
                pass
            return {
                "project": str(project_dir),
                "version": __version__,
                "settings": s,
                "backlog": rows,
                "backlog_error": bl_err,
                "next": nxt,
                "validation": pj.validate(project_dir),
                "articles": articles.list_articles(project_dir),
                "secrets": pp_secrets.masked(project_dir),
                "meta": {
                    "statuses": bl.STATUSES, "intents": bl.INTENTS,
                    "providers": pj.SITE_PROVIDERS, "targets": pj.EXISTING_TARGETS,
                    "secret_env": pj.SECRET_ENV, "columns": bl.COLUMNS,
                },
            }

        def do_GET(self):
            path = urlparse(self.path).path
            if path in ("/", "/index.html"):
                if not self._guard(api=False):
                    return
                html = (HERE / "ui/index.html").read_text(encoding="utf-8").replace("__PP_TOKEN__", token)
                self._send(200, html, "text/html; charset=utf-8",
                           {"Content-Security-Policy": "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; img-src 'self' data:"})
                return
            if not self._guard():
                return
            try:
                if path == "/api/state":
                    self._json(200, self._state())
                elif path == "/api/aws/state":
                    self._json(200, aws_state(project_dir))
                elif path == "/api/backlog.csv":
                    self._send(200, bl.to_text(bl.read(project_dir)), "text/csv; charset=utf-8",
                               {"Content-Disposition": 'attachment; filename="backlog.csv"'})
                elif path.startswith("/api/context/"):
                    name = path.rsplit("/", 1)[-1]
                    if name not in ("product.md", "voice.md", "factcheck.md"):
                        self._json(404, {"error": "unknown file"})
                        return
                    p = pj.root(project_dir) / "context" / name
                    self._send(200, p.read_text(encoding="utf-8") if p.exists() else "", "text/plain; charset=utf-8")
                else:
                    self._json(404, {"error": "not found"})
            except Exception as e:
                self._json(500, {"error": str(e)})

        def do_POST(self):
            if not self._guard():
                return
            path = urlparse(self.path).path
            try:
                body = self._body()
                if path == "/api/settings":
                    pj.save(project_dir, body["settings"])
                    if "backlog" in body:
                        bl.write(project_dir, body["backlog"])
                    self._json(200, self._state())
                elif path == "/api/backlog/parse":
                    self._json(200, {"rows": bl.parse_text(body.get("csv", ""))})
                elif path == "/api/action":
                    self._json(200, run_action(project_dir, body.get("action"), body.get("slug")))
                elif path == "/api/secrets":
                    self._json(200, {"secrets": pp_secrets.set_many(project_dir, body.get("values") or {})})
                elif path.startswith("/api/aws/"):
                    self._json(200, aws_action(project_dir, path.rsplit("/", 1)[-1], body))
                else:
                    self._json(404, {"error": "not found"})
            except (bl.BacklogError, pj.ProjectError, KeyError, ValueError) as e:
                self._json(400, {"error": str(e)})
            except Exception as e:
                self._json(500, {"error": f"{type(e).__name__}: {e}"})

    return H


def aws_state(project_dir):
    from . import aws
    try:
        import boto3  # noqa: F401
        sdk = True
    except ImportError:
        sdk = False
    st = aws.public_state(project_dir)
    st["sdk"] = sdk
    st["profiles"] = aws.list_profiles() if sdk else []
    st["policy"] = json.dumps(aws.POLICY, indent=2)
    return st


def aws_action(project_dir, action, body):
    from . import aws
    try:
        if action == "test":
            return {"ok": True, "identity": aws.identity(project_dir)}
        if action == "check-domain":
            return {"ok": True, **aws.check_domain(project_dir, body.get("domain", ""))}
        if action == "start":
            return {"ok": True, "state": aws.start(project_dir, body.get("domain"), body.get("region"))}
        if action == "stop":
            return {"ok": True, "state": aws.stop(project_dir)}
        if action == "reset":
            return {"ok": True, "state": aws.reset(project_dir)}
    except aws.AwsError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": aws._explain(e)}
    raise ValueError(f"unknown action {action}")


def run_action(project_dir, action, slug=None):
    if action == "build":
        from .build import build
        res = build(project_dir)
        return {"ok": not res["broken_links"], "log": [f"built {len(res['articles'])} article(s) into {res['public']}"]
                + res["articles"] + (["BROKEN LINKS:"] + res["broken_links"] if res["broken_links"] else [])}
    if action in ("publish", "publish-dry"):
        from .publish import publish
        try:
            res = publish(project_dir, slug=slug or None, dry_run=(action == "publish-dry"))
        except Exception as e:
            return {"ok": False, "log": [str(e)]}
        lines = [x for x in res.get("log", []) if x]
        for k in ("message", "url"):
            if res.get(k):
                lines.append(res[k])
        if res.get("published"):
            lines.append("published: " + ", ".join(res["published"]))
        return {"ok": True, "log": lines}
    if action == "hero":
        from .hero import make
        return {"ok": True, "log": [make(project_dir, slug)]}
    raise ValueError(f"unknown action {action}")


def serve(project, port=8765, open_browser=True):
    r = pj.root(project)
    if not (r / pj.SETTINGS_FILE).exists():
        pj.init(r)
        print(f"created a new ProofPress project at {r}")
    token = secrets.token_urlsafe(24)
    httpd = None
    for p in range(port, port + 20):
        try:
            httpd = ThreadingHTTPServer(("127.0.0.1", p), make_handler(r, token, p))
            port = p
            break
        except OSError:
            continue
    if not httpd:
        raise SystemExit("no free port found")
    url = f"http://127.0.0.1:{port}/"
    print(f"ProofPress settings for {r}\n  {url}\n(Ctrl+C to stop)")
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
