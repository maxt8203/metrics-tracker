"""One-shot localhost callback server for the first OAuth login."""

from __future__ import annotations

import secrets
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse


def _make_handler(path: str, state: str, result: dict[str, str]):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            url = urlparse(self.path)
            if url.path != path:  # e.g. /favicon.ico - ignore and keep waiting
                self.send_response(404)
                self.end_headers()
                return
            q = {k: v[0] for k, v in parse_qs(url.query).items()}
            ok = q.get("state") == state and "code" in q
            if ok:
                result["code"] = q["code"]
            else:
                result["error"] = q.get("error", "state mismatch or missing code")
            self.send_response(200 if ok else 400)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"Authorised. You can close this tab." if ok else b"Authorisation failed.")

        def log_message(self, *args):
            pass

    return Handler


def serve_until_code(server: HTTPServer, result: dict[str, str], timeout: float) -> str:
    """Handle requests until the callback sets a code or an error, or `timeout` elapses."""
    deadline = time.monotonic() + timeout
    try:
        while "code" not in result and "error" not in result:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            server.timeout = remaining
            server.handle_request()
    finally:
        server.server_close()
    if "code" not in result:
        raise RuntimeError(f"OAuth failed: {result.get('error', 'timed out')}")
    return result["code"]


def make_server(redirect_uri: str, state: str) -> tuple[HTTPServer, dict[str, str]]:
    parsed = urlparse(redirect_uri)
    result: dict[str, str] = {}
    handler = _make_handler(parsed.path or "/", state, result)
    return HTTPServer((parsed.hostname or "localhost", parsed.port or 80), handler), result


def capture_code(authorize_url: str, redirect_uri: str, state: str, timeout: float = 300) -> str:
    """Open the browser at `authorize_url` and wait for the redirect carrying `code`."""
    server, result = make_server(redirect_uri, state)
    print(f"Opening browser. If it doesn't open, visit:\n{authorize_url}")
    webbrowser.open(authorize_url)
    return serve_until_code(server, result, timeout)


def new_state() -> str:
    return secrets.token_urlsafe(24)
