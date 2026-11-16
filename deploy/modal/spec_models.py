"""Model registry and job plans for the speculative-decoding runs on Modal (spec_modal.py, spec_download.py).

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
    "q3c_eagle_480b": {"family": "qwen3", "repo": "lmsys/SGLang-EAGLE3-Qwen3-Coder-480B-A35B-Instruct-SpecForge-EigenAI"},
    "q35_4b": {"family": "qwen35", "repo": "Qwen/Qwen3.5-4B", "flags": ["--language-model-only"]},
    "q35_35b": {"family": "qwen35", "repo": "Qwen/Qwen3.5-35B-A3B-FP8", "flags": ["--language-model-only"]},
    "q35_397b": {"family": "qwen35", "repo": "Qwen/Qwen3.5-397B-A17B-FP8", "flags": ["--language-model-only"]},
    "q35_eagle_397b": {"family": "qwen35", "repo": "AQ-MedAI/Qwen3.5-397B-A17B-eagle3"},
}


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
    "eagle_q3c_480b": {"method": "eagle3", "model": "q3c_eagle_480b", "num_speculative_tokens": 3},
    "eagle_q35_397b": {"method": "eagle3", "model": "q35_eagle_397b", "num_speculative_tokens": 3},
    "draft_q35_4b": {"method": "draft_model", "model": "q35_4b", "num_speculative_tokens": 4},
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


# ---------- jobs: one big model per job; plans run in order; a finished plan file is skipped on a rerun ----------
def P(name, drafter, mode, **kw):
    return {"name": name, "drafter": drafter, "mode": mode, **kw}


def SW(to, tag):
    return {"name": f"{tag}_switch_{to}", "drafter": None, "mode": "switch", "to": to}


PLUS = {"adaptive": True, "pipeline": True, "free": True}


def phase_a(t, mid, small, chain, same, extra=()):
    """Most important first, so a job that stops early still answers the main question:
    big alone -> mid drafter across boxes (plain, Spec+, K=8, +100 ms) -> same box (vLLM's own speculative modes)
    -> small drafter -> 2-level chain -> extras -> big alone again (run-to-run check) -> near-tie check on every
    difference from big alone."""
    plans = [P(f"{t}_big_alone", None, "big_alone"),
             P(f"{t}_mid_alone", mid, "draft_alone"), P(f"{t}_spec_k4", mid, "spec", k=4),
             P(f"{t}_specplus", mid, "spec", **PLUS), P(f"{t}_spec_k8", mid, "spec", k=8),
             P(f"{t}_spec_k4_rtt100", mid, "spec", k=4, extra_rtt_ms=100),
             P(f"{t}_specplus_rtt100", mid, "spec", extra_rtt_ms=100, **PLUS)]
    for m in same:
        plans += [SW(m, t), P(f"{t}_big_{m}", None, "big_alone")]
    plans += [SW("plain", t),
              P(f"{t}_small_alone", small, "draft_alone"), P(f"{t}_small_spec_k4", small, "spec", k=4),
              P(f"{t}_small_specplus", small, "spec", **PLUS),
              P(f"{t}_chain_alone", chain, "draft_alone"), P(f"{t}_chain_spec_k4", chain, "spec", k=4),
              P(f"{t}_chain_specplus", chain, "spec", **PLUS), *extra,
              P(f"{t}_big_alone_rep", None, "big_alone")]
    # only runs that must match big alone (spec, same-box modes, the repeat); a drafter alone is another model
    runs = [p["name"] for p in plans if p["mode"] in ("spec", "big_alone") and p["name"] != f"{t}_big_alone"]
    return plans + [P(f"{t}_rescore", None, "rescore", base=f"{t}_big_alone"),
                    P(f"{t}_margins", None, "margins", base=f"{t}_big_alone", runs=runs)]


def resume_235(t):
    """235B runs in account C, in order of value: baseline, the runs account B never reached, then repeats."""
    new = [P(f"{t}_big_alone", None, "big_alone"), P(f"{t}_rescore", None, "rescore", base=f"{t}_big_alone"),
           P(f"{t}_chain_alone", "q3_30b+4b", "draft_alone"), P(f"{t}_chain_spec_k4", "q3_30b+4b", "spec", k=4),
           P(f"{t}_chain_specplus", "q3_30b+4b", "spec", **PLUS),
           P(f"{t}_mid_alone", "q3_30b", "draft_alone"),
           P(f"{t}_small_alone", "q3_4b", "draft_alone"), P(f"{t}_small_spec_k4", "q3_4b", "spec", k=4),
           P(f"{t}_big_alone_rep", None, "big_alone")]
    first = [p["name"] for p in new if p["mode"] in ("spec", "big_alone") and p["name"] != f"{t}_big_alone"]
    new.append(P(f"{t}_margins", None, "margins", base=f"{t}_big_alone", runs=first))
    same = [SW("draft_q3_4b", t), P(f"{t}_big_draft_q3_4b", None, "big_alone")]
    more = [SW("eagle_q3_235b", t), P(f"{t}_big_eagle_q3_235b", None, "big_alone"),
            SW("ngram", t), P(f"{t}_big_ngram", None, "big_alone"), SW("plain", t),
            P(f"{t}_spec_k4", "q3_30b", "spec", k=4), P(f"{t}_specplus", "q3_30b", "spec", **PLUS),
            P(f"{t}_small_specplus", "q3_4b", "spec", **PLUS), P(f"{t}_spec_k8", "q3_30b", "spec", k=8),
            P(f"{t}_mideagle_alone", "q3_30b+eagle", "draft_alone"),
            P(f"{t}_mideagle_specplus", "q3_30b+eagle", "spec", **PLUS)]
    rest = [p["name"] for p in same + more if p["mode"] in ("spec", "big_alone")]
    return new + same + more + [P(f"{t}_margins_more", None, "margins", base=f"{t}_big_alone", runs=rest)]


JOBS = {
    # cheap check of every code path: the 30B plays the big model on one L40S, the 4B drafts; 3 prompts, 48 tokens
    "smoke": {"app": "chimera-spec-smoke", "big": "q3_30b", "gpu": "L40S", "tok": "q3_30b", "n_prompts": 3,
              "max_tokens": 48,
              "plans": [P("s_big_alone", None, "big_alone"), P("s_small_alone", "q3_4b", "draft_alone"),
                        P("s_spec_k4", "q3_4b", "spec", k=4), P("s_specplus", "q3_4b", "spec", **PLUS),
                        P("s_rtt100", "q3_4b", "spec", k=4, extra_rtt_ms=100),
                        SW("ngram", "s"), P("s_big_ngram", None, "big_alone"),
                        SW("eagle_q3_30b", "s"), P("s_big_eagle_q3_30b", None, "big_alone"),
                        SW("draft_q3_4b", "s"), P("s_big_draft_q3_4b", None, "big_alone"), SW("plain", "s"),
                        P("s_margins", None, "margins", base="s_big_alone",
                          runs=["s_spec_k4", "s_specplus", "s_rtt100", "s_big_ngram", "s_big_eagle_q3_30b",
                                "s_big_draft_q3_4b"])]},
    "qa_235b": {"app": "chimera-spec-qa-235b", "big": "q3_235b", "gpu": "H200:2", "gpu_fallback": ["H100:4"],
                "tok": "q3_235b",
                "plans": phase_a("a235", "q3_30b", "q3_4b", "q3_30b+4b", ["eagle_q3_235b", "ngram", "draft_q3_4b"],
                                 extra=[P("a235_mideagle_alone", "q3_30b+eagle", "draft_alone"),
                                        P("a235_mideagle_specplus", "q3_30b+eagle", "spec", **PLUS)])},
    # Account C: the rest of the 235B runs. Account B's credits ran out during qa_235b (its numbers are kept as
    # measured there). Own baseline first (every comparison stays inside one account and one box), then the runs
    # account B never reached, then (time allows) repeats of what account B measured. Same GPU type first (4 H100).
    "qb_235b": {"app": "chimera-spec-qb-235b", "big": "q3_235b", "gpu": "H100:4", "gpu_fallback": ["H200:2"],
                "tok": "q3_235b", "plans": resume_235("b235")},
    "qa_480b": {"app": "chimera-spec-qa-480b", "big": "q3c_480b", "gpu": "H200:4", "gpu_fallback": ["H100:8"],
                "tok": "q3c_480b", "subset": "code",
                "plans": phase_a("c480", "q3_30b", "q3_4b", "q3_30b+4b", ["eagle_q3c_480b", "ngram", "draft_q3_4b"],
                                 extra=[P("c480_coder_alone", "q3c_30b", "draft_alone"),
                                        P("c480_coder_spec_k4", "q3c_30b", "spec", k=4),
                                        P("c480_coder_specplus", "q3c_30b", "spec", **PLUS)])},
    "qa_397b": {"app": "chimera-spec-qa-397b", "big": "q35_397b", "gpu": "H200:4", "gpu_fallback": ["H100:8"],
                "tok": "q35_397b",
                "plans": phase_a("q397", "q35_35b", "q35_4b", "q35_35b+mtp",
                                 ["mtp2", "eagle_q35_397b", "ngram", "draft_q35_4b"])},
}
