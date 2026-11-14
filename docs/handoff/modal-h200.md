# Handoff: Modal H200 gpu-large tier (for the backend owner)

## State
- Modal: every `chimera-*` app is stopped, 0 tasks (proof in `bench/results_modal.md`). Volumes `chimera-hf-cache` (gpt-oss-120b weights, about 65 GB) and `chimera-vllm-cache` are kept.
- No ssh tunnels were opened by this work.

## Done
- `d0a4776`: Qwen3.5-122B attempt write-up, `make modal-up` / `make modal-down`.
- This commit: `deploy/modal/vllm_server.py` serves `openai/gpt-oss-120b` on `vllm/vllm-openai:v0.33.0` (cold start 376 s). Pair runs A and D measured in `bench/results_modal.md` and `bench/results_modal.csv`. Verdict: A (763B only) beats D on cost and speed, quality ties.
- Gateway: `x-chimera-tier` now names the pool tier (e.g. `gpu-large`) via `Telemetry.tier_name` (`packages/chimera-core/router.py`, `apps/gateway/app.py`). `apps/gateway/server.py` skips the mid/top wrappers in pool mode. Test in `tests/test_tiers.py`.
- `bench/run_pairs.py`, `bench/run_kv.py` committed (H200 body uses gpt-oss).

## Half done
1. Run E (`bench/run_pairs.py E`) failed in 6 s with `Connection refused`. Next step: check each tier URL in `chimera.example.toml` (the 30B is on 127.0.0.1:11436 via `--gpu-small-url`; GMI tiers need `GMI_API_KEY`).
2. KV test: `bench/run_kv.py` not run. Needs the H200 up.
3. Gateway smoke: script at `$KIROCREW_SCRATCH/gw_smoke.py` (scratch, not committed). It writes a pool-mode config copy and calls the gateway on port 8099 with the OpenAI SDK.
4. Blind grade: `bench/run_pairs.py report` (grades with Qwen3.8-27B, rewrites `bench/results_modal.csv` with every run present).

## Resume
```
make modal-up                       # then set MODAL_VLLM_URL in .env if it changed
curl -H "Authorization: Bearer $MODAL_VLLM_TOKEN" $MODAL_VLLM_URL/v1/models   # 200 after ~2-4 min warm volume
.venv/bin/python bench/run_pairs.py E B C --gpu-small-url http://127.0.0.1:11436
.venv/bin/python bench/run_kv.py
.venv/bin/python bench/run_pairs.py report
make modal-down                     # always; then check `modal app list`
```
Cost: H200 is $4.54/hr while up. Stop it before any wait over 5 min.
