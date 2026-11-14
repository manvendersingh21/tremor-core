"""Property test for the /api/chat event stream shape (docs/api.md). Fake tiers and fake Supabase. Property P25."""
import json

from hypothesis import given, strategies as st

from _props import PBT
from test_service import Fake, router
from test_pgvector_cache import settle

from chimera_core.config import ChimeraConfig
from chimera_core.service import Service

FIELDS = {
    "embed": {"ms", "dim"},
    "cache_shared": {"hit", "status", "threshold", "kind", "score", "guard", "ms"},
    "memory": {"op"},
    "decide": {"tier", "reason"},
    "call": {"tier", "model", "ok", "ms", "tokens_in", "tokens_out", "cached_tokens"},
    "draft": {"tier", "model", "confidence", "gate"},
    "final": {"tier", "model", "tokens_in", "tokens_out", "cached_tokens", "dollars", "dollars_saved", "ms",
              "tokens_kept_off_big", "cache"},
    "answer": {"text"},
    "done": set(),
}


# P25 (R9.3): any prompt gets a stream with documented steps, each carrying its documented fields, ending answer, done
@PBT
@given(st.lists(st.text(alphabet="abcdefgh ", min_size=1, max_size=12), min_size=1, max_size=4).map(" ".join)
       .filter(lambda s: s.strip()), st.one_of(st.none(), st.floats(0, 1)), st.booleans())
def test_chat_stream_carries_the_documented_fields(prompt, conf, twice):
    svc = Service(router(small=Fake("small", conf=conf)), ChimeraConfig(), rate_per_min=10**6, burst=10**6)
    for _ in range(2 if twice else 1):  # the second pass is a cache hit: fewer steps, same shapes
        events = list(svc.chat({"prompt": prompt}, "127.0.0.1"))
        settle(svc.router.shared)
        names = [e for e, _ in events]
        assert names[-2:] == ["answer", "done"] and "error" not in names
        for step, data in events:
            assert FIELDS[step] <= set(data), (step, data)
            json.dumps(data)
        assert names.index("embed") < names.index("cache_shared") < names.index("final") < names.index("answer")
        if names.count("decide"):  # a miss: retrieve, then decide/call/draft, then store, then final
            assert names.index("memory") < names.index("decide") < names.index("call") < len(names) - names[::-1].index("memory")
        final = dict(events)["final"]
        assert final["tokens_kept_off_big"] >= 0 and final["dollars_saved"] >= 0 and final["dollars"] >= 0
        assert final["cache"] in (None, "shared")
