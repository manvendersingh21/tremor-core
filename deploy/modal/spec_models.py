"""Model registry for the speculative-decoding runs on Modal (shared by spec_modal.py and spec_download.py).

Weights live only on Modal v2 Volumes, one per family, mounted at /w/<family>. Nothing is downloaded to the Mac.
Tokenizer checks (SHA-256 of tokenizer.json from the Hugging Face API, 2026-11-15):
  qwen3  : every Qwen3 model below shares one tokenizer.json (151,936 tokens), Coder-480B included. The Coder models
           ship a different chat template (a default system prompt), so the 480B runs use the Coder template.
  qwen35 : Qwen3.5 has its own tokenizer (248,320 tokens), so it cannot verify Qwen3 drafts: it is its own chain.
"""

FAMILIES = {
    "qwen3": {"volume": "chimera-spec-w-qwen3", "eos": [151645, 151643], "chat": {}},
    "qwen35": {"volume": "chimera-spec-w-qwen35", "eos": [248046, 248044], "chat": {"enable_thinking": False}},
}

WEIGHTS = ["*.json", "*.safetensors", "*.txt", "*.jinja", "*.py", "tokenizer*", "*.model"]

MODELS = {  # key: family, Hugging Face repo, extra vllm flags when served
    "q3_4b": {"family": "qwen3", "repo": "Qwen/Qwen3-4B-Instruct-2507-FP8"},
    "q3_30b": {"family": "qwen3", "repo": "Qwen/Qwen3-30B-A3B-Instruct-2507-FP8"},
    "q3_235b": {"family": "qwen3", "repo": "Qwen/Qwen3-235B-A22B-Instruct-2507-FP8"},
    "q3c_30b": {"family": "qwen3", "repo": "Qwen/Qwen3-Coder-30B-A3B-Instruct-FP8"},
    "q3c_480b": {"family": "qwen3", "repo": "Qwen/Qwen3-Coder-480B-A35B-Instruct-FP8"},
    "q3_eagle_235b": {"family": "qwen3", "repo": "RedHatAI/Qwen3-235B-A22B-Instruct-2507-speculator.eagle3"},
    "q3_eagle_30b": {"family": "qwen3", "repo": "RedHatAI/Qwen3-30B-A3B-Instruct-2507-speculator.eagle3"},
    "q35_4b": {"family": "qwen35", "repo": "Qwen/Qwen3.5-4B", "flags": ["--language-model-only"]},
    "q35_35b": {"family": "qwen35", "repo": "Qwen/Qwen3.5-35B-A3B-FP8", "flags": ["--language-model-only"]},
    "q35_397b": {"family": "qwen35", "repo": "Qwen/Qwen3.5-397B-A17B-FP8", "flags": ["--language-model-only"]},
}
PHASE_A = ["q3_4b", "q3_30b", "q3_eagle_30b", "q3_eagle_235b", "q3c_30b", "q3_235b", "q35_4b", "q35_35b", "q35_397b",
           "q3c_480b"]


def path(key: str) -> str:
    m = MODELS[key]
    return f"/w/{m['family']}/{m['repo'].split('/')[-1]}"


def family(key: str) -> dict:
    return FAMILIES[MODELS[key]["family"]]


# ---------- same-box speculative settings (vLLM --speculative-config); "model" is a key of MODELS ----------
MODES = {
    "plain": None,
    "ngram": {"method": "ngram", "num_speculative_tokens": 4, "prompt_lookup_min": 2, "prompt_lookup_max": 5},
    "draft_q3_4b": {"method": "draft_model", "model": "q3_4b", "num_speculative_tokens": 4},
    "eagle_q3_235b": {"method": "eagle3", "model": "q3_eagle_235b", "num_speculative_tokens": 3},  # the head's own K
    "eagle_q3_30b": {"method": "eagle3", "model": "q3_eagle_30b", "num_speculative_tokens": 3},
    "mtp2": {"method": "mtp", "num_speculative_tokens": 2},  # Qwen3.5 card: MTP with 2 tokens
}

# ---------- drafter boxes (the "local machine"): model, GPU, and the drafter's own same-box helper ----------
DRAFTERS = {
    "q3_30b": {"model": "q3_30b", "gpu": "L40S", "mode": "plain"},
    "q3_4b": {"model": "q3_4b", "gpu": "L40S", "mode": "plain"},
    "q3_30b+4b": {"model": "q3_30b", "gpu": "L40S", "mode": "draft_q3_4b"},  # 2-level chain: 4B -> 30B, then -> big
    "q3_30b+eagle": {"model": "q3_30b", "gpu": "L40S", "mode": "eagle_q3_30b"},
    "q3c_30b": {"model": "q3c_30b", "gpu": "L40S", "mode": "plain"},
    "q35_35b": {"model": "q35_35b", "gpu": "L40S", "mode": "plain"},
    "q35_4b": {"model": "q35_4b", "gpu": "L40S", "mode": "plain"},
    "q35_35b+mtp": {"model": "q35_35b", "gpu": "L40S", "mode": "mtp2"},
}


