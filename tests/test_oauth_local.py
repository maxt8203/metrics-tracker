import socket
import threading
import urllib.error
import urllib.request

import pytest

from tracker.sources.oauth_local import make_server, serve_until_code


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("localhost", 0))
        return s.getsockname()[1]


def _start(state="s3cret", timeout=5.0):
    port = _free_port()
    server, result = make_server(f"http://localhost:{port}/callback", state)
    out: dict = {}

    def run():
        try:
            out["code"] = serve_until_code(server, result, timeout)
        except RuntimeError as e:
            out["error"] = str(e)

    t = threading.Thread(target=run, daemon=True)
    t.start()
    return port, t, out


def _get(port, path):
    try:
        return urllib.request.urlopen(f"http://localhost:{port}{path}", timeout=5).status
    except urllib.error.HTTPError as e:
        return e.code


def test_stray_requests_do_not_end_login():
    port, t, out = _start()
    assert _get(port, "/favicon.ico") == 404
    assert _get(port, "/") == 404
    assert _get(port, "/callback?code=abc&state=s3cret") == 200
    t.join(5)
    assert out == {"code": "abc"}


def test_state_mismatch_is_an_error():
    port, t, out = _start()
    assert _get(port, "/callback?code=abc&state=wrong") == 400
    t.join(5)
    assert "state mismatch" in out["error"]


def test_provider_error_is_reported():
    port, t, out = _start()
    _get(port, "/callback?error=access_denied&state=s3cret")
    t.join(5)
    assert "access_denied" in out["error"]


def test_times_out_without_callback():
    port, t, out = _start(timeout=0.3)
    t.join(3)
    assert not t.is_alive() and "timed out" in out["error"]


def test_server_port_released_afterwards():
    port, t, out = _start()
    _get(port, "/callback?code=abc&state=s3cret")
    t.join(5)
    with socket.socket() as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("localhost", port))  # would raise if still bound


@pytest.mark.parametrize("timeout", [0, -1])
def test_non_positive_timeout_fails_fast(timeout):
    port, t, out = _start(timeout=timeout)
    t.join(2)
    assert "timed out" in out["error"]
