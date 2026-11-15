"""Image-to-video on Modal: Wan 2.1 I2V 14B (720P, diffusers) on one H200, for the castle walk-in clips.

  modal deploy deploy/modal/wan_video.py     (app name chimera-video-wan)
  modal app stop -y chimera-video-wan        (always, when the clips are done)

Weights live in the `chimera-video-cache` Volume, never on the Mac. Called from scripts/gen_video.py (provider "modal").
shortcut: first frame only (no last-frame control), 81 frames at 16 fps; upgrade to Wan FLF2V if end-frame pinning is needed.
"""
import modal

MODEL = "Wan-AI/Wan2.1-I2V-14B-720P-Diffusers"
app = modal.App("chimera-video-wan")
cache = modal.Volume.from_name("chimera-video-cache", create_if_missing=True)
image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("ffmpeg")
    .pip_install("torch==2.6.0", "diffusers>=0.33", "transformers>=4.49", "accelerate", "ftfy", "sentencepiece",
                 "imageio", "imageio-ffmpeg", "pillow", "numpy<2", "huggingface_hub")
    .env({"HF_HOME": "/cache/hf"})
)

NEG = ("bright colors, overexposed, static, blurry details, worst quality, low quality, jpeg artifacts, ugly, deformed, "
       "extra fingers, people, text, watermark, subtitles, warping, morphing, cut, flicker, still picture")


@app.cls(image=image, gpu="H200", volumes={"/cache": cache}, timeout=60 * 60, scaledown_window=120, max_containers=10)
class Wan:
    @modal.enter()
    def load(self):
        import torch
        from diffusers import AutoencoderKLWan, WanImageToVideoPipeline
        from transformers import CLIPVisionModel
        enc = CLIPVisionModel.from_pretrained(MODEL, subfolder="image_encoder", torch_dtype=torch.float32)
        vae = AutoencoderKLWan.from_pretrained(MODEL, subfolder="vae", torch_dtype=torch.float32)
        self.pipe = WanImageToVideoPipeline.from_pretrained(MODEL, vae=vae, image_encoder=enc, torch_dtype=torch.bfloat16)
        self.pipe.to("cuda")
        cache.commit()

    @modal.method()
    def clip(self, image_png: bytes, prompt: str, width: int = 1280, height: int = 720, frames: int = 81,
             steps: int = 40, seed: int = 7) -> bytes:
        import io, tempfile, torch
        from PIL import Image
        from diffusers.utils import export_to_video
        img = Image.open(io.BytesIO(image_png)).convert("RGB").resize((width, height), Image.LANCZOS)
        out = self.pipe(image=img, prompt=prompt, negative_prompt=NEG, height=height, width=width, num_frames=frames,
                        num_inference_steps=steps, guidance_scale=5.0,
                        generator=torch.Generator("cuda").manual_seed(seed)).frames[0]
        with tempfile.NamedTemporaryFile(suffix=".mp4") as f:
            export_to_video(out, f.name, fps=16)
            return open(f.name, "rb").read()
