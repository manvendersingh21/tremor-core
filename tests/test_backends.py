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


def test_spec_backend_verifies_in_one_request_and_serves_correction_from_it(monkeypatch):
    import random

    from chimera_core.inference import cloud_verifier as cv

    # target logprobs: token 1 certain, token 2 impossible -> reject at position 1.
    payload = {"logprobs": [0.0, -50.0, 0.0], "next_ids": [11, 22, 33, 44]}
    seen = []
    monkeypatch.setattr(cv.urllib.request, "urlopen", _fake_urlopen(payload, seen))
    b = cv.SpecVerifierBackend()
    res = cv.CloudVerifier(b, random.Random(0)).verify([5, 6], [1, 2, 3], [-0.1, -0.1, -0.1])
    assert res.accepted_ids == [1] and res.correction_id == 22
    assert len(seen) == 1 and seen[0][0].endswith("/verify")
    assert seen[0][1]["prompt_ids"] == [5, 6] and b.bytes_up > 0 and b.bytes_down > 0


def test_router_verify_encodes_chatml_prompt_for_chatml_draft(monkeypatch):
    from chimera_core.inference import cloud_verifier as cv
    from chimera_core.inference.local_draft import DraftResult
    from chimera_core.router import SpeculativeCascadeRouter

    class Local:
        chatml = True

        def complete(self, prompt, max_tokens, system=None):
            return DraftResult(text="x", token_ids=[1, 2], logprobs=[-1.0, -1.0], mean_confidence=0.3)

    class Tok:
        def __init__(self):
            self.encoded = []

        def encode(self, text):
            self.encoded.append(text)
            return [9]

        def decode(self, ids):
            return str(ids)

    monkeypatch.setattr(cv.urllib.request, "urlopen",
                        _fake_urlopen({"logprobs": [0.0, 0.0], "next_ids": [7, 8, 9]}, []))
    tok = Tok()
    r = SpeculativeCascadeRouter(Local(), cv.CloudVerifier(cv.SpecVerifierBackend()), tokenizer=tok)
    out = r.generate("hi")
    assert tok.encoded[0].startswith("<|im_start|>user\nhi") and out.telemetry.tier_used == "cloud_verified"
