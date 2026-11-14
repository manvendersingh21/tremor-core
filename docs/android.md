# Android phone tier (`phone-3b`)

The phone runs a small Qwen model. The Mac reaches it over USB. Nothing is exposed to the internet.

## Pick a model by RAM

| Phone RAM | Model | File size |
|---|---|---|
| 6 GB or more | Qwen2.5-3B-Instruct q4_k_m | about 2 GB |
| under 6 GB | Qwen2.5-1.5B-Instruct q4_k_m | about 1 GB |

Qwen matches the GPU model family (`family = "qwen"`), so speculative verify can work. Gemma cannot verify against Qwen.

## Option A (primary): Termux + llama.cpp

1. Install Termux from F-Droid. The Play Store build is outdated.
2. Run `scripts/android_setup.sh` on the Mac (add `1.5b` for a small phone). It prints the Termux commands: install tools, build `llama-server`, download the model, start the server on the phone's `127.0.0.1:8080`.
3. Paste those commands into Termux, in order. Keep Termux open. `termux-wake-lock` stops Android from sleeping it.
4. Connect (below), then run `scripts/phone_check.sh`.
5. In `chimera.toml`, set `enabled = true` on `phone-3b`. If you use 1.5B, set `model` to match.

## Option B: Google AI Edge / MediaPipe, Gemma 3 1B

1. Use the MediaPipe LLM Inference sample app from Google AI Edge. Load a Gemma 3 1B `.task` model.
2. Gemma has its own vocabulary. It cannot draft for a Qwen verifier, so use it only as a stand-alone tier with `family = "gemma"`.
3. The app does not serve llama.cpp's HTTP API. You need a small wrapper that serves `/completion` and `/health`, or the tier will not work with `backend = "llamacpp"`.

## Connect safely

USB (preferred). The server stays bound to the phone's loopback:

```
adb devices
adb forward tcp:8081 tcp:8080     # Mac 127.0.0.1:8081 -> phone 8080
curl 127.0.0.1:8081/health
```

`scripts/phone_check.sh` runs these. To reach a Mac service from the phone instead, use `adb reverse tcp:PORT tcp:PORT`.

Wi-Fi (only if USB is not possible):

1. Start the server with `--host 0.0.0.0 --api-key <long random token>` and use it on a trusted LAN only.
2. Send the token as `Authorization: Bearer <token>`. Keep the token out of git.
3. Do not port-forward the router. Do not use a public network.

## Check

`scripts/phone_check.sh` prints `adb devices`, sets the forward and calls `/health`. With no `adb` or no device it says so and exits 0.
