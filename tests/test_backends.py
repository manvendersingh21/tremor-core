import io
import json

import pytest

from chimera_core.inference import local_draft
from chimera_core.inference.cloud_verifier import CrusoeBackend
from chimera_core.inference.local_draft import LlamaCppBackend, chatml


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass


def _fake_urlopen(payload, seen):
    def urlopen(req, timeout=None):
        seen.append((req.full_url, json.loads(req.data), dict(req.headers)))
        return _Resp(json.dumps(payload).encode())

    return urlopen


def test_llama_parses_current_server_shape_and_wraps_chatml(monkeypatch):
    payload = {"content": "Paris", "completion_probabilities": [
        {"id": 7, "token": "Paris", "logprob": -0.1,
         "top_logprobs": [{"id": 7, "logprob": -0.1}, {"id": 8, "logprob": -3.0}]}]}
    seen = []
    monkeypatch.setattr(local_draft.urllib.request, "urlopen", _fake_urlopen(payload, seen))
    r = LlamaCppBackend().complete("hi", 4, system="sys")
    assert r.text == "Paris" and r.token_ids == [7] and r.logprobs == [-0.1]
    assert 0.9 < r.mean_confidence < 0.91 and r.mean_entropy > 0
    assert seen[0][1]["prompt"] == chatml("hi", "sys")


def test_crusoe_records_usage_and_falls_back_to_reasoning(monkeypatch):
    from chimera_core.inference import cloud_verifier as cv

    payload = {"choices": [{"message": {"content": "", "reasoning_content": "thinking"}}],
               "usage": {"prompt_tokens": 10, "completion_tokens": 5, "reasoning_tokens": 5,
                         "prompt_tokens_details": {"cached_tokens": 3}}}
    seen = []
    monkeypatch.setattr(cv.urllib.request, "urlopen", _fake_urlopen(payload, seen))
    b = CrusoeBackend(api_key="k-test")
    assert b.complete("q") == "thinking"
    assert b.last_usage == {"prompt_tokens": 10, "completion_tokens": 5, "reasoning_tokens": 5, "cached_tokens": 3}
    assert seen[0][0].endswith("/v1/chat/completions")
    assert seen[0][1]["chat_template_kwargs"] == {"enable_thinking": False}


def test_crusoe_requires_key(monkeypatch):
    monkeypatch.delenv("CRUSOE_API_KEY", raising=False)
    with pytest.raises(RuntimeError):
        CrusoeBackend()


def test_ollama_counts_tokens_disables_think_and_strips_think_block(monkeypatch):
    from chimera_core.inference import cloud_verifier as cv

    payload = {"message": {"content": "<think>hmm</think>\nParis"}, "prompt_eval_count": 12,
               "eval_count": 3, "total_duration": 2_000_000_000, "load_duration": 1_500_000_000}
    seen = []
    monkeypatch.setattr(cv.urllib.request, "urlopen", _fake_urlopen(payload, seen))
    b = cv.OllamaBackend()
    assert b.complete("q", 64) == "Paris"
    assert b.last_usage["prompt_tokens"] == 12 and b.last_usage["completion_tokens"] == 3
    assert b.last_usage["load_duration_ms"] == 1500 and b.usage_log == [b.last_usage]
    assert seen[0][0] == "http://127.0.0.1:11435/api/chat"
    assert seen[0][1]["think"] is False and seen[0][1]["options"] == {"num_predict": 64}
