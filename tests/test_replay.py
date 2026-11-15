"""apps/replay: log parsing and the estimate math. Offline: no models, no network."""
import csv
import json

import pytest

from apps.replay import estimate, logs, prices, report


def test_jsonl_formats_and_skips(tmp_path):
    p = tmp_path / "l.jsonl"
    rows = [
        {"messages": [{"role": "system", "content": "be brief"}, {"role": "user", "content": "hi"}], "model": "m",
         "usage": {"prompt_tokens": 12, "completion_tokens": 5}},
        {"custom_id": "b", "body": {"model": "m2", "messages": [{"role": "user", "content": [{"type": "text", "text": "part"}]}]},
         "response": {"body": {"usage": {"prompt_tokens": 3, "completion_tokens": 4}}}},
        {"messages": [{"role": "system", "content": "only system"}]},
    ]
    p.write_text("\n".join(json.dumps(r) for r in rows) + "\nnot json\n")
    reqs, skipped = logs.load(p)
    assert [r.prompt for r in reqs] == ["hi", "part"]
    assert (reqs[0].tokens_in, reqs[0].tokens_out, reqs[0].sys_chars) == (12, 5, 8)
    assert (reqs[1].id, reqs[1].tokens_in, reqs[1].tokens_out) == ("b", 3, 4)
    assert skipped == 2


def test_multi_turn_prompt_keeps_history():
    prompt, _ = logs.render([{"role": "user", "content": "a"}, {"role": "assistant", "content": "b"}, {"role": "user", "content": "c"}])
    assert prompt == "user: a\nassistant: b\nuser: c"


def test_csv_and_sample(tmp_path):
    p = tmp_path / "l.csv"
    with open(p, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["prompt", "model", "prompt_tokens", "completion_tokens"])
        for i in range(10):
            w.writerow([f"q{i}", "gpt", 10, ""])
    reqs, _ = logs.load(p)
    assert len(reqs) == 10 and reqs[0].tokens_in == 10 and reqs[0].tokens_out is None
    a, _ = logs.load(p, sample=4, seed=1)
    b, _ = logs.load(p, sample=4, seed=1)
    assert [r.id for r in a] == [r.id for r in b] and len(a) == 4


def test_classify_without_embeddings():
    reqs = [logs.Req(str(i), t) for i, t in enumerate([
        "What is the capital of France?", "what is the  capital of france?", "Write a python function that reverses a string",
        "x" * 3000, "Tell me about " + "the history of Rome " * 20])]
    assert estimate.classify(reqs) == ["lookup", "repeat", "easy_code", "hard", "general"]


def test_near_repeat_needs_cosine_and_guard():
    reqs = [logs.Req("0", "add 2 and 3"), logs.Req("1", "add 2 and 4"), logs.Req("2", "sum of 2 and 3 please")]
    vec = {"add 2 and 3": [1, 0], "add 2 and 4": [1, 0.001], "sum of 2 and 3 please": [0, 1]}
    got = estimate.classify(reqs, lambda t: vec[t])
    assert got[1] != "near_repeat"  # cosine ~1 but the guard sees 3 vs 4
    assert got[2] != "near_repeat"  # below the threshold
    assert estimate.classify([logs.Req("0", "add 2 and 3"), logs.Req("1", "Add 2 and 3 ")], lambda t: [1, 0])[1] == "repeat"


def test_estimate_math():
    rates = {"p30": {"lookup": 0.75, "hard": 0.0}, "agree": 0.8, "wrong_hit": 0.1, "out_tokens": 100, "source": "t"}
    reqs = [logs.Req("a", "q" * 400, tokens_in=1000, tokens_out=1000), logs.Req("b", "q" * 400, tokens_in=1000, tokens_out=1000),
            logs.Req("c", "z" * 400)]
    rows = estimate.project_rows(reqs, ["lookup", "near_repeat", "hard"], rates)
    assert rows[0]["top_frac"] == pytest.approx(0.25)
    assert rows[1]["ladder_usd"] == 0 and rows[1]["wrong_hit"] == 0.1
    assert rows[2]["tin"] == 100 and rows[2]["tout"] == 100 and rows[2]["est_tokens"]
    assert rows[0]["bad_answer"] == pytest.approx(0.75 * 0.2)
    s = estimate.summarize(rows, "gpt-5.5-class", volume_per_month=1000)
    base = prices.usd(1000, 1000, prices.PRICES["gpt-5.5-class"]) * 2 + prices.usd(100, 100, prices.PRICES["gpt-5.5-class"])
    assert s["baseline_usd"] == pytest.approx(base)
    top = 0.25 * prices.usd(1000, 1000, prices.TOP) + prices.usd(100, 100, prices.TOP)
    assert s["ladder_usd"] == pytest.approx(top)
    assert s["per_1k"]["ladder_usd"] == pytest.approx(top * 1000 / 3)
    mo = s["monthly"]
    assert mo["ladder_total_usd"] == pytest.approx(top / 3 * 1000 + mo["gpu_box_usd"])
    assert mo["break_even_volume"] == int(mo["gpu_box_usd"] / ((base - top) / 3))


def test_live_records_to_rates():
    from apps.replay import live
    req = lambda i, tier, cls, cache=None, top=0: {"type": "req", "id": i, "tier": tier, "cls": cls, "cache": cache, "tin": 10, "tout": 20,  # noqa: E731
                                                  "tokens_logged": True, "ladder_top_tokens": top, "ladder_usd": 0.0, "answer": "a", "error": ""}
    j = {"in": 100, "out": 10}
    recs = [req("1", "gpu-small", "lookup"), req("2", "cloud-deepseek", "lookup", top=30), req("3", "semantic_cache", "near_repeat", "semantic_cache"),
            {"type": "req", "id": "4", "error": "boom", "ms": 1},
            {"type": "ref", "id": "1", "score": 3, "ref_usd": 0.0, "judge": j}, {"type": "cachejudge", "id": "3", "ok": False, "judge": j}]
    rows, rates, q = live.rows_and_rates(recs)
    assert len(rows) == 3 and q["failed_requests"] == 1
    assert rates["p30"]["lookup"] == 0.5 and rates["agree"] == 0.0 and rates["wrong_hit"] == 1.0
    assert q["wrong_cache_hits"] == 1 and q["judged"] == 1 and q["passed"] == 0
    assert live._parse_score('{"score": 4}') == 4 and live._parse_score("") is None


def test_no_saving_means_no_break_even():
    rows = [{"id": "a", "cls": "hard", "tin": 10, "tout": 10, "est_tokens": False, "ladder_top_tokens": 20, "ladder_usd": 1.0,
             "wrong_hit": 0, "bad_answer": 0}]
    assert estimate.summarize(rows, "grok-class", 100)["monthly"]["break_even_volume"] is None
    assert "never" in report.markdown(report.build(rows, "estimate", estimate.DEFAULT_RATES, 100))
