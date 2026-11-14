---
inclusion: fileMatch
fileMatchPattern: ["site/**", "apps/**/server*.py"]
---

# Web API contract

`docs/api.md` is the contract. The backend owns it (`packages/chimera-core/service.py`). The UI only calls it.

#[[file:docs/api.md]]

- Shapes are fixed. New fields may be added, none removed or renamed. Event order for a miss: `embed`, `cache_shared`, `memory`, then per tier `decide`, `call`, `draft`, then `memory`, `final`, `answer`, `done`.
- The frontend reads events by name and ignores unknown fields. It never invents a step the API did not send, and it shows `cache_shared` as the only cache lane.
- A site change that needs a new field is a request to the backend, recorded in `docs/api.md` first.
- No response contains a key, a DSN or a host name. Do not render one either.
- Errors before a stream starts are JSON `{"error": {"code", "message"}}`. Show `429` and `503` with their `Retry-After`.
- One server: `apps/phantom-phone/hud-web/server.py` on 127.0.0.1:8765 (`make web`).
