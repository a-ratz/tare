import http.client
import json
import urllib.error
import urllib.request
from urllib.parse import urlparse

import pytest

from tare.fake import FAKE_MODEL, Fake


def post(url, body, headers=None):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"content-type": "application/json", **(headers or {})})
    with urllib.request.urlopen(req) as resp:
        return resp.headers.get("content-type"), resp.read().decode()


def test_streamed_turn_is_answered_and_kept():
    with Fake() as fake:
        kind, text = post(f"{fake.url}/v1/messages", {"model": "m", "stream": True, "tools": [{"name": "Bash"}]})
    assert kind == "text/event-stream"
    events = [json.loads(line[6:]) for line in text.splitlines() if line.startswith("data: ")]
    assert [e["type"] for e in events][0] == "message_start" and events[-1]["type"] == "message_stop"
    assert any(e.get("delta", {}).get("text") == "ok" for e in events)
    assert fake.requests == [{"model": "m", "stream": True, "tools": [{"name": "Bash"}]}]


def test_plain_turn_and_count_tokens():
    with Fake() as fake:
        _, text = post(f"{fake.url}/v1/messages", {"model": "m"})
        _, count = post(f"{fake.url}/v1/messages/count_tokens", {"model": "m"})
    assert json.loads(text)["content"] == [{"type": "text", "text": "ok"}]
    assert json.loads(count) == {"input_tokens": 1}
    assert len(fake.requests) == 1


def test_headers_are_never_kept():
    with Fake() as fake:
        post(f"{fake.url}/v1/messages", {"model": "m"}, {"authorization": "Bearer secret-token"})
    assert "secret-token" not in json.dumps(fake.requests)


def test_unknown_paths_are_recorded_and_refused():
    with Fake() as fake:
        with pytest.raises(urllib.error.HTTPError) as err:
            urllib.request.urlopen(f"{fake.url}/api/hello")
    assert err.value.code == 404
    assert fake.other_paths == ["GET /api/hello"]


def test_cloud_code_answers_the_calls_around_a_turn_and_keeps_a_chunked_model_request():
    with Fake() as fake:
        host = urlparse(fake.url)
        conn = http.client.HTTPConnection(host.hostname, host.port)
        conn.request("POST", "/v1internal:loadCodeAssist", body=b'{"metadata": {}}',
                     headers={"content-type": "application/json"})
        assert json.loads(conn.getresponse().read())["currentTier"]["id"] == "free-tier"
        conn.request("POST", "/v1internal:fetchAvailableModels", body=b"{}")
        assert FAKE_MODEL in json.loads(conn.getresponse().read())["models"]
        conn.request("POST", "/v1internal:somethingNew", body=b"{}")
        assert json.loads(conn.getresponse().read()) == {}
        body = json.dumps({"model": FAKE_MODEL, "request": {"contents": [{"role": "user", "parts": [{"text": "hi"}]}]}})
        conn.request("POST", "/v1internal:streamGenerateContent?alt=sse", body=iter([body[:10].encode(), body[10:].encode()]),
                     headers={"transfer-encoding": "chunked"}, encode_chunked=True)
        reply = conn.getresponse().read().decode()
        assert reply.startswith("data: ") and json.loads(reply[6:])["response"]["candidates"][0]["content"]["parts"][0]["text"] == "ok"
    assert fake.requests == [json.loads(body)]
