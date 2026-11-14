"""Config loading, CLI ask output, and an MCP stdio round trip, all with fake backends."""
import json
import pathlib
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from chimera_core.config import ROOT, ChimeraConfig, build_router, load_config
from chimera_core.inference.local_draft import DraftResult
from chimera_core.inference.telemetry import TelemetryTracker

APP = ROOT / "apps" / "kiro-trimmer"
sys.path.insert(0, str(APP))
import cli  # noqa: E402


class FakeLocal:
    calls = 0

    def complete(self, prompt, max_tokens, system=None):
        FakeLocal.calls += 1
        return DraftResult(text="Paris", token_ids=[1], logprobs=[-0.01], mean_confidence=0.99)


class FakeEmbedder:
    def embed(self, text):
        return [1.0, 0.0] if "capital" in text else [0.0, 1.0]


def cfg_for(tmp_path, **cache):
    return ChimeraConfig.model_validate({
        "cache": {"path": str(tmp_path / "c.db"), "semantic": False, **cache},
        "telemetry": {"path": str(tmp_path / "t.jsonl")},
    })


def test_example_toml_loads_with_spec_values():
    cfg = load_config(ROOT / "chimera.example.toml")
    assert (cfg.thresholds.semantic, cfg.thresholds.confidence, cfg.thresholds.heavy) == (0.97, 0.85, 0.6)
    assert cfg.gpu.model == "qwen3:30b-instruct" and cfg.gpu.url.endswith(":11435")
    assert "key" not in (ROOT / "chimera.example.toml").read_text().lower().replace("api_key comes", "")


def test_telemetry_env_override(tmp_path, monkeypatch):
    monkeypatch.setenv("CHIMERA_TELEMETRY", str(tmp_path / "x.jsonl"))
    assert load_config(ROOT / "chimera.example.toml").telemetry_path == tmp_path / "x.jsonl"


def test_exact_cache_survives_restart_and_telemetry_is_written(tmp_path):
    cfg = cfg_for(tmp_path)
    build_router(cfg, local=FakeLocal(), mid=object(), top=object()).generate("hello there")
    r2 = build_router(cfg, local=FakeLocal(), mid=object(), top=object())  # new process stand-in
    assert r2.generate("hello there").telemetry.tier_used == "exact_cache"
    tiers = [json.loads(x)["tier_used"] for x in (tmp_path / "t.jsonl").read_text().splitlines()]
    assert tiers == ["local", "exact_cache"]


def test_semantic_cache_persists_in_same_file(tmp_path):
    cfg = cfg_for(tmp_path, semantic=True)
    kw = dict(local=FakeLocal(), mid=object(), top=object(), embedder=FakeEmbedder(), tracker=TelemetryTracker())
    build_router(cfg, **kw).generate("what is the capital of France")
    out = build_router(cfg, **kw).generate("capital of France?")
    assert out.telemetry.tier_used == "semantic_cache"


def test_cli_ask_prints_answer_and_one_telemetry_line(tmp_path, monkeypatch, capsys):
    cfg_file = tmp_path / "chimera.toml"
    cfg_file.write_text(f'[cache]\npath="{tmp_path}/c.db"\nsemantic=false\n[telemetry]\npath="{tmp_path}/t.jsonl"\n')
    monkeypatch.setattr(cli, "build_router", lambda cfg: build_router(cfg, local=FakeLocal(), mid=object(), top=object()))
    assert cli.main(["--config", str(cfg_file), "ask", "capital of France?"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == "Paris"
    assert lines[1].startswith("[tier=local latency=") and "tokens_saved=" in lines[1] and "dollars_saved=$" in lines[1]
    assert cli.main(["--config", str(cfg_file), "stats"]) == 0
    assert "calls=1" in capsys.readouterr().out


class _LlamaStub(BaseHTTPRequestHandler):
    def do_POST(self):
        self.rfile.read(int(self.headers["Content-Length"]))
        body = json.dumps({"content": "Paris", "completion_probabilities": [{"id": 1, "logprob": -0.01}]}).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


def test_mcp_stdio_tools_list_and_call_round_trip(tmp_path):
    srv = HTTPServer(("127.0.0.1", 0), _LlamaStub)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    cfg_file = tmp_path / "chimera.toml"
    cfg_file.write_text(
        f'[local]\nurl="http://127.0.0.1:{srv.server_port}"\n[gpu]\nenabled=false\n'
        f'[cache]\npath="{tmp_path}/c.db"\nsemantic=false\n[telemetry]\npath="{tmp_path}/t.jsonl"\n')
    env = {"PATH": "/usr/bin:/bin", "CHIMERA_CONFIG": str(cfg_file)}
    p = subprocess.Popen([sys.executable, str(APP / "mcp_server.py")], stdin=subprocess.PIPE,
                         stdout=subprocess.PIPE, text=True, env=env)

    def rpc(method, params=None, id=None):
        msg = {"jsonrpc": "2.0", "method": method, "params": params or {}, **({"id": id} if id else {})}
        p.stdin.write(json.dumps(msg) + "\n")
        p.stdin.flush()
        return json.loads(p.stdout.readline()) if id else None

    try:
        rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                           "clientInfo": {"name": "t", "version": "0"}}, id=1)
        rpc("notifications/initialized")
        names = {t["name"] for t in rpc("tools/list", id=2)["result"]["tools"]}
        assert names == {"chimera_generate", "chimera_stats", "chimera_risk_score"}
        r = rpc("tools/call", {"name": "chimera_generate", "arguments": {"prompt": "capital of France?"}}, id=3)
        assert "Paris" in r["result"]["content"][0]["text"] and "tier=local" in r["result"]["content"][0]["text"]
        r = rpc("tools/call", {"name": "chimera_risk_score", "arguments": {"action": "Merge PR"}}, id=4)
        assert json.loads(r["result"]["content"][0]["text"])["needs_approval"] is True
    finally:
        p.kill()
        srv.shutdown()
