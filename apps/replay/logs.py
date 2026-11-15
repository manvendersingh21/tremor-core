"""Read request logs: OpenAI-style JSONL (messages, model, usage) or CSV. Pure parsing, no network."""
from __future__ import annotations

import csv
import json
import pathlib
import random
from dataclasses import dataclass


@dataclass
class Req:
    id: str
    prompt: str                  # what the router sees: the last user turn, earlier turns prepended
    model: str | None = None
    tokens_in: int | None = None   # from the log's usage when present, else None (estimated later)
    tokens_out: int | None = None
    sys_chars: int = 0           # system prompt length; counted in the input tokens, not sent to the router


def _text(content) -> str:
    if isinstance(content, list):  # OpenAI content parts
        return "\n".join(p.get("text", "") for p in content if isinstance(p, dict) and p.get("type", "text") == "text")
    return content if isinstance(content, str) else ""


def render(messages: list[dict]) -> tuple[str, int]:
    """(prompt, system chars). One user turn -> that text. A conversation -> earlier turns as 'role: text' lines, then the last user turn.
    shortcut: the system prompt is not sent to the router (a shared system prompt would swamp cosine similarity); upgrade if a log's system prompt varies per request."""
    sys_chars = sum(len(_text(m.get("content"))) for m in messages if m.get("role") in ("system", "developer"))
    turns = [(m.get("role", ""), _text(m.get("content")).strip()) for m in messages if m.get("role") not in ("system", "developer")]
    turns = [t for t in turns if t[1]]
    last = max((i for i, t in enumerate(turns) if t[0] == "user"), default=None)
    if last is None:
        return "", sys_chars
    head = "\n".join(f"{r}: {t}" for r, t in turns[:last])
    return (f"{head}\nuser: {turns[last][1]}" if head else turns[last][1]), sys_chars


def _int(v) -> int | None:
    try:
        return int(float(v)) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _from_obj(d: dict, i: int) -> Req | None:
    body = d.get("body") or d.get("request") or d  # OpenAI batch lines nest the request under "body"
    resp = d.get("response") or {}
    resp = resp.get("body", resp) if isinstance(resp, dict) else {}
    usage = body.get("usage") or d.get("usage") or resp.get("usage") or {}
    if isinstance(body.get("messages"), list):
        prompt, sc = render(body["messages"])
    else:
        prompt, sc = str(body.get("prompt") or ""), 0
    if not prompt.strip():
        return None
    return Req(id=str(d.get("id") or d.get("custom_id") or i), prompt=prompt, model=body.get("model") or d.get("model"),
               tokens_in=_int(usage.get("prompt_tokens", usage.get("input_tokens"))),
               tokens_out=_int(usage.get("completion_tokens", usage.get("output_tokens"))), sys_chars=sc)


def _from_row(r: dict, i: int) -> Req | None:
    r = {k.strip().lower(): v for k, v in r.items() if k}
    if r.get("messages"):
        try:
            prompt, sc = render(json.loads(r["messages"]))
        except ValueError:
            return None
    else:
        prompt, sc = (r.get("prompt") or "").strip(), len(r.get("system") or "")
    if not prompt:
        return None
    pick = lambda *ks: next((r[k] for k in ks if r.get(k) not in (None, "")), None)  # noqa: E731
    return Req(id=str(pick("id", "request_id") or i), prompt=prompt, model=pick("model"),
               tokens_in=_int(pick("prompt_tokens", "input_tokens", "tokens_in")),
               tokens_out=_int(pick("completion_tokens", "output_tokens", "tokens_out")), sys_chars=sc)


def load(path: str | pathlib.Path, sample: int | None = None, seed: int = 0) -> tuple[list[Req], int]:
    """(requests, skipped lines). Bad lines and lines with no user text are counted, not fatal. `sample` keeps a seeded random subset in file order."""
    p = pathlib.Path(path)
    reqs: list[Req] = []
    skipped = 0
    if p.suffix.lower() == ".csv":
        with open(p, newline="", encoding="utf-8") as fh:
            items = [("row", r) for r in csv.DictReader(fh)]
    else:
        items = []
        for line in p.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                items.append(("obj", json.loads(line)))
            except ValueError:
                skipped += 1
    for i, (kind, d) in enumerate(items):
        r = (_from_row if kind == "row" else _from_obj)(d, i) if isinstance(d, dict) else None
        if r is None:
            skipped += 1
        else:
            reqs.append(r)
    if sample and sample < len(reqs):
        keep = sorted(random.Random(seed).sample(range(len(reqs)), sample))
        reqs = [reqs[i] for i in keep]
    return reqs, skipped


def est_tokens(text: str) -> int:
    return max(len(text) // 4, 1)  # same len/4 estimate the router uses for tokens_saved