# ---------- jobs: one big model per job, plans run in order; a finished plan file is skipped on a rerun ----------
def P(name, drafter, mode, **kw):
    return {"name": name, "drafter": drafter, "mode": mode, **kw}


def SW(to, tag):
    return {"name": f"{tag}_switch_{to}", "drafter": None, "mode": "switch", "to": to}


PLUS = {"adaptive": True, "pipeline": True, "free": True}


def _cross(t, mid, small, chain, extra=()):
    """The cross-box block of a job: big alone, then each drafter's runs back to back (one cold start each)."""
    plans = [P(f"{t}_big_alone", None, "big_alone"),
             P(f"{t}_mid_alone", mid, "draft_alone"), P(f"{t}_spec_k4", mid, "spec", k=4),
             P(f"{t}_specplus", mid, "spec", **PLUS), P(f"{t}_spec_k8", mid, "spec", k=8),
             P(f"{t}_spec_k4_rtt100", mid, "spec", k=4, extra_rtt_ms=100),
             P(f"{t}_small_alone", small, "draft_alone"), P(f"{t}_small_spec_k4", small, "spec", k=4),
             P(f"{t}_small_specplus", small, "spec", **PLUS),
             P(f"{t}_chain_alone", chain, "draft_alone"), P(f"{t}_chain_spec_k4", chain, "spec", k=4),
             P(f"{t}_chain_specplus", chain, "spec", **PLUS), *extra,
             P(f"{t}_big_alone_rep", None, "big_alone")]
    runs = [p["name"] for p in plans if p["mode"] in ("spec", "draft_alone") or p["name"].endswith("_rep")]
    return plans + [P(f"{t}_margins", None, "margins", base=f"{t}_big_alone", runs=runs)]


def _same(t, modes):
    plans = []
    for m in modes:
        plans += [SW(m, t), P(f"{t}_big_{m}", None, "big_alone")]
    return plans + [SW("plain", t), P(f"{t}_margins_same", None, "margins", base=f"{t}_big_alone",
                                         runs=[f"{t}_big_{m}" for m in modes])]


JOBS = {
    # cheap check of every code path: 30B as the "big" model on one L40S, the 4B drafts; 3 prompts, 48 tokens
    "smoke": {"app": "chimera-spec-smoke", "big": "q3_30b", "gpu": "L40S", "tok": "q3_30b", "n_prompts": 3,
              "max_tokens": 48,
              "plans": [P("s_big_alone", None, "big_alone"), P("s_small_alone", "q3_4b", "draft_alone"),
                        P("s_spec_k4", "q3_4b", "spec", k=4), P("s_specplus", "q3_4b", "spec", **PLUS),
                        P("s_rtt100", "q3_4b", "spec", k=4, extra_rtt_ms=100),
                        P("s_margins", None, "margins", base="s_big_alone", runs=["s_spec_k4", "s_specplus", "s_small_alone"]),
                        *_same("s", ["ngram", "eagle_q3_30b", "draft_q3_4b"])]},
    "qa_235b": {"app": "chimera-spec-qa-235b", "big": "q3_235b", "gpu": "H200:2", "tok": "q3_235b",
                "plans": _cross("a235", "q3_30b", "q3_4b", "q3_30b+4b",
                                extra=[P("a235_mideagle_alone", "q3_30b+eagle", "draft_alone"),
                                       P("a235_mideagle_specplus", "q3_30b+eagle", "spec", **PLUS)])
                + _same("a235", ["eagle_q3_235b", "ngram", "draft_q3_4b"])},
    "qa_480b": {"app": "chimera-spec-qa-480b", "big": "q3c_480b", "gpu": "H200:4", "tok": "q3c_480b", "subset": "code",
                "plans": _cross("c480", "q3_30b", "q3_4b", "q3_30b+4b",
                                extra=[P("c480_coder_alone", "q3c_30b", "draft_alone"),
                                       P("c480_coder_spec_k4", "q3c_30b", "spec", k=4),
                                       P("c480_coder_specplus", "q3c_30b", "spec", **PLUS)])
                + _same("c480", ["ngram", "draft_q3_4b"])},
    "qa_397b": {"app": "chimera-spec-qa-397b", "big": "q35_397b", "gpu": "H200:4", "tok": "q35_397b",
                "plans": _cross("q397", "q35_35b", "q35_4b", "q35_35b+mtp") + _same("q397", ["mtp2", "ngram"])},
}
