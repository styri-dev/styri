"""Serve the built operator UI from the bridge itself (one container, one port)."""

from __future__ import annotations

import mimetypes
from http import HTTPStatus
from pathlib import Path

from websockets.datastructures import Headers
from websockets.http11 import Response

# Zero external requests: the page may only talk to this origin.
CSP = ("default-src 'self'; connect-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
       "font-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")

SECURITY_HEADERS = [
    ("Content-Security-Policy", CSP),
    ("X-Content-Type-Options", "nosniff"),
    ("Referrer-Policy", "no-referrer"),
]

_TYPES = {".js": "text/javascript", ".css": "text/css", ".svg": "image/svg+xml",
          ".woff2": "font/woff2", ".html": "text/html", ".json": "application/json"}


class StaticFiles:
    """Files from a Vite build. Unknown paths get index.html (client-side routing)."""

    def __init__(self, root: str | None):
        self.root = Path(root).resolve() if root else None
        self._cache: dict[Path, bytes] = {}

    def available(self) -> bool:
        return self.root is not None and (self.root / "index.html").is_file()

    def _read(self, path: Path) -> bytes:
        if path not in self._cache:  # the build never changes while we run
            self._cache[path] = path.read_bytes()
        return self._cache[path]

    def response(self, url_path: str) -> Response:
        if not self.available():
            return _plain(HTTPStatus.NOT_FOUND, "UI not built\n")
        rel = url_path.lstrip("/") or "index.html"
        target = (self.root / rel).resolve()
        if self.root not in target.parents and target != self.root:
            return _plain(HTTPStatus.NOT_FOUND, "not found\n")  # path traversal
        if not target.is_file():
            if "." in rel.rsplit("/", 1)[-1]:
                return _plain(HTTPStatus.NOT_FOUND, "not found\n")  # a missing asset, not a route
            target = self.root / "index.html"
        ctype = _TYPES.get(target.suffix) or mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype.endswith(("json", "javascript", "svg+xml")):
            ctype += "; charset=utf-8"
        hashed = target.parent.name == "assets"  # Vite fingerprints these
        headers = Headers([("Content-Type", ctype),
                           ("Cache-Control", "public, max-age=31536000, immutable" if hashed else "no-cache"),
                           *SECURITY_HEADERS])
        body = self._read(target)
        headers["Content-Length"] = str(len(body))
        return Response(HTTPStatus.OK.value, HTTPStatus.OK.phrase, headers, body)


def _plain(status: HTTPStatus, text: str) -> Response:
    body = text.encode()
    headers = Headers([("Content-Type", "text/plain; charset=utf-8"), ("Content-Length", str(len(body))),
                       *SECURITY_HEADERS])
    return Response(status.value, status.phrase, headers, body)
