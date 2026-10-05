#!/usr/bin/env python3
"""Fake Anthropic Messages endpoint for the dirty-twin test (see PLAN.md).

Stores every request it receives, with credentials redacted, and answers so that the
real CLI runs its normal loop: the first main-loop turn gets one scripted Bash call
(reach check, names only), a turn that carries the tool result gets a plain "ok".

usage: uv run fake_model.py CAPTURE_DIR [--port 47811]
"""
import argparse
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REDACT = {"authorization", "x-api-key", "cookie", "proxy-authorization"}
REACH_ID = "toolu_tare_reach_01"


def reach_command(home: Path) -> str:
    # Readability and variable names only: the probe must never copy a secret.
    paths = [".claude/CLAUDE.md", ".claude/.credentials.json", ".claude.json",
             ".codex/auth.json", ".config/gh/hosts.yml", ".ssh"]
    checks = "; ".join(
        f'if test -r "{home / p}"; then echo "REACH {home / p}"; else echo "absent {home / p}"; fi'
        for p in paths)
    return checks + "; env | cut -d= -f1 | grep -iE 'token|key|secret|passw|auth' | sort | sed 's/^/ENV /'"


def has_tool_result(body: dict) -> bool:
    for msg in body.get("messages", []):
        content = msg.get("content")
        if isinstance(content, list) and any(b.get("type") == "tool_result" for b in content):
            return True
    return False


def offers_bash(body: dict) -> bool:
    return any(t.get("name") == "Bash" for t in body.get("tools", []))


class Fake(BaseHTTPRequestHandler):
    capture_dir: Path
    home: Path
    lock = threading.Lock()
    seq = 0

    def log_message(self, *args):
        pass

    def _store(self, body):
        with Fake.lock:
            Fake.seq += 1
            n = Fake.seq
        headers = {k.lower(): ("<redacted>" if k.lower() in REDACT else v) for k, v in self.headers.items()}
        name = f"{n:03d}-{self.command}-{self.path.split('?')[0].strip('/').replace('/', '_') or 'root'}.json"
        record = {"seq": n, "method": self.command, "path": self.path, "headers": headers, "body": body}
        (self.capture_dir / name).write_text(json.dumps(record, ensure_ascii=False, indent=1))
        return n

    def _json(self, status, payload):
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        n = self._store(None)
        print(f"[fake] {n:03d} GET {self.path} -> 404", file=sys.stderr, flush=True)
        self._json(404, {"type": "error", "error": {"type": "not_found_error", "message": "fake endpoint"}})

    def do_POST(self):
        raw = self.rfile.read(int(self.headers.get("content-length") or 0))
        try:
            body = json.loads(raw)
        except ValueError:
            body = {"_raw": raw.decode(errors="replace")}
        n = self._store(body)
        path = self.path.split("?")[0]

        if path.endswith("/v1/messages/count_tokens"):
            print(f"[fake] {n:03d} count_tokens", file=sys.stderr, flush=True)
            return self._json(200, {"input_tokens": 1})
        if not path.endswith("/v1/messages"):
            print(f"[fake] {n:03d} POST {self.path} -> 404", file=sys.stderr, flush=True)
            return self._json(404, {"type": "error", "error": {"type": "not_found_error", "message": "fake endpoint"}})

        if offers_bash(body) and not has_tool_result(body):
            blocks = [{"type": "tool_use", "id": REACH_ID, "name": "Bash",
                       "input": {"command": reach_command(self.home), "description": "tare reach probe"}}]
            stop, kind = "tool_use", "reach call"
        else:
            blocks, stop, kind = [{"type": "text", "text": "ok"}], "end_turn", "ok"
        print(f"[fake] {n:03d} messages tools={len(body.get('tools', []))} stream={bool(body.get('stream'))} -> {kind}",
              file=sys.stderr, flush=True)

        model = body.get("model", "fake")
        msg_id = f"msg_tare_{n:03d}"
        if not body.get("stream"):
            return self._json(200, {"id": msg_id, "type": "message", "role": "assistant", "model": model,
                                    "content": blocks, "stop_reason": stop, "stop_sequence": None,
                                    "usage": {"input_tokens": 1, "output_tokens": 1}})

        events = [("message_start", {"type": "message_start", "message": {
            "id": msg_id, "type": "message", "role": "assistant", "model": model, "content": [],
            "stop_reason": None, "stop_sequence": None, "usage": {"input_tokens": 1, "output_tokens": 1}}})]
        for i, b in enumerate(blocks):
            if b["type"] == "text":
                start = {"type": "text", "text": ""}
                delta = {"type": "text_delta", "text": b["text"]}
            else:
                start = {"type": "tool_use", "id": b["id"], "name": b["name"], "input": {}}
                delta = {"type": "input_json_delta", "partial_json": json.dumps(b["input"])}
            events += [("content_block_start", {"type": "content_block_start", "index": i, "content_block": start}),
                       ("content_block_delta", {"type": "content_block_delta", "index": i, "delta": delta}),
                       ("content_block_stop", {"type": "content_block_stop", "index": i})]
        events += [("message_delta", {"type": "message_delta", "delta": {"stop_reason": stop, "stop_sequence": None},
                                      "usage": {"output_tokens": 1}}),
                   ("message_stop", {"type": "message_stop"})]
        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.send_header("cache-control", "no-cache")
        self.end_headers()
        for name, data in events:
            self.wfile.write(f"event: {name}\ndata: {json.dumps(data)}\n\n".encode())
        self.wfile.flush()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("capture_dir", type=Path)
    ap.add_argument("--port", type=int, default=47811)
    args = ap.parse_args()
    args.capture_dir.mkdir(parents=True, exist_ok=True)
    Fake.capture_dir = args.capture_dir
    Fake.home = Path.home()  # the fake runs outside the room, as the real user
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Fake)
    print(f"[fake] listening on 127.0.0.1:{args.port}, capturing to {args.capture_dir}", file=sys.stderr, flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
