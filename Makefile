PY ?= .venv/bin/python
HUD = apps/phantom-phone/hud-web

.PHONY: setup test demo bench serve-local

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
