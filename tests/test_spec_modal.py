import importlib.util
import pathlib
import random
import sys
import time

import pytest

from chimera_core.inference import specplus as sp

_p = pathlib.Path(__file__).resolve().parents[1] / "bench" / "spec_modal_core.py"
_s = importlib.util.spec_from_file_location("spec_modal_core", _p)
core = importlib.util.module_from_spec(_s)
sys.modules["spec_modal_core"] = core
_s.loader.exec_module(core)

EOS = 0


def target(ctx):  # fake big model: next token is a function of the last two tokens
    return (ctx[-1] * 7 + ctx[-2] * 3 + 1) % 50 if (ctx[-1] + len(ctx)) % 41 else EOS


def make(noise, seed=1, delay=0.0):
    rnd = random.Random(seed)

    def draft(ctx, k):
        c, out = list(ctx), []
        for _ in range(k):
            t = target(c) if rnd.random() > noise else rnd.randrange(50)
            out.append(t)
            c.append(t)
            if t == EOS:
                break
        return out

    def verify(ctx, d):
        time.sleep(delay)
        c = list(ctx)
        for i, t in enumerate(d):
            g = target(c)
            if g != t:
                return i, g
            c.append(t)
        return len(d), target(c)

    return draft, verify


def alone(prompt, n):
    c, out = list(prompt), []
    while len(out) < n:
        t = target(c)
        out.append(t)
        c.append(t)
        if t == EOS:
            break
    return out


def test_lossless_for_every_mode():
    choose = core.make_choose(sp.choose_k)
    free = sp.FreeDrafter(n=2, m=6)
    modes = [{}, {"choose": choose}, {"pipeline": True}, {"free": lambda c: free.propose(c, 1)},
             {"choose": choose, "pipeline": True, "free": lambda c: free.propose(c, 1)}]
    for noise in (0.0, 0.3, 1.0):
        for kw in modes:
            for seed in range(4):
                prompt = [random.Random(seed).randrange(1, 50) for _ in range(5)]
                d, v = make(noise, seed)
                out, st = core.spec_generate(d, v, prompt, 60, k=4, eos={EOS}, **kw)
                assert core.first_diff(out, alone(prompt, 60)) == -1, (noise, kw)
                assert 0 <= st.alpha <= 1 and 0 <= st.alpha_tested <= 1


def test_pipeline_reuses_pre_drafts_and_good_drafter_needs_fewer_rounds():
    d, v = make(0.0, delay=0.002)
    _, st = core.spec_generate(d, v, [3, 4, 5], 40, k=4, eos={EOS}, pipeline=True)
    assert st.reused > 0
    d, v = make(1.0)
    _, st_bad = core.spec_generate(d, v, [3, 4, 5], 40, k=4, eos={EOS})
    assert st.rounds < st_bad.rounds


def test_alpha_tested_counts_only_tested_tokens():
    st = core.SpecStats(drafted=8, accepted=3, misses=2)  # rounds: accept 3 then miss; miss at once
    assert st.alpha == 3 / 8 and st.alpha_tested == 3 / 5


def test_accept_reads_both_logprob_shapes():
    d = [11, 12, 13]
    absolute = [None, None, {"11": {"logprob": -0.1, "rank": 1}},
                {"12": {"logprob": -0.2, "rank": 1}}, {"13": {"logprob": -3.0, "rank": 2}, "99": {"logprob": -0.1, "rank": 1}}]
    assert core.accept_from_prompt_logprobs(absolute, 2, d) == (2, 99)
    relative = [[{"token_id": 11, "logprob": -0.1, "rank": 1}], [{"token_id": 12, "logprob": -0.1, "rank": 1}],
                {"token_id": 13, "logprob": -0.2, "rank": 1, "top_logprobs": [{"token_id": 13, "logprob": -0.2, "rank": 1}]}]
    assert core.accept_from_prompt_logprobs(relative, 7, d) == (3, None)
    try:
        core.accept_from_prompt_logprobs([None] * 5, 2, d)
        raise AssertionError("a missing row must raise")
    except core.IncompleteScores:
        pass


