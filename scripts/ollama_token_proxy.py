from __future__ import annotations

import os
import sys
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urljoin


TOKEN = os.getenv("OLLAMA_PROXY_TOKEN") or os.getenv("OPENAI_API_KEY") or ""
UPSTREAM = os.getenv("OLLAMA_UPSTREAM", "http://127.0.0.1:11434").rstrip("/")
HOST = os.getenv("OLLAMA_PROXY_HOST", "127.0.0.1")
PORT = int(os.getenv("OLLAMA_PROXY_PORT", "8080"))
TIMEOUT_SECONDS = int(os.getenv("OLLAMA_PROXY_TIMEOUT", "900"))

HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
    "host",
}


class OllamaTokenProxy(BaseHTTPRequestHandler):
    server_version = "OllamaTokenProxy/1.0"

    def _send_text(self, status: int, body: str) -> None:
        payload = body.encode("utf-8")
        self.send_response(status)
        self.send_header("content-type", "text/plain; charset=utf-8")
        self.send_header("content-length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _is_authorized(self) -> bool:
        if not TOKEN:
            return False
        expected = f"Bearer {TOKEN}"
        return self.headers.get("authorization", "") == expected

    def _proxy(self) -> None:
        if not self._is_authorized():
            self._send_text(401, "Unauthorized")
            return

        body = b""
        if self.command in {"POST", "PUT", "PATCH"}:
            length = int(self.headers.get("content-length", "0") or "0")
            body = self.rfile.read(length) if length > 0 else b""

        upstream_url = urljoin(f"{UPSTREAM}/", self.path.lstrip("/"))
        headers = {
            key: value
            for key, value in self.headers.items()
            if key.lower() not in HOP_BY_HOP_HEADERS
        }
        request = urllib.request.Request(
            upstream_url,
            data=body if self.command in {"POST", "PUT", "PATCH"} else None,
            headers=headers,
            method=self.command,
        )

        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
                response_body = response.read()
                self.send_response(response.status)
                for key, value in response.headers.items():
                    if key.lower() not in HOP_BY_HOP_HEADERS:
                        self.send_header(key, value)
                self.send_header("content-length", str(len(response_body)))
                self.end_headers()
                self.wfile.write(response_body)
        except urllib.error.HTTPError as exc:
            error_body = exc.read()
            self.send_response(exc.code)
            for key, value in exc.headers.items():
                if key.lower() not in HOP_BY_HOP_HEADERS:
                    self.send_header(key, value)
            self.send_header("content-length", str(len(error_body)))
            self.end_headers()
            self.wfile.write(error_body)
        except Exception as exc:
            self._send_text(502, f"Ollama upstream error: {type(exc).__name__}: {exc}")

    def do_GET(self) -> None:
        self._proxy()

    def do_POST(self) -> None:
        self._proxy()

    def log_message(self, fmt: str, *args: object) -> None:
        sys.stderr.write("[%s] %s\n" % (self.log_date_time_string(), fmt % args))


def main() -> None:
    if not TOKEN:
        raise SystemExit("Set OLLAMA_PROXY_TOKEN or OPENAI_API_KEY before starting the proxy.")
    server = ThreadingHTTPServer((HOST, PORT), OllamaTokenProxy)
    print(f"Ollama token proxy listening on http://{HOST}:{PORT}")
    print(f"Forwarding authorized requests to {UPSTREAM}")
    server.serve_forever()


if __name__ == "__main__":
    main()
