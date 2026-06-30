"""P12 Review Dashboard — minimal local backend (Python stdlib http.server).

Holds the Supabase service key SERVER-SIDE (via api.py -> supabase_client) and serves the
vanilla frontend + a small JSON API to localhost only. The browser never sees a credential
(SPEC-P12 Security, CLAUDE §6.5: stdlib only, no new framework).

Routes
  GET  /                         -> static/index.html
  GET  /static/<file>            -> static asset (html/css/js)
  GET  /fonts/<file>             -> embedded brand font (assets/fonts/*.ttf)
  GET  /api/select-queue         -> validated candidates + today's count vs the soft cap
  GET  /api/approve-queue        -> both-gates-passed products
  GET  /api/pdf?product_id=&kind=interior|cover -> stream the artifact (sandboxed to build/)
  POST /api/select               {product_id}
  POST /api/approve              {product_id}
  POST /api/reject               {product_id, reason}
  POST /api/edit                 {product_id, ...fields}
  POST /api/kdp-publish          {product_id, asin, listing_url?, price?, disclosure?}

CLI:  python -m pipeline.dashboard.server
"""

from __future__ import annotations

import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from pipeline.dashboard import api
from pipeline.lib import supabase_client

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
STATIC_DIR = (Path(__file__).resolve().parent / "static").resolve()
FONTS_DIR = (REPO_ROOT / "assets" / "fonts").resolve()

_CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".svg": "image/svg+xml",
    ".ttf": "font/ttf",
}


def _content_type(path: Path) -> str:
    return _CONTENT_TYPES.get(path.suffix.lower(), "application/octet-stream")


def _under(base: Path, target: Path) -> bool:
    """True if target resolves inside base — blocks path-traversal / arbitrary file reads."""
    try:
        target.relative_to(base)
        return True
    except ValueError:
        return False


class Handler(BaseHTTPRequestHandler):
    server_version = "P12Dashboard/1.0"
    cfg: dict = {}

    # --- low-level response helpers ---------------------------------------
    def _send_json(self, obj, status: int = 200) -> None:
        body = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_error_json(self, status: int, message: str) -> None:
        self._send_json({"error": message}, status=status)

    def _send_file(self, path: Path, content_type: str | None = None) -> None:
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type or _content_type(path))
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8")) or {}
        except json.JSONDecodeError:
            raise ValueError("request body is not valid JSON")

    def log_message(self, fmt, *args):  # quieter, single-line console
        sys.stderr.write("  %s - %s\n" % (self.address_string(), fmt % args))

    # --- GET ---------------------------------------------------------------
    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        route = parsed.path
        try:
            if route == "/" or route == "/index.html":
                return self._send_file(STATIC_DIR / "index.html")
            if route.startswith("/static/"):
                return self._serve_static(route[len("/static/"):])
            if route.startswith("/fonts/"):
                return self._serve_font(route[len("/fonts/"):])
            if route == "/api/select-queue":
                return self._send_json(api.select_queue(self.cfg))
            if route == "/api/approve-queue":
                return self._send_json(api.approve_queue(self.cfg))
            if route == "/api/pdf":
                return self._serve_artifact(parse_qs(parsed.query))
            self._send_error_json(404, f"no route {route}")
        except ValueError as exc:
            self._send_error_json(400, str(exc))
        except Exception as exc:  # noqa: BLE001 — surface a clean 500, never a stack to the browser
            self._send_error_json(500, f"{type(exc).__name__}: {exc}")

    def _serve_static(self, rel: str) -> None:
        target = (STATIC_DIR / rel).resolve()
        if not _under(STATIC_DIR, target) or not target.is_file():
            return self._send_error_json(404, "not found")
        self._send_file(target)

    def _serve_font(self, rel: str) -> None:
        target = (FONTS_DIR / rel).resolve()
        if not _under(FONTS_DIR, target) or not target.is_file():
            return self._send_error_json(404, "font not found")
        self._send_file(target)

    def _serve_artifact(self, qs: dict) -> None:
        """Stream a product's interior/cover artifact, sandboxed to build/ (no arbitrary reads)."""
        product_id = (qs.get("product_id") or [""])[0]
        kind = (qs.get("kind") or ["interior"])[0]
        if kind not in ("interior", "cover"):
            return self._send_error_json(400, "kind must be 'interior' or 'cover'")
        rows = supabase_client.select("products", {"id": product_id})
        if not rows:
            return self._send_error_json(404, "product not found")
        rel_path = rows[0].get("interior_path" if kind == "interior" else "cover_path")
        if not rel_path:
            return self._send_error_json(404, f"no {kind} artifact for this product")
        base = (REPO_ROOT / self.cfg.get("build_dir", "build")).resolve()
        target = (REPO_ROOT / rel_path).resolve()
        if not _under(base, target):
            return self._send_error_json(403, "artifact path outside the build sandbox")
        if not target.is_file():
            return self._send_error_json(404, "artifact file missing on disk")
        self._send_file(target)

    # --- POST --------------------------------------------------------------
    def do_POST(self) -> None:
        route = urlparse(self.path).path
        try:
            body = self._read_body()
            handler = {
                "/api/select": self._post_select,
                "/api/approve": self._post_approve,
                "/api/reject": self._post_reject,
                "/api/edit": self._post_edit,
                "/api/kdp-publish": self._post_kdp_publish,
            }.get(route)
            if handler is None:
                return self._send_error_json(404, f"no route {route}")
            self._send_json(handler(body))
        except ValueError as exc:
            self._send_error_json(400, str(exc))
        except Exception as exc:  # noqa: BLE001
            self._send_error_json(500, f"{type(exc).__name__}: {exc}")

    @staticmethod
    def _require(body: dict, key: str):
        val = body.get(key)
        if val is None or (isinstance(val, str) and not val.strip()):
            raise ValueError(f"missing required field: {key}")
        return val

    def _post_select(self, body: dict) -> dict:
        return api.do_select(self._require(body, "product_id"), self.cfg)

    def _post_approve(self, body: dict) -> dict:
        return api.do_approve(self._require(body, "product_id"), self.cfg)

    def _post_reject(self, body: dict) -> dict:
        return api.do_reject(self._require(body, "product_id"), body.get("reason", ""))

    def _post_edit(self, body: dict) -> dict:
        return api.do_edit(self._require(body, "product_id"), body.get("fields") or {}, self.cfg)

    def _post_kdp_publish(self, body: dict) -> dict:
        return api.mark_kdp_published(
            self._require(body, "product_id"),
            body.get("asin", ""),
            body.get("listing_url"),
            body.get("price"),
            body.get("disclosure"),
        )


def serve(cfg: dict | None = None) -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # Windows console defaults to cp1252
    except Exception:
        pass
    cfg = cfg or api.load_config()
    Handler.cfg = cfg
    host, port = cfg["host"], int(cfg["port"])
    httpd = ThreadingHTTPServer((host, port), Handler)
    print(f"P12 Review Dashboard -> http://{host}:{port}  (operator: {cfg['operator']})")
    print("  service key is server-side only; press Ctrl-C to stop.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped.")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    sys.path.insert(0, str(REPO_ROOT))
    serve()
