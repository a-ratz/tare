import json
from pathlib import Path

import pytest

from tare import capsule as caps
from tare import judge


def test_score_is_read_from_a_stream_json_result_and_from_plain_text():
    stream = "\n".join(json.dumps(e) for e in [
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "Looking at page.png"}]}},
        {"type": "result", "result": '{"score": 72, "reason": "clean layout, one rounding bug"}'}])
    assert judge._score(stream) == (72, "clean layout, one rounding bug")
    assert judge._score('noise {"score": 40, "reason": "broken"} more') == (40, "broken")
    with pytest.raises(RuntimeError, match="no score"):
        judge._score('{"type": "result", "result": "I cannot score this"}')


def test_noise_flags_a_threshold_inside_a_pages_range_of_scores(monkeypatch, tmp_path):
    scores = {"good": iter([80, 84, 82]), "bad": iter([30, 45, 38])}
    monkeypatch.setattr(judge, "judge", lambda page, *a, **k: (next(scores[page.name]), ""))
    pages = [tmp_path / "good", tmp_path / "bad"]
    text, clear = judge.noise(pages, Path("r.md"), 3, threshold=60)
    assert clear and "outside every page's range of scores" in text
    scores.update(good=iter([80, 84, 82]), bad=iter([30, 65, 38]))
    text, clear = judge.noise(pages, Path("r.md"), 3, threshold=60)
    assert not clear and "<- threshold inside this page's range" in text


def test_check_detail_carries_the_checks_last_line(tmp_path):
    passed, detail = caps.run_check("echo 'score 72 (threshold 60): fine'", tmp_path)
    assert passed and detail == "check exit 0: score 72 (threshold 60): fine"
