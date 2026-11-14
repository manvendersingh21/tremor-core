"""evallog: importer mapping per CSV, leaderboard math, /api/evals shape. Offline, reads the real result files."""
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "bench"), str(ROOT / "apps/phantom-phone/hud-web")]
import evallog  # noqa: E402
from evallog import EvalRow  # noqa: E402


def _csv(tmp_path, name, text):
    p = tmp_path / name
    p.write_text(text)
    return p


def test_results_mapping(tmp_path):
    p = _csv(tmp_path, "r.csv", "mode,id,cat,tier,latency_ms,local_tokens,cloud_prompt_tokens,cloud_completion_tokens,cloud_cached_tokens,usd,quality\n"
             "B,e1,easy,cloud_handoff,100,5,10,20,3,0.5,1\nB,h1,code_heavy,cloud,200,0,1,2,0,0.1,4\n")
    a, b = evallog.import_results(p)
    assert (a.tier, a.tokens_in, a.tokens_out, a.cached_tokens, a.dollars, a.passed) == ("cloud", 10, 20, 3, 0.5, True)
    assert "mac_tokens=5" in a.notes
    assert b.passed is None and "heavy_grade=4" in b.notes  # a 1-5 grade is not a pass


def test_gpu_handoff_is_gpu_and_no_dollars(tmp_path):
    p = _csv(tmp_path, "g.csv", "mode,id,cat,tier,latency_ms,local_tokens,gpu_prompt_tokens,gpu_completion_tokens,quality\nH,h1,code_heavy,cloud_handoff,9,1,7,8,\n")
    (r,) = evallog.import_gpu(p)
    assert (r.tier, r.tokens_in, r.dollars, r.passed) == ("gpu", 7, None, None)


def test_ladder_uses_top_tokens_else_gpu(tmp_path):
    p = _csv(tmp_path, "l.csv", "mode,id,cat,tier,latency_ms,top_prompt_tokens,top_completion_tokens,top_cached_tokens,top_usd,gpu_prompt_tokens,gpu_completion_tokens,quality,top_ms,local_ms,mid_ms,brief_ms,heavy_grade\n"
             "L,h1,code_heavy,top,1,5,6,0,0.1,2,3,,,,,,5\nL,e1,easy,gpu,1,0,0,0,0,9,8,1,,,,,\n")
    a, b = evallog.import_ladder(p)
    assert (a.tokens_in, a.tokens_out, a.passed) == (5, 6, None) and "gpu_tokens=2/3" in a.notes and "heavy_grade=5" in a.notes
    assert (b.tier, b.tokens_in, b.passed) == ("gpu", 9, True)


def test_spec_and_specplus_and_suite(tmp_path):
    s = _csv(tmp_path, "s.csv", "id,cat,K,new_tokens,rounds,drafted,accepted,alpha,tokens_per_round,bytes_up_per_round,bytes_down_per_round,draft_s,verify_rtt_s,verify_server_s,total_s,tok_s,decode_tok_s\n"
             "e1,easy,ollama,8,,,,,,,,,,,3.9,2.05,26\ne1,easy,4,8,2,7,7,1.0,4,1,1,1,1,1,5.16,1.5,\n")
    a, b = evallog.import_spec(s)
    assert (a.mode, a.latency_ms, b.mode, a.tokens_in) == ("ollama", 3900.0, "spec-K4", None)
    sp = _csv(tmp_path, "sp.csv", "section,setup,alpha,bytes_per_rt,free_frac,lossy_unchecked_per_100,lossy_wrong_per_100,passes_per_100,rt_per_100,rtt_ms,srv_ms,tok_per_rt,tok_s,tokens\nablation,x,-,-,-,,,1,-,150,50,-,2,99\n")
    (r,) = evallog.import_specplus(sp)
    assert r.item_id == "ablation-rtt150-srv50" and r.tokens_out == 99 and "alpha" not in (r.notes or "")
    j = tmp_path / "suite_TOP.jsonl"
    j.write_text(json.dumps({"id": "mmlu-1", "mode": "TOP", "tier": "cloud-deepseek", "latency_ms": 5, "attempts": ["cloud-deepseek"], "error": "", "grade": 1,
                             "per_tier": {"cloud-deepseek": {"tokens_in": 4, "tokens_out": 1, "dollars": 0.01}}}) + "\n")
    (q,) = evallog.import_suite(j)
    assert (q.dataset, q.tier, q.tokens_in, q.dollars, q.passed) == ("mmlu", "cloud", 4, 0.01, True)


def _r(mode, item, tier, tin, tout=0, usd=None, ms=1, passed=None):
    return EvalRow(run_id="x", dataset="d", item_id=item, mode=mode, tier=tier, tokens_in=tin, tokens_out=tout, dollars=usd, latency_ms=ms, passed=passed)


def test_leaderboard_math():
    rows = [_r("A", "1", "cloud", 50, 50, 1.0, 10, True), _r("A", "2", "cloud", 100, 0, 1.0, 30, True),
            _r("B", "1", "cloud", 20, 20, 2.0, 20, False), _r("B", "2", "mac", 5, 5, 0.0, 40, True), _r("B", "3", "mac", 1000, 0, None, 1, True)]
    lb = {s["mode"]: s for s in evallog.leaderboard(rows)}
    assert lb["A"]["baseline"] and lb["A"]["saved_pct"] is None
    assert lb["B"]["top_tokens"] == 40
    assert round(lb["B"]["saved_pct"], 6) == 80.0  # 1 - 40/200, only items 1 and 2 count (item 3 is not in the baseline)
    assert lb["B"]["pass_rate"] == 2 / 3 and lb["B"]["p50_ms"] == 20.0
    assert set(lb["B"]["bad"]) == {"p90_ms", "pass_rate"}


def test_api_shape_and_db_roundtrip(tmp_path):
    rows = [_r("A", "1", "cloud", 1, 2, 0.1, 5, True), _r("B", "1", "semantic_cache", 0, 0, 0.0, 1, True)]
    db = tmp_path / "e.db"
    evallog.upsert_sqlite(rows, db)
    evallog.upsert_sqlite(rows, db)  # idempotent
    back = evallog.load_rows(db)
    assert len(back) == 2 and back[0].passed is True
    p = evallog.api_payload(back)
    assert set(p) == {"leaderboard", "tokens_by_tier", "n", "rows"} and p["n"] == 2
    assert {"dataset", "mode", "top_tokens", "saved_pct", "dollars", "p50_ms", "p90_ms", "pass_rate", "n", "bad"} <= set(p["leaderboard"][0])
    assert p["tokens_by_tier"][1]["cache"] == 0
