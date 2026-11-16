"""chimera code: edit parsing, undo, risk gate, repair loop, status line. A fake router, no models."""
import hashlib
import math
import pathlib
import re
import sys

import pytest

from apps.terminal import edits as ed
from apps.terminal import safety
from apps.terminal.agent import Session, status_line
from apps.terminal.cli import handle, make_bank
from apps.terminal.routing import Reply
from chimera_core.memory import Bank, InMemoryBankStore

SR = "mod.py\n<<<<<<< SEARCH\nx = 1\n=======\nx = 2\n>>>>>>> REPLACE\n"


class FakeClient:
    """Returns the scripted replies in order and records (mode, floor) of each call."""

    def __init__(self, texts, tiers=("gpu-small", "cloud-deepseek")):
        self.texts, self.calls, self.tiers = list(texts), [], tiers

    def generate(self, prompt, mode="auto", floor=0, on_event=None, key=""):
        self.calls.append((mode, floor, prompt))
        self.keys = getattr(self, "keys", []) + [key]
        tier = self.tiers[min(floor, 1)]
        if on_event:
            on_event("decide", {"tier": tier})
        return Reply(text=self.texts.pop(0), tier=tier, model="Qwen2.5-3B-Instruct-q4_k_m", tokens_in=100,
                     tokens_out=20, ms=1200, kept_tokens=0 if tier == "cloud-deepseek" else 120, tried=[tier])


def sess(tmp_path, texts, **kw):
    out = []
    kw.setdefault("test_cmd", None)
    s = Session(tmp_path, FakeClient(texts), say=out.append, ask=kw.pop("ask", lambda p: "y"), yes=kw.pop("yes", True), **kw)
    return s, out


def test_parse_search_replace_and_whole_file():
    txt = SR + "\nFILE: new.py\nprint('hi')\nEND FILE\n"
    e = ed.parse_edits(txt)
    assert [(x.path, x.search) for x in e] == [("mod.py", "x = 1"), ("new.py", None)]
    assert ed.parse_edits("sub/a.py\n```python\nA = 1\n```\n")[0].replace == "A = 1"
    assert ed.parse_edits("--- a.py ---\n<<<<<<< SEARCH\nq\n=======\nr\n>>>>>>> REPLACE")[0].path == "a.py"
    assert ed.parse_edits("hello.py: main\n<<<<<<< SEARCH\nq\n=======\nr\n>>>>>>> REPLACE")[0].path == "hello.py"
    assert ed.parse_edits("<<<<<<< SEARCH\nq\n=======\nr\n>>>>>>> REPLACE", "only.py")[0].path == "only.py"
    fenced = ed.parse_edits("db.py\n```python\n<<<<<<< SEARCH\nq\n=======\nr\n>>>>>>> REPLACE\n```")
    assert [(x.path, x.search) for x in fenced] == [("db.py", "q")]
    e = ed.parse_edits("--- s.py ---\nclass S:\n    pass\n--- t.py ---\nT = 1")
    assert [(x.path, x.search, x.replace) for x in e] == [("s.py", None, "class S:\n    pass"), ("t.py", None, "T = 1")]
    assert ed.parse_edits("just prose, no edit") == []


def test_apply_exact_whitespace_tolerant_and_missing():
    e = ed.Edit("m.py", "  x = 1", "x = 2")
    assert ed.apply_edit("a\nx = 1\nb", e) == "a\nx = 2\nb"          # indentation differs: matched by stripped lines
    with pytest.raises(ed.EditError):
        ed.apply_edit("a\nb", ed.Edit("m.py", "zzz", "q"))
    assert ed.apply_edit(None, ed.Edit("n.py", None, "A")) == "A\n"
    assert ed.apply_edit("def f():\n    pass\n\ndef g():\n    pass\n", ed.Edit("m.py", "def f():\n    pass\ndef g():\n    pass", "X")) == "X\n"


def test_write_then_undo_restores_and_removes(tmp_path):
    (tmp_path / "mod.py").write_text("x = 1\n")
    s, _ = sess(tmp_path, [SR, "FILE: new.py\nB = 1\nEND FILE"])
    s.task("bump")
    assert (tmp_path / "mod.py").read_text() == "x = 2\n"
    s.task("add file")
    assert (tmp_path / "new.py").exists()
    s.undo()
    assert not (tmp_path / "new.py").exists()
    s.undo()
    assert (tmp_path / "mod.py").read_text() == "x = 1\n"
    assert s.undo() == "nothing to undo"


