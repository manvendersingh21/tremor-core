PY ?= .venv/bin/python
HUD = apps/phantom-phone/hud-web

.PHONY: setup test demo bench serve-local site loop

setup:
	python3 -m venv .venv
	$(PY) -m pip install -e ".[dev,embed]"

test:
	$(PY) -m pytest -q tests

demo:
	@if [ -f $(HUD)/demo.py ] || [ -f $(HUD)/server.py ]; then \
	  [ -f $(HUD)/demo.py ] && $(PY) $(HUD)/demo.py; \
	  [ -f $(HUD)/server.py ] && $(PY) $(HUD)/server.py; \
	else echo "HUD demo is not built yet"; fi

bench:
	@echo "Rerun commands (from bench/*.md):"
	@for f in bench/results*.md bench/spec_results.md; do [ -f $$f ] && { echo "# $$f"; awk '/^## (Reproduce|Rerun)/{h=1;next} /^## /{h=0} h&&/^```/{c=!c;next} h&&c' $$f; }; done; true

serve-local:
	bench/serve_local.sh

loop:  # N rounds through the tier pool (ROUNDS=3); LOOP_ARGS=--forever for continuous
	$(PY) bench/run_loop.py --rounds $(or $(ROUNDS),3) $(LOOP_ARGS)

site:
	python3 site/build.py --check || python3 site/build.py
	@echo "Open http://127.0.0.1:8765  (Ctrl-C to stop)"
	python3 -m http.server 8765 --bind 127.0.0.1 --directory site
