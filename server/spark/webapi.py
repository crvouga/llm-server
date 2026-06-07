"""Tiny JSON-over-HTTP client + the Cloudflare API error it raises."""

import json
import urllib.error
import urllib.request

from .console import die


class CloudflareAPIError(Exception):
    def __init__(self, code: int, message: str, body: str = ""):
        self.code = code
        self.message = message
        self.body = body
        super().__init__(f"HTTP {code}: {message}")


def _http_request(method: str, url: str, headers=None, data=None, timeout: int = 10):
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body, method=method)
    req.add_header("Content-Type", "application/json")
    if headers:
        for k, v in headers.items():
            req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        raw = e.read().decode(errors="replace")
        message = raw
        try:
            payload = json.loads(raw)
            errors = payload.get("errors") or []
            if errors:
                message = errors[0].get("message", raw)
        except json.JSONDecodeError:
            pass
        raise CloudflareAPIError(e.code, message, raw) from e
    except urllib.error.URLError as e:
        die(f"HTTP request failed for {url}: {e.reason}")


def http_get(url, headers=None):
    return _http_request("GET", url, headers=headers)


def http_post(url, data, headers=None):
    return _http_request("POST", url, headers=headers, data=data)


def http_put(url, data, headers=None):
    return _http_request("PUT", url, headers=headers, data=data)