def test_review_no_writes_when_refused(tmp_path):
    (tmp_path / "mod.py").write_text("x = 1\n")
    s, _ = sess(tmp_path, [SR], yes=False, ask=lambda p: "n")
    s.task("bump")
    assert (tmp_path / "mod.py").read_text() == "x = 1\n"
    s2, _ = sess(tmp_path, [SR], yes=False, ask=lambda p: "a")  # "always" sets yes for the session
    s2.task("bump")
    assert s2.yes and (tmp_path / "mod.py").read_text() == "x = 2\n"


def test_risk_gate_needs_typed_token_even_with_yes(tmp_path):
    s, out = sess(tmp_path, [], yes=True, ask=lambda p: "no")
    ok, msg = s.run("rm -rf build")
    assert not ok and "refused" in msg
    tok = {}

    def ask(p):
        tok["t"] = p.split()[1]
        return tok["t"]
    s2, _ = sess(tmp_path, [], yes=True, ask=ask)
    s2._run = lambda *a, **k: type("P", (), {"returncode": 0, "stdout": "ok", "stderr": ""})()
    assert s2.run("git push origin dev")[0] and tok["t"]
    assert safety.risk("write file /etc/x", outside_cwd=True).needs_approval
    assert not safety.risk("ls -l").needs_approval


def test_outside_cwd_write_refused_without_token(tmp_path):
    other = tmp_path.parent / "outside_target.py"
    s, _ = sess(tmp_path, ["../outside_target.py\n<<<<<<< SEARCH\n=======\nA = 1\n>>>>>>> REPLACE"], ask=lambda p: "")
    s.task("make it")
    assert not other.exists()


def test_secret_files_blocked_and_redacted(tmp_path):
    (tmp_path / ".env").write_text("OPENAI_API_KEY=sk-abcdefghijklmnopqrstuvwxyz\n")
    (tmp_path / "ok.py").write_text('KEY = "x"\nTOKEN = "abcdef123456"\nBEARER = "Bearer abcdefghijklmnopqrstuvwxyz0123"\n')
    s, out = sess(tmp_path, [])
    assert not s.add(".env") and any("credential" in o for o in out)
    assert s.add("ok.py")
    p = s.prompt("hi")
    assert "abcdef123456" not in p and "abcdefghijklmnopqrstuvwxyz0123" not in p
    assert safety.redact("postgres://u:pw1234@host/db") == "postgres://[redacted]@host/db"


def test_gitignore_respected(tmp_path):
    (tmp_path / ".gitignore").write_text("secret_dir/\n*.log\n")
    (tmp_path / "a.log").write_text("x")
    s, out = sess(tmp_path, [])
    assert not s.add("a.log") and any("gitignore" in o for o in out)


def test_repair_loop_climbs_and_stops_at_three(tmp_path):
    (tmp_path / "mod.py").write_text("x = 1\n")
    fix = "mod.py\n<<<<<<< SEARCH\nx = {a}\n=======\nx = {b}\n>>>>>>> REPLACE"
    texts = [fix.format(a=1, b=2), fix.format(a=2, b=3), fix.format(a=3, b=4), fix.format(a=4, b=5)]
    cmd = f"{sys.executable} -c \"import mod; assert mod.x == 99\""
    s, _ = sess(tmp_path, texts, test_cmd=cmd)
    r = s.task("make x 99")
    assert r.ok is False and r.rounds == 3 and len(s.client.calls) == 4   # first try + 3 repairs, no more
    assert [c[1] for c in s.client.calls] == [0, 1, 1, 1]                 # climbs one tier per failed round
    assert "AssertionError" in s.client.calls[1][2]                         # the error output is fed back


def test_repair_succeeds_and_forced_tier_does_not_climb(tmp_path):
    (tmp_path / "mod.py").write_text("x = 1\n")
    fix = "mod.py\n<<<<<<< SEARCH\nx = {a}\n=======\nx = {b}\n>>>>>>> REPLACE"
    cmd = f"{sys.executable} -c \"import mod; assert mod.x == 3\""
    s, _ = sess(tmp_path, [fix.format(a=1, b=2), fix.format(a=2, b=3)], test_cmd=cmd, mode="local")
    r = s.task("make x 3")
    assert r.ok is True and r.rounds == 1 and [c[1] for c in s.client.calls] == [0, 0]


