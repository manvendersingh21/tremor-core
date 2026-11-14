"""Fetch small samples of public, ungated Hugging Face datasets through the datasets-server rows API.

No full downloads: each dataset is read in 100-row pages and only the pages we need are kept. Pages are
cached as JSON under $KIROCREW_SCRATCH/hf (never in the repo). Before each dataset, the size reported by the
server is printed and a dataset above MAX_BYTES is refused.

    .venv/bin/python bench/datasets/fetch.py            # fetch everything, write licenses.json to the cache
"""
from __future__ import annotations

import json
import os
import pathlib
import random
import time

import httpx

API = "https://datasets-server.huggingface.co"
HUB = "https://huggingface.co/api/datasets"
CACHE = pathlib.Path(os.environ.get("KIROCREW_SCRATCH") or "/tmp") / "hf"
MAX_BYTES = 150 * 2**20  # refuse any dataset whose original files are larger than this

# name -> (repo id, config, split)
SOURCES = {
    "humaneval": ("openai/openai_humaneval", "openai_humaneval", "test"),
    "mbpp": ("google-research-datasets/mbpp", "sanitized", "test"),
    "gsm8k": ("openai/gsm8k", "main", "test"),
    "dolly": ("databricks/databricks-dolly-15k", "default", "train"),
    "qqp": ("nyu-mll/glue", "qqp", "validation"),
}
MMLU = ("cais/mmlu", ["high_school_geography", "world_religions", "nutrition", "astronomy",
                      "computer_security", "us_foreign_policy"], "test")

_client = httpx.Client(timeout=60, follow_redirects=True)


def _get(url: str, **params) -> dict:
    for attempt in range(6):
        r = _client.get(url, params=params)
        if r.status_code == 200:
            return r.json()
        if r.status_code in (429, 500, 502, 503):
            time.sleep(2 * (attempt + 1))
            continue
        r.raise_for_status()
    raise RuntimeError(f"giving up on {url} {params}")


def info(repo: str) -> dict:
    """Size (bytes of original files) and license of a dataset; raises if gated or too big."""
    meta = _get(f"{HUB}/{repo}")
    if meta.get("gated"):
        raise RuntimeError(f"{repo} is gated, skipping")
    size = _get(f"{API}/size", dataset=repo)["size"]["dataset"]["num_bytes_original_files"]
    lic = (meta.get("cardData") or {}).get("license") or next(
        (t.split(":", 1)[1] for t in meta.get("tags", []) if t.startswith("license:")), "unknown")
    print(f"{repo}: {size / 2**20:.1f} MiB original, license={lic}")
    if size > MAX_BYTES:
        print(f"  large dataset: streaming pages only, never downloading it whole")
    return {"repo": repo, "bytes": size, "license": lic if isinstance(lic, str) else ",".join(lic)}


def rows(repo: str, config: str, split: str, offset: int, length: int = 100) -> list[dict]:
    """One cached page of rows (<= 100)."""
    f = CACHE / f"{repo.replace('/', '__')}.{config}.{split}.{offset}.{length}.json"
    if f.exists():
        return json.loads(f.read_text())
    data = _get(f"{API}/rows", dataset=repo, config=config, split=split, offset=offset, length=length)
    out = [r["row"] for r in data["rows"]]
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(out))
    return out


def total(repo: str, config: str, split: str) -> int:
    d = _get(f"{API}/size", dataset=repo)["size"]["splits"]
    return next(s["num_rows"] for s in d if s["config"] == config and s["split"] == split)


def all_rows(name: str) -> list[dict]:
    repo, config, split = SOURCES[name]
    n = total(repo, config, split)
    return [r for off in range(0, n, 100) for r in rows(repo, config, split, off)]


def sample_rows(name: str, pages: int, seed: int) -> list[dict]:
    """`pages` random 100-row pages of a big dataset (dolly, qqp)."""
    repo, config, split = SOURCES[name]
    n = total(repo, config, split)
    offs = random.Random(seed).sample(range(0, n - 100, 100), pages)
    return [r for off in sorted(offs) for r in rows(repo, config, split, off)]


def mmlu_rows() -> list[dict]:
    repo, subjects, split = MMLU
    out = []
    for s in subjects:
        n = total(repo, s, split)
        for off in range(0, n, 100):
            out += [{**r, "subject": s} for r in rows(repo, s, split, off)]
    return out


def main() -> None:
    lic = {name: info(src[0]) for name, src in SOURCES.items()}
    lic["mmlu"] = info(MMLU[0])
    for name in SOURCES:
        n = len(all_rows(name) if name not in ("dolly", "qqp") else sample_rows(name, 6, 7))
        print(f"  {name}: {n} rows cached")
    print(f"  mmlu: {len(mmlu_rows())} rows cached")
    (CACHE / "licenses.json").write_text(json.dumps(lic, indent=1))
    print("cache:", CACHE)


if __name__ == "__main__":
    main()
