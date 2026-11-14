PY ?= .venv/bin/python
HUD = apps/phantom-phone/hud-web

.PHONY: setup test demo web bench serve-local site loop modal-up modal-down

setup:
	python3 -m venv .venv
	$(PY) -m pip install -e ".[dev,embed]"

test:
	$(PY) -m pytest -q tests

web:  # one page, one port: castle, dashboard and API on http://127.0.0.1:8765 (CHIMERA_PORT to change)
	python3 site/build.py --check || python3 site/build.py
	$(PY) $(HUD)/server.py

demo:  # the same page fed by invented demo telemetry (labelled demo) instead of the real log
	HUD_TELEMETRY=$(HUD)/telemetry.jsonl $(PY) $(HUD)/demo.py & HUD_TELEMETRY=$(HUD)/telemetry.jsonl $(PY) $(HUD)/server.py

bench:
	@echo "Rerun commands (from bench/*.md):"
	@for f in bench/results*.md bench/spec_results.md; do [ -f $$f ] && { echo "# $$f"; awk '/^## (Reproduce|Rerun)/{h=1;next} /^## /{h=0} h&&/^```/{c=!c;next} h&&c' $$f; }; done; true

serve-local:
	bench/serve_local.sh

loop:  # N rounds through the tier pool (ROUNDS=3); LOOP_ARGS=--forever for continuous
	$(PY) bench/run_loop.py --rounds $(or $(ROUNDS),3) $(LOOP_ARGS)

site: web  # old name

modal-up:  # deploy the H200 tier (scales to zero by itself). First call after this cold-starts it.
	.venv/bin/modal deploy deploy/modal/vllm_server.py

modal-down:  # stop the app so nothing can start again, then show what is left
	.venv/bin/modal app stop -y chimera-gpu-large
	.venv/bin/modal app list