def test_bad_search_block_is_fed_back(tmp_path):
    (tmp_path / "mod.py").write_text("x = 1\n")
    bad = "mod.py\n<<<<<<< SEARCH\nnope\n=======\ny\n>>>>>>> REPLACE"
    s, _ = sess(tmp_path, [bad, SR])
    s.task("bump")
    assert "could not be applied" in s.client.calls[1][2] and (tmp_path / "mod.py").read_text() == "x = 2\n"


def test_status_line_and_cost(tmp_path):
    r = Reply(text="", tier="mac-3b", model="Qwen2.5-3B-Instruct-q4_k_m", tokens_in=300, tokens_out=112, ms=1234,
              kept_tokens=412, tried=["mac-3b"])
    line = status_line(r)
    assert line == "-> local (Qwen2.5-3B) · 412 tok · $0 · 1.2 s · supabase MISS cos - · kept 412 tok off the big model"
    assert "supabase MISS cos 0.83" in status_line(Reply(text="", tier="mac-3b", cache_status="ok", cache_score=0.83))
    assert "supabase unavailable" in status_line(Reply(text="", tier="mac-3b", cache_status="unavailable"))
    hit = Reply(text="", cache="shared", cache_score=0.99, kept_tokens=50)
    assert "supabase HIT cos 0.99" in status_line(hit)
    big = Reply(text="", tier="cloud-deepseek", model="deepseek-ai/DeepSeek-V4.1-Flash", dollars=0.0004, ms=900,
                tried=["mac-3b", "cloud-deepseek"])
    assert "went to the big model" in status_line(big) and "after mac-3b>cloud-deepseek" in status_line(big)
    (tmp_path / "mod.py").write_text("x = 1\n")
    s, out = sess(tmp_path, [SR])
    s.task("bump")
    handle(s, "/cost")
    assert "total" in out[-1] and "kept off the big model" in out[-1] and "gpu-small" in out[-1]


def test_slash_commands(tmp_path):
    (tmp_path / "a.py").write_text("A = 1\n")
    s, out = sess(tmp_path, [])
    handle(s, "/add a.py")
    handle(s, "/files")
    assert out[-1] == "a.py"
    handle(s, "/tier cloud")
    assert s.mode == "cloud"
    handle(s, "/drop")
    assert s.files == []
    assert handle(s, "/exit") is False


def test_no_local_cache_file_is_written(tmp_path, monkeypatch):
    """The real Cascade constructor leaves no SQLite cache on disk: the answer cache is Supabase only."""
    from apps.terminal import routing

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("CHIMERA_TELEMETRY", str(tmp_path / "t.jsonl"))
    monkeypatch.delenv("CHIMERA_DB_URL", raising=False)
    monkeypatch.setattr("chimera_core.config.load_env", lambda *a, **k: None)
    c = routing.Cascade(gpu_url="http://127.0.0.1:1")
    c.router.exact.put("p", "a")
    assert c.router.exact.get("p") is None and c.router.semantic is None
    assert not list(tmp_path.rglob("*.db")) and not (tmp_path / ".chimera" / "cache.db").exists()
    assert not pathlib.Path(":memory:").exists()


def test_h200_joins_the_30b_step_only(monkeypatch):
    """The H200 30B is tried before the Akash 30B on the 30B step; a failed test round climbs past both."""
    from apps.terminal import routing
    from chimera_core.config import ROOT, load_config

    tiers = load_config(ROOT / "chimera.example.toml").tiers
    c = routing.Cascade(router=type("R", (), {"cfg": __import__("chimera_core.router", fromlist=["x"]).RouterConfig()})(),
                        tiers=tiers)
    names = lambda floor: [t.name for t in c._pool(c.names("auto", floor), False).tiers]  # noqa: E731
    assert names(0) == ["gpu-h200", "gpu-small", "cloud-deepseek"]
    assert names(1) == ["cloud-deepseek"]


def test_cache_key_hashes_context_files(tmp_path):
    (tmp_path / "a.py").write_text("x = 1\n")
    s, _ = sess(tmp_path, [])
    assert s.context_key() == ""                      # no files: a plain request may share cached answers
    s.add("a.py")
    k1 = s.context_key()
    (tmp_path / "a.py").write_text("x = 2\n")
    assert k1 and s.context_key() != k1               # other file text: other key, never a stale answer