def test_first_diff_ignores_trailing_eos():
    assert core.first_diff([1, 2, 151645], [1, 2]) == -1
    assert core.first_diff([1, 2, 3], [1, 5, 3]) == 1
    assert core.first_diff([1, 2], [1, 2, 3]) == 2


# ---------- the vLLM client against a fake server (both transports, fast path, fallback) ----------
import json  # noqa: E402

import httpx  # noqa: E402


def big_model(c):  # never emits EOS, outputs are >= 100 so 13/14 are always "wrong" drafts
    return (c[-1] * 7 + (c[-2] if len(c) > 1 else 0) * 3 + 1) % 50 + 100


def noisy_model(c):
    return big_model(c) if len(c) % 3 else big_model(c) + 1


def fake_vllm(model, tito=True, fast_holes=False, block=4):
    """Greedy fake of vLLM's /inference/v1/generate and /v1/completions. With skip_reading_prefix_cache=False it
    behaves like vLLM's prefix cache: the hit is the longest prefix (in whole blocks, at most len-1) shared with an
    earlier prompt of the same salt, and prompt_logprobs is [None] + rows from the hit on. fast_holes: a broken server
    that drops one draft row."""
    seen: dict[str, list[list[int]]] = {}

    def handler(request):
        body = json.loads(request.content)
        if request.url.path == "/inference/v1/generate":
            if not tito:
                return httpx.Response(403)
            ids, sp = body["token_ids"], body["sampling_params"]
        else:
            ids, sp = body["prompt"], body
        assert sp["temperature"] == 0.0 and sp["repetition_penalty"] == 1.0 and body["cache_salt"]
        assert "stop_token_ids" in sp
        c, out = list(ids), []
        while len(out) < sp["max_tokens"]:
            out.append(model(c))
            c.append(out[-1])
        pl = None
        if sp.get("prompt_logprobs"):
            rows = []
            for i in range(1, len(ids)):
                top = model(ids[:i])
                row = {str(top): {"logprob": -0.1, "rank": 1}, str(top + 50): {"logprob": -1.0, "rank": 2}}
                if ids[i] not in (top, top + 50):
                    row[str(ids[i])] = {"logprob": -5.0, "rank": 9}
                rows.append(row)
            hit = 0
            if sp.get("skip_reading_prefix_cache") is False:
                for prev in seen.get(body["cache_salt"], []):
                    n = 0
                    while n < min(len(prev), len(ids)) and prev[n] == ids[n]:
                        n += 1
                    hit = max(hit, min(n, len(ids) - 1) // block * block)
                if fast_holes:
                    hit = len(ids) - 2  # drops draft rows: must be caught
            pl = [None] + rows[hit:]
        seen.setdefault(body["cache_salt"], []).append(list(ids))
        if request.url.path == "/v1/completions":
            return httpx.Response(200, json={"choices": [{"token_ids": out, "prompt_logprobs": pl}]})
        return httpx.Response(200, json={"choices": [{"token_ids": out}], "prompt_logprobs": pl})

    return httpx.Client(transport=httpx.MockTransport(handler))


PROMPT = [3, 4, 5, 6, 7, 8]


def test_selftest_picks_tito_and_fast_path():
    v = core.VLLM("big", client=fake_vllm(big_model))
    rep = v.selftest(PROMPT)
    assert (v.transport, v.fast) == ("tito", True) and rep["tito"]["agrees_with_decode"]


def test_selftest_falls_back_to_openai_transport():
    v = core.VLLM("big", client=fake_vllm(big_model, tito=False))
    v.selftest(PROMPT)
    assert v.transport == "openai"


def test_fast_path_with_holes_is_rejected_and_falls_back():
    v = core.VLLM("big", client=fake_vllm(big_model, fast_holes=True))
    v.selftest(PROMPT)
    assert v.fast is False
    v.fast = True
    g = v.gen(PROMPT, 6, "s")
    assert v.verify(PROMPT, g[:3] + [13], "s") == (3, g[3]) and v.fallbacks >= 1


def test_top2_orders_best_first():
    v = core.VLLM("big", client=fake_vllm(big_model))
    (t1, l1), (t2, l2) = v.top2(PROMPT, "s")
    assert t1 == big_model(PROMPT) and l1 > l2


def test_spec_over_two_fake_servers_matches_big_alone():
    big, small = core.VLLM("big", client=fake_vllm(big_model)), core.VLLM("small", client=fake_vllm(noisy_model))
    big.selftest(PROMPT)
    free = sp.FreeDrafter(n=2, m=4)
    for kw in ({}, {"choose": core.make_choose(sp.choose_k), "pipeline": True, "free": lambda c: free.propose(c, 1)}):
        out, st = core.spec_generate(lambda c, k: small.gen(c, k, "d"), lambda c, d: big.verify(c, d, "v"), PROMPT, 40,
                                     k=4, eos=set(core.EOS), **kw)
        assert out == big.gen(PROMPT, 40, "ref") and st.accepted > 0


# ---------- the driver: prompt set and summary ----------
_d = importlib.util.spec_from_file_location("run_spec_modal", pathlib.Path(__file__).resolve().parents[1] / "bench" / "run_spec_modal.py")
driver = importlib.util.module_from_spec(_d)
_d.loader.exec_module(driver)


@pytest.mark.skipif(not (pathlib.Path(__file__).resolve().parents[1] / "bench/datasets/suite.jsonl").exists(),
                    reason="bench/datasets/suite.jsonl is git-ignored (bench/datasets/README.md builds it); not on CI")
def test_prompt_set_is_mixed_and_warmups_are_not_measured():
    ps = driver.pick_prompts()
    ids = {p["id"] for p in ps["prompts"]}
    assert len(ps["prompts"]) == 48 and sum(p["kind"] == "code" for p in ps["prompts"]) == 28
    assert len(ps["warm"]) == 2 and not ids & {w["id"].removeprefix("warm-") for w in ps["warm"]}


def test_summary_counts_tokens_per_second_and_acceptance():
    rows = [{"out": [1] * 10, "wall_s": 1.0, "kind": "code", "rounds": 4, "drafted": 12, "accepted": 6, "misses": 3,
             "ks": [4, 4, 2, 2], "draft_ms": 40.0, "free_accepted": 0, "reused": 1}]
    s = driver.summarize({"rows": rows, "rtt_ms": [30.0, 50.0], "server_ms": [10.0, 20.0]})
    assert s["tok_s"] == 10 and s["alpha"] == 0.5 and s["alpha_tested"] == 6 / 9 and s["net_p50_ms"] == 30.0


# ---------- the Modal runner's own loop (run_plan, mismatches) on fakes; skipped where modal is not installed ----------
def test_run_plan_end_to_end_on_fakes(monkeypatch, tmp_path):
    import pytest

    pytest.importorskip("modal")
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "deploy" / "modal"))
    import spec_modal as m

    monkeypatch.setitem(sys.modules, "specplus", sp)
    big = core.VLLM("big", client=fake_vllm(big_model))
    big.selftest(PROMPT)

    def handler(req):
        b = json.loads(req.content) if req.content else {}
        if req.url.path == "/verify":
            mm, nxt = big.verify(b["ctx"], b["draft"], b["salt"])
            return httpx.Response(200, json={"m": mm, "next": nxt, "server_ms": 1.0})
        if req.url.path == "/generate":
            return httpx.Response(200, json={"ids": big.gen(b["ctx"], b["max_tokens"], b["salt"]), "server_ms": 2.0})
        return httpx.Response(200, json={})  # /stats

    monkeypatch.setattr(m, "big_client", lambda url: httpx.Client(base_url=url, transport=httpx.MockTransport(handler)))

    class Tok:  # chat template as text, then token ids, like encode() in the Modal file
        def apply_chat_template(self, msgs, tokenize=False, add_generation_prompt=True, **kw):
            assert tokenize is False and add_generation_prompt
            return "x" * len(msgs[0]["content"])

        def __call__(self, text, add_special_tokens=True):
            assert add_special_tokens is False
            return {"input_ids": PROMPT + [len(text) % 40 + 1]}

        def decode(self, ids):
            return " ".join(map(str, ids))

    prompts = [{"id": i, "kind": "code", "messages": [{"role": "user", "content": "x" * (i + 1)}]} for i in range(3)]
    local = core.VLLM("small", client=fake_vllm(noisy_model))
    url = "http://fake"
    base = m.run_plan(prompts, prompts[:1], {"name": "big_alone", "mode": "big_alone", "max_tokens": 30}, url, Tok(), None)
    for plan in ({"name": "s", "mode": "spec", "max_tokens": 30, "k": 4}, {"name": "p", "mode": "spec", "max_tokens": 30, "adaptive": True, "pipeline": True, "free": True}):
        res = m.run_plan(prompts, prompts[:1], plan, url, Tok(), local)
        assert [r["out"] for r in res["rows"]] == [r["out"] for r in base["rows"]]
        assert len(res["rtt_ms"]) == sum(r["rounds"] for r in res["rows"])  # warm-up rounds are not counted
    alone = m.run_plan(prompts, [], {"name": "d", "mode": "draft_alone", "max_tokens": 30}, url, Tok(), local)
    (tmp_path / "big_alone.json").write_text(json.dumps(base))
    (tmp_path / "d.json").write_text(json.dumps(alone))
    (tmp_path / "s.json").write_text(json.dumps(res))
    diffs = m.mismatches(tmp_path, "big_alone", ["s", "d"])
    assert {x["run"] for x in diffs} == {"d"} and all(x["ctx"][: len(PROMPT)] == PROMPT for x in diffs)


