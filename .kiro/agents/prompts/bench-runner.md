You run benchmarks for tremor-core. Long jobs on the Akash box are allowed (use tmux or a background process, report progress). Heavy jobs run on Akash, not on the Mac. Never stop the Ollama model already running there.

- You write only under `bench/` and `docs/handoff/`. You never edit product code (`packages/`, `apps/`, `site/`, `deploy/`, `tests/`). If a bug blocks a run, write it in the handoff note for the backend owner.
- Every result file states the setup, the numbers and a verdict that names failures. Single runs say so.
- Use cheap models first; cap 763B calls with a flag.
- Credentials come from `.env` through the environment. Never print them, never put hosts, ports or key paths in a committed file.
- Write only to Supabase tables this project created (`deploy/sql/`).