def test_unpathed_search_goes_to_matching_file_and_file_wrapped_search(tmp_path):
    (tmp_path / "a.py").write_text("A = 1\n")
    (tmp_path / "b.py").write_text("B = 1\n")
    s, _ = sess(tmp_path, ["<<<<<<< SEARCH\nB = 1\n=======\nB = 2\n>>>>>>> REPLACE",
                           "FILE: a.py\n<<<<<<< SEARCH\nA = 1\n=======\nA = 3\n>>>>>>> REPLACE\nEND FILE"])
    s.add("a.py"); s.add("b.py")
    s.task("b to 2")
    s.task("a to 3")
    assert (tmp_path / "b.py").read_text() == "B = 2\n" and (tmp_path / "a.py").read_text() == "A = 3\n"
    assert s.client.keys[0] != s.client.keys[1]   # file text changed in between: other cache key


# ---- solved-problem bank ------------------------------------------------------------------------
X2 = f"{sys.executable} -c \"import mod; assert mod.x == 2\""


class BagEmbedder:
    def embed(self, text):
        v = [0.0] * 64
        for w in re.findall(r"[a-z0-9]+", text.lower()):
            v[int(hashlib.md5(w.encode()).hexdigest(), 16) % 64] += 1.0
        n = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / n for x in v]


def banked(tmp_path, texts, store=None, verify=None, **kw):
    """A session on mod.py (x = 1) with a bank whose verify is the session's own sandbox run."""
    (tmp_path / "mod.py").write_text("x = 1\n")
    s, out = sess(tmp_path, texts, test_cmd=kw.pop("test_cmd", X2), **kw)
    s.add("mod.py")
    s.bank = Bank(store if store is not None else InMemoryBankStore(), BagEmbedder(), "t", verify or s.verify)
    return s, out


def problem_and_tests(s, request):
    return request + "\n" + s._file_blocks(), {"cmd": s.test_cmd, "files": {"mod.py": "x = 1\n"}}


def test_bank_hit_that_passes_is_served_without_a_model_call(tmp_path):
    s, out = banked(tmp_path, [])
    p, t = problem_and_tests(s, "make x 2")
    assert s.bank.add(p, "FILE: mod.py\nx = 2\nEND FILE", t)
    r = s.task("make x 2")
    assert r.ok is True and s.client.calls == [] and (tmp_path / "mod.py").read_text() == "x = 2\n"
    assert any(o.startswith("-> bank (exact) · 0 tok · $0 · ") and o.endswith("served after tests passed") for o in out)
    assert r.calls == [dict(r.calls[0], tier="bank", tokens=0, dollars=0.0, baseline_dollars=0.0)]
    handle(s, "/cost")
    assert re.search(r"^bank\s+1\s+0\s+0\.00000\s+0\.00000", out[-1], re.M)


def test_bank_hit_that_fails_its_tests_is_not_served(tmp_path):
    store = InMemoryBankStore()
    # A bad row in the store (written past the gate); the sandbox run catches it, the model answers.
    s, _ = banked(tmp_path, [SR], store=store)
    p, t = problem_and_tests(s, "make x 2")
    Bank(store, BagEmbedder(), "t", lambda a, t: True).add(p, "FILE: mod.py\nx = 7\nEND FILE", t)
    r = s.task("make x 2")
    assert r.ok is True and len(s.client.calls) == 1 and (tmp_path / "mod.py").read_text() == "x = 2\n"
    assert "bank" not in s.tally
    # The sandbox says yes but the tests here say no: the bank edit is undone before the model call.
    seen, store2 = [], InMemoryBankStore()
    s2, out = banked(tmp_path, [SR], store=store2, verify=lambda a, t: True)
    s2.bank.add(p, "FILE: mod.py\nx = 7\nEND FILE", t)
    s2.client.generate = lambda *a, **k: (seen.append((tmp_path / "mod.py").read_text()),
                                          FakeClient.generate(s2.client, *a, **k))[1]
    r2 = s2.task("make x 2")
    assert seen == ["x = 1\n"] and r2.ok is True and (tmp_path / "mod.py").read_text() == "x = 2\n"
    assert "bank" not in s2.tally and any("undone" in o for o in out)