def test_live_apps_reads_lowercase_app_list_keys():
    rows = [{"app_id": "ap-1", "description": "chimera-spec-qa", "state": "ephemeral"},
            {"app_id": "ap-2", "description": "chimera-spec-qa", "state": "stopped"},
            {"app_id": "ap-3", "description": "chimera-video-wan", "state": "deployed"}]
    assert [a["app_id"] for a in driver.live_apps("chimera-spec-qa", rows)] == ["ap-1"]


def test_jobs_are_consistent():
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "deploy" / "modal"))
    import spec_models as sm

    for name, cfg in sm.JOBS.items():
        assert cfg["app"].startswith("chimera-spec-") and cfg["big"] in sm.MODELS and cfg["tok"] in sm.MODELS
        assert sm.MODELS[cfg["tok"]]["family"] == sm.MODELS[cfg["big"]]["family"], name  # one tokenizer per job
        names = [p["name"] for p in cfg["plans"]]
        assert len(names) == len(set(names)), name
        for p in cfg["plans"]:
            assert p["mode"] in ("draft_alone", "big_alone", "spec", "margins", "switch"), p
            if p["mode"] in ("draft_alone", "spec"):
                d = sm.DRAFTERS[p["drafter"]]
                assert sm.MODELS[d["model"]]["family"] == sm.MODELS[cfg["big"]]["family"], p  # same tokenizer
                assert d["mode"] in sm.MODES
            if p["mode"] == "switch":
                assert p["to"] in sm.MODES
            if p["mode"] == "margins":
                assert set(p["runs"]) <= set(names) and p["base"] in names
    assert len({c["app"] for c in sm.JOBS.values()}) == len(sm.JOBS)  # parallel jobs never share an app name
    for m in sm.MODES.values():
        assert m is None or "model" not in m or m["model"] in sm.MODELS


def test_report_tables_from_fake_runs(tmp_path, monkeypatch):
    monkeypatch.setattr(driver, "OUT", tmp_path)
    base = {"plan": {"name": "s_big_alone", "mode": "big_alone"}, "rows": [{"id": 1, "kind": "code", "out": [5, 6, 7], "wall_s": 1.0}]}
    spec = {"plan": {"name": "s_spec_k4", "mode": "spec", "drafter": "q3_4b", "k": 4},
            "rows": [{"id": 1, "kind": "code", "out": [5, 6, 7], "wall_s": 0.5, "rounds": 1, "drafted": 3, "accepted": 2,
                      "misses": 1, "ks": [4], "draft_ms": 10.0, "free_accepted": 0, "reused": 0}],
            "rtt_ms": [30.0], "server_ms": [10.0]}
    for n, r in (("s_big_alone", base), ("s_spec_k4", spec)):
        (tmp_path / f"{n}.json").write_text(json.dumps(r))
    table = driver.job_tables("smoke", driver.load_runs())
    row = next(line for line in table.splitlines() if "`s_spec_k4`" in line)
    assert "2.00x" in row and "1/1" in row and "30 / 30" in row
