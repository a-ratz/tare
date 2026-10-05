"""A fake Anthropic Messages endpoint that keeps what the CLI sends.

The CLI under test is pointed at it with ANTHROPIC_BASE_URL. Every request body is
kept in memory; headers are never stored, so the login token never leaves the
request. Each turn is answered with the text "ok", so the CLI ends its loop at once.
"""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def _events(model: str) -> list[tuple[str, dict]]:
    message = {"id": "msg_tare", "type": "message", "role": "assistant", "model": model, "content": [],
               "stop_reason": None, "stop_sequence": None, "usage": {"input_tokens": 1, "output_tokens": 1}}
    return [
        ("message_start", {"type": "message_start", "message": message}),
        ("content_block_start", {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}}),
        ("content_block_delta", {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "ok"}}),
        ("content_block_stop", {"type": "content_block_stop", "index": 0}),
        ("message_delta", {"type": "message_delta", "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                           "usage": {"output_tokens": 1}}),
        ("message_stop", {"type": "message_stop"}),
    ]


class Fake:
    """Context manager: serves on a free port of 127.0.0.1 and collects request bodies."""

    def __init__(self):
        self.requests: list[dict] = []
        self.other_paths: list[str] = []
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _json(self, status, payload):
                data = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                fake.other_paths.append(f"GET {self.path}")
                self._json(404, {"type": "error", "error": {"type": "not_found_error", "message": "tare fake"}})

            def do_POST(self):
                raw = self.rfile.read(int(self.headers.get("content-length") or 0))
                path = self.path.split("?")[0]
                if path.endswith("/v1/messages/count_tokens"):
                    return self._json(200, {"input_tokens": 1})
                if not path.endswith("/v1/messages"):
                    fake.other_paths.append(f"POST {self.path}")
                    return self._json(404, {"type": "error", "error": {"type": "not_found_error", "message": "tare fake"}})
                body = json.loads(raw)
                fake.requests.append(body)
                model = body.get("model", "fake")
                if not body.get("stream"):
                    return self._json(200, {"id": "msg_tare", "type": "message", "role": "assistant", "model": model,
                                            "content": [{"type": "text", "text": "ok"}], "stop_reason": "end_turn",
                                            "stop_sequence": None, "usage": {"input_tokens": 1, "output_tokens": 1}})
                self.send_response(200)
                self.send_header("content-type", "text/event-stream")
                self.send_header("cache-control", "no-cache")
                self.end_headers()
                for name, data in _events(model):
                    self.wfile.write(f"event: {name}\ndata: {json.dumps(data)}\n\n".encode())
                self.wfile.flush()

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self._server.server_address[1]}"

    def __enter__(self):
        threading.Thread(target=self._server.serve_forever, daemon=True).start()
        return self

    def __exit__(self, *exc):
        self._server.shutdown()
        self._server.server_close()