def test_passing_model_answer_is_written_back_and_served_next_time(tmp_path):
    store = InMemoryBankStore()
    bad = "mod.py\n<<<<<<< SEARCH\nx = 1\n=======\nx = 5\n>>>>>>> REPLACE"
    fix = "mod.py\n<<<<<<< SEARCH\nx = 5\n=======\nx = 2\n>>>>>>> REPLACE"
    s, out = banked(tmp_path, [bad, fix], store=store)   # one repair round: the answer is the final file text
    assert s.task("make x 2").ok is True and len(s.client.calls) == 2
    assert "bank: saved the passing answer" in out
    (rec, _), = store.rows.values()
    assert rec.answer == "FILE: mod.py\nx = 2\n\nEND FILE" and rec.source == "chimera-code" and rec.tests["files"] == {"mod.py": "x = 1\n"}
    s2, _ = banked(tmp_path, [], store=store)               # same starting files, a new session
    r = s2.task("make x 2")
    assert r.ok is True and s2.client.calls == [] and (tmp_path / "mod.py").read_text() == "x = 2\n"


def test_failing_model_answer_is_never_written_back(tmp_path):
    store = InMemoryBankStore()
    s, _ = banked(tmp_path, ["mod.py\n<<<<<<< SEARCH\nx = 1\n=======\nx = 3\n>>>>>>> REPLACE"], store=store, max_repairs=0)
    assert s.task("make x 2").ok is False and store.rows == {}
    # A bank that raises never fails the task.
    s2, out = banked(tmp_path, [SR])
    s2.bank.add = lambda *a, **k: 1 / 0
    assert s2.task("make x 2").ok is True and any(o.startswith("bank: write skipped") for o in out)


def test_verify_never_modifies_root(tmp_path):
    s, _ = banked(tmp_path, [])
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "keep.txt").write_text("k\n")
    snap = lambda: {str(p): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}  # noqa: E731
    before = snap()
    t = {"cmd": X2, "files": {"mod.py": "x = 1\n"}}
    assert s.verify("FILE: mod.py\nx = 2\nEND FILE", t) is True
    assert s.verify("FILE: mod.py\nx = 3\nEND FILE", t) is False
    assert s.verify("FILE: new.py\nx = 2\nEND FILE", t) is False           # tests fail: mod.x is still 1
    assert s.verify("FILE: ../escape.py\nx = 2\nEND FILE", t) is False     # outside the copy: refused
    assert s.verify("no edits here", t) is False and s.verify("FILE: mod.py\nx = 2\nEND FILE", {}) is False
    assert snap() == before and not (tmp_path.parent / "escape.py").exists()


def test_verify_never_copies_credentials(tmp_path):
    no_env = f"{sys.executable} -c \"import os,sys; sys.exit(os.path.exists('.env'))\""
    s, _ = banked(tmp_path, [], test_cmd=no_env)
    (tmp_path / ".env").write_text("FAKE_KEY=not-a-real-value\n")
    assert s.verify("FILE: mod.py\nx = 2\nEND FILE", {"cmd": no_env, "files": {"mod.py": "x = 1\n"}}) is True


def test_verify_runs_only_the_session_test_command(tmp_path):
    s, _ = banked(tmp_path, [])
    passes = f"{sys.executable} -c \"pass\""
    assert s.verify("FILE: mod.py\nx = 2\nEND FILE", {"cmd": passes, "files": {"mod.py": "x = 1\n"}}) is False
    assert s.verify("FILE: mod.py\nx = 2\nEND FILE", {"cmd": s.test_cmd, "files": {"mod.py": "x = 1\n"}}) is True


def test_make_bank_needs_dsn_and_embedder(tmp_path, monkeypatch):
    monkeypatch.setattr("chimera_core.config.load_env", lambda *a, **k: None)
    monkeypatch.setattr("apps.terminal.cli.PgBankStore", lambda dsn: InMemoryBankStore())  # never a real DB
    monkeypatch.delenv("CHIMERA_CONFIG", raising=False)
    s, _ = sess(tmp_path, [])
    client = type("C", (), {"router": type("R", (), {"embedder": BagEmbedder()})()})()
    monkeypatch.delenv("CHIMERA_DB_URL", raising=False)
    assert make_bank(None, client, s) is None
    monkeypatch.setenv("CHIMERA_DB_URL", "postgres://fake")
    assert make_bank(None, type("C", (), {"router": type("R", (), {"embedder": None})()})(), s) is None
    b = make_bank(None, client, s)
    assert b.tenant.endswith(":terminal") and b.verify == s.verify
