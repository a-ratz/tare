"""A fake model endpoint that keeps what the CLI sends.

The CLI under test is pointed at it: Claude Code with ANTHROPIC_BASE_URL (Anthropic
Messages API), Codex with `-c openai_base_url=...` (OpenAI Responses API). Every request
body is kept in memory; headers are never stored, so the login token never leaves the
request. Each turn is answered with the text "ok", so the CLI ends its loop at once.
"""
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def _messages_events(model: str) -> list[tuple[str, dict]]:
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


def _responses_events() -> list[tuple[str, dict]]:
    item = {"type": "message", "role": "assistant", "id": "msg_tare",
            "content": [{"type": "output_text", "text": "ok", "annotations": []}]}
    usage = {"input_tokens": 1, "input_tokens_details": {"cached_tokens": 0}, "output_tokens": 1,
             "output_tokens_details": {"reasoning_tokens": 0}, "total_tokens": 2}
    return [
        ("response.created", {"type": "response.created", "response": {"id": "resp_tare"}}),
        ("response.output_item.added", {"type": "response.output_item.added", "output_index": 0, "item": item}),
        ("response.output_text.delta", {"type": "response.output_text.delta", "item_id": "msg_tare",
                                        "output_index": 0, "content_index": 0, "delta": "ok"}),
        ("response.output_item.done", {"type": "response.output_item.done", "output_index": 0, "item": item}),
        ("response.completed", {"type": "response.completed", "response": {"id": "resp_tare", "usage": usage}}),
    ]


class _QuietServer(ThreadingHTTPServer):
    def handle_error(self, request, client_address):
        # The CLIs drop connections at will (a refused websocket, the end of a run);
        # that is not worth a traceback in the user's terminal.
        if not isinstance(sys.exc_info()[1], ConnectionError):
            super().handle_error(request, client_address)


class Fake:
    """Context manager: serves on a free port of 127.0.0.1 and collects request bodies."""

    def __init__(self):
        self.requests: list[dict] = []
        self.other_paths: list[str] = []
        fake = self

        class Handler(BaseHTTPRequestHandler):
            # HTTP/1.1, so a refused websocket upgrade reads as a plain 404 and Codex
            # falls back to HTTPS instead of retrying.
            protocol_version = "HTTP/1.1"

            def log_message(self, *args):
                pass

            def _json(self, status, payload):
                data = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _not_found(self):
                fake.other_paths.append(f"{self.command} {self.path.split('?')[0]}")
                self._json(404, {"type": "error", "error": {"type": "not_found_error", "message": "tare fake"}})

            def _stream(self, events):
                self.send_response(200)
                self.send_header("content-type", "text/event-stream")
                self.send_header("cache-control", "no-cache")
                self.send_header("connection", "close")
                self.end_headers()
                for name, data in events:
                    self.wfile.write(f"event: {name}\ndata: {json.dumps(data)}\n\n".encode())
                self.wfile.flush()
                self.close_connection = True

            def do_GET(self):
                self._not_found()

            def do_POST(self):
                raw = self.rfile.read(int(self.headers.get("content-length") or 0))
                path = self.path.split("?")[0]
                if path.endswith("/messages/count_tokens"):
                    return self._json(200, {"input_tokens": 1})
                if not path.endswith(("/v1/messages", "/responses")):
                    return self._not_found()
                if self.headers.get("content-encoding"):
                    # Codex compresses unless told not to (--disable enable_request_compression)
                    return self._json(415, {"error": {"message": "tare fake: send uncompressed bodies"}})
                body = json.loads(raw)
                fake.requests.append(body)
                if path.endswith("/responses"):
                    return self._stream(_responses_events())
                model = body.get("model", "fake")
                if body.get("stream"):
                    return self._stream(_messages_events(model))
                self._json(200, {"id": "msg_tare", "type": "message", "role": "assistant", "model": model,
                                 "content": [{"type": "text", "text": "ok"}], "stop_reason": "end_turn",
                                 "stop_sequence": None, "usage": {"input_tokens": 1, "output_tokens": 1}})

        self._server = _QuietServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self._server.server_address[1]}"

    def __enter__(self):
        threading.Thread(target=self._server.serve_forever, daemon=True).start()
        return self

    def __exit__(self, *exc):
        self._server.shutdown()
        self._server.server_close()
