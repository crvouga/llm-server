"""Local reverse proxy: landing page on / and API forwarding to the engine port."""

from __future__ import annotations

import http.server
import socketserver
import threading
import urllib.error
import urllib.request

_server: socketserver.ThreadingTCPServer | None = None
_thread: threading.Thread | None = None

_LANDING_HTML = b"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>LLM Server</title>
  <style>
    body { font-family: system-ui, sans-serif; max-width: 40rem; margin: 3rem auto; line-height: 1.5; }
    code { background: #f4f4f5; padding: 0.1rem 0.35rem; border-radius: 0.25rem; }
  </style>
</head>
<body>
  <h1>LLM server is running</h1>
  <p>OpenAI-compatible API:</p>
  <ul>
    <li><a href="/v1/models"><code>/v1/models</code></a></li>
    <li><code>/v1/chat/completions</code></li>
  </ul>
</body>
</html>
"""


class _ProxyHandler(http.server.BaseHTTPRequestHandler):
    upstream: str = "http://127.0.0.1:18888"

    def log_message(self, format, *args):
        pass

    def _is_root(self) -> bool:
        return self.path.split("?", 1)[0] in ("", "/")

    def do_GET(self):
        if self._is_root():
            self._send_landing()
            return
        self._proxy()

    def do_HEAD(self):
        if self._is_root():
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(_LANDING_HTML)))
            self.end_headers()
            return
        self._proxy()

    def do_POST(self):
        self._proxy()

    def do_PUT(self):
        self._proxy()

    def do_PATCH(self):
        self._proxy()

    def do_DELETE(self):
        self._proxy()

    def do_OPTIONS(self):
        self._proxy()

    def _send_landing(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(_LANDING_HTML)))
        self.end_headers()
        self.wfile.write(_LANDING_HTML)

    def _proxy(self):
        url = self.upstream + self.path
        body = None
        if self.command in ("POST", "PUT", "PATCH"):
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length) if length else None

        req = urllib.request.Request(url, data=body, method=self.command)
        for header in self.headers:
            if header.lower() in ("host", "content-length"):
                continue
            req.add_header(header, self.headers[header])

        try:
            with urllib.request.urlopen(req, timeout=600) as resp:
                self.send_response(resp.status)
                for key, value in resp.headers.items():
                    if key.lower() in ("transfer-encoding", "connection"):
                        continue
                    self.send_header(key, value)
                self.end_headers()
                while chunk := resp.read(65536):
                    self.wfile.write(chunk)
        except urllib.error.HTTPError as exc:
            self.send_response(exc.code)
            for key, value in exc.headers.items():
                if key.lower() in ("transfer-encoding", "connection"):
                    continue
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(exc.read())
        except Exception:
            self.send_error(502, "upstream unavailable")


def start_local_proxy(listen_port: int, upstream_port: int, bind: str = "127.0.0.1") -> None:
    global _server, _thread
    stop_local_proxy()
    _ProxyHandler.upstream = f"http://127.0.0.1:{upstream_port}"
    _server = socketserver.ThreadingTCPServer((bind, listen_port), _ProxyHandler)
    _server.daemon_threads = True
    _thread = threading.Thread(
        target=_server.serve_forever, name="local-proxy", daemon=True
    )
    _thread.start()


def stop_local_proxy() -> None:
    global _server, _thread
    if _server is not None:
        _server.shutdown()
        _server.server_close()
        _server = None
    if _thread is not None:
        _thread.join(timeout=2)
        _thread = None
