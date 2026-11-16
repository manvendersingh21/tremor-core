"""CPU-only download of the speculative-decoding weights into Modal v2 Volumes (never to the Mac).

  python bench/run_spec_modal.py download q3_4b,q3_30b,...     # wraps `modal run` and stops the app after

App `chimera-spec-download`: one CPU container per model, in parallel; each writes <model dir>/.complete when done.
"""
import json
import pathlib
import sys
import time

import modal

_here = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_here))
from spec_models import FAMILIES, MODELS, WEIGHTS, path  # noqa: E402

import os  # noqa: E402

# one app name per batch, so a first batch can finish (and be stopped) while a second one still downloads
app = modal.App("chimera-spec-download" + (f"-{os.environ['SPEC_DL_TAG']}" if os.environ.get("SPEC_DL_TAG") else ""))
vols = {f"/w/{f}": modal.Volume.from_name(c["volume"], create_if_missing=True, version=2) for f, c in FAMILIES.items()}
image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install("huggingface_hub[hf_xet]>=0.34")
    .env({"HF_XET_HIGH_PERFORMANCE": "1"})
    .add_local_file(_here / "spec_models.py", "/root/spec_models.py")
)


@app.function(image=image, volumes=vols, cpu=8, memory=16384, timeout=4 * 60 * 60, scaledown_window=120)
def fetch(key: str) -> dict:
    from huggingface_hub import snapshot_download

    dest = pathlib.Path(path(key))
    done = dest / ".complete"
    if done.exists():
        return json.loads(done.read_text())
    t0 = time.time()
    snapshot_download(MODELS[key]["repo"], local_dir=str(dest), allow_patterns=WEIGHTS + MODELS[key].get("extra", []),
                      ignore_patterns=MODELS[key].get("ignore"), max_workers=16)
    size = sum(p.stat().st_size for p in dest.rglob("*") if p.is_file())
    info = {"key": key, "repo": MODELS[key]["repo"], "gb": round(size / 1e9, 1), "seconds": round(time.time() - t0)}
    done.write_text(json.dumps(info))
    vols[f"/w/{MODELS[key]['family']}"].commit()
    return info


@app.local_entrypoint()
def main(keys: str):
    for info in fetch.map(keys.split(","), return_exceptions=True):
        print("downloaded:", info, flush=True)
