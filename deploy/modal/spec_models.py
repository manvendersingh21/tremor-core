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
