"""Greedy (temperature 0) speculative decoding over token ids, with the drafter and the verifier on two machines.

draft(ctx, k)   -> up to k token ids the small model proposes after ctx
verify(ctx, d)  -> (m, nxt): the big model accepts the first m ids of d; nxt is its own next token (the correction at
                   the first miss, or the bonus token after a full accept)
Plain spec: fixed K. Spec+ (the parts of inference/specplus.py that apply to greedy decoding on real servers):
  adaptive K  -> specplus.choose_k, fed with measured acceptance and timings (pass it as `choose`)
  pipelining  -> while a verify is on the wire, the drafter already drafts the next block, assuming a full accept
  free drafts -> specplus.FreeDrafter: tokens copied from earlier in the context, appended after the model draft
The output equals the big model's greedy output by construction (lossless), up to GPU numeric ties.
The loop is pure Python; VLLM below is the small greedy client both Modal boxes use for their own vLLM server
(deploy/modal/spec_modal.py). Everything here is tested offline against a fake server in tests/test_spec_modal.py.
"""
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

EOS = (151645, 151643)  # Qwen3 <|im_end|>, <|endoftext|>


@dataclass
class SpecStats:
    rounds: int = 0
    drafted: int = 0  # model-drafted tokens sent for checking
    accepted: int = 0  # of those, accepted
    misses: int = 0  # rounds that ended on a rejected token (a geometric "failure")
    free_drafted: int = 0
    free_accepted: int = 0
    reused: int = 0  # rounds whose draft came (partly) from a pipelined pre-draft
    draft_ms: float = 0.0  # drafting time on the critical path
    verify_ms: float = 0.0  # verify wall time (network + server)
    ks: list = field(default_factory=list)

    @property
    def alpha(self) -> float:
        """Accepted / drafted (model tokens), the number reported in bench/spec_results.md."""
        return self.accepted / self.drafted if self.drafted else 0.0

    @property
    def alpha_tested(self) -> float:
        """Per-token acceptance a of the geometric model: tokens after a miss were never tested."""
        t = self.accepted + self.misses
        return self.accepted / t if t else 0.0


def spec_generate(draft, verify, prompt_ids, max_tokens, k=4, eos=frozenset(), choose=None, pipeline=False,
                  free=None, kmax=16):
    """choose(stats, k) -> next K (None = fixed K). free(ctx) -> extra free draft tokens (None = off)."""
    ctx, out, st = list(prompt_ids), [], SpecStats()
    pool = ThreadPoolExecutor(2) if pipeline else None  # 2: a stale pre-draft never blocks the next one
    carry: list[int] = []
    try:
        while len(out) < max_tokens:
            room = max_tokens - len(out)
            kk = max(1, min(k, room))
            t0 = time.perf_counter()
            d = carry[:kk]
            if len(d) < kk and not (d and d[-1] in eos):
                d += draft(ctx + d, kk - len(d)) or []
            n_model = len(d)
            if free is not None and n_model and d[-1] not in eos and room > n_model + 1:
                d += list(free(ctx + d))[: room - n_model - 1]
            t1 = time.perf_counter()
            fut = pool.submit(draft, ctx + d, kk) if pool and d and d[-1] not in eos else None
            m, nxt = verify(ctx, d)
            t2 = time.perf_counter()
            carry = []
            if fut is not None and m == len(d):  # pre-draft is valid only after a full accept
                pre = fut.result() or []
                if pre and pre[0] == nxt:
                    carry = pre[1:]
                    st.reused += 1
            new = d[:m] + [nxt]
            for i, t in enumerate(new):  # stop at the first EOS, keep it
                if t in eos:
                    new = new[: i + 1]
                    break
            new = new[:room]
            out += new
            ctx += new
            st.rounds += 1
            st.drafted += n_model
            st.accepted += min(m, n_model)
            st.free_drafted += len(d) - n_model
            st.free_accepted += max(0, m - n_model)
            st.misses += m < len(d)
            st.draft_ms += (t1 - t0) * 1e3
            st.verify_ms += (t2 - t1) * 1e3
            st.ks.append(kk)
            if choose is not None:
                k = max(1, min(kmax, choose(st, k)))
            if new and new[-1] in eos:
                break
    finally:
        if pool:
            pool.shutdown(wait=True)
    return out, st


def make_choose(choose_k, v_node_ms=1.5, kmax=16, warm_rounds=3):
    """Adaptive K from specplus.choose_k, fed with this run's own measured acceptance and per-round times."""

    def choose(st: SpecStats, k: int) -> int:
        if st.rounds < warm_rounds or not st.drafted:
            return k
        t_draft = st.draft_ms / max(1, st.drafted) / 1e3
        v0 = st.verify_ms / st.rounds / 1e3
        return choose_k(st.alpha_tested, t_draft, v0, v_node_ms / 1e3, kmax)

    return choose


# ---------- reading the verifier's prompt logprobs ----------
class IncompleteScores(ValueError):
    pass


def ranked(entry) -> list[tuple[int, float]]:
    """One prompt-logprob row as [(token_id, logprob)], best first. Accepts a {id: {logprob, rank}} dict
    (OpenAI style, keys str, int or 'token_id:N'), a list of {token_id, logprob, rank}, or one such object
    carrying top_logprobs (vLLM tokens-in/tokens-out style)."""
    if entry is None:
        raise IncompleteScores("missing row")
    if isinstance(entry, dict) and "token_id" in entry:
        entry = [entry, *(entry.get("top_logprobs") or [])]
    items = entry.items() if isinstance(entry, dict) else ((e.get("token_id"), e) for e in entry)
    seen = {}
    for tid, v in items:
        v = v if isinstance(v, dict) else {"logprob": v}
        seen[int(str(tid).split(":")[-1])] = (v.get("rank") == 1, v.get("logprob", float("-inf")))
    if not seen:
        raise IncompleteScores("empty row")
    return [(t, k[1]) for t, k in sorted(seen.items(), key=lambda x: x[1], reverse=True)]


def _top1(entry):
    return ranked(entry)[0][0]


def accept_from_prompt_logprobs(pl, n_ctx: int, d: list[int]) -> tuple[int, int | None]:
    """(m, big model's token at the first miss or None) for the prompt ctx+d.

    vLLM returns [None, row_H, ..., row_{n-2}]: H is the prefix-cache hit (0 without one), row_i predicts prompt
    token i+1 (vllm/logprobs.py create_prompt_logprobs; v1/worker/gpu/sample/prompt_logprob.py). So the last len(d)
    entries always score the draft tokens, as long as the hit stops before the draft (H <= n_ctx - 1). It does in this
    loop: ctx ends with the verifier's own token, which no earlier request of the same cache salt had at that place.
    A too-short list or a None entry means the draft rows are missing: IncompleteScores."""
    if not d or len(pl) < len(d):
        raise IncompleteScores(f"{len(pl)} rows for a draft of {len(d)} after {n_ctx} tokens")
    rows = pl[-len(d):]
    for i, t in enumerate(d):
        top = _top1(rows[i])
        if top != t:
            return i, top
    return len(d), None


def strip_eos(ids, eos=frozenset(EOS)):
    ids = list(ids)
    while ids and ids[-1] in eos:
        ids.pop()
    return ids


def first_diff(a, b):
    """Index of the first differing token, or -1 when equal (the lossless check). Trailing EOS is ignored."""
    a, b = strip_eos(a), strip_eos(b)
    for i, (x, y) in enumerate(zip(a, b)):
        if x != y:
            return i
    return -1 if len(a) == len(b) else min(len(a), len(b))


# ---------- greedy client for one local vLLM server ----------
class VLLM:
    """Greedy calls to one vLLM server. transport: tito (/inference/v1/generate, token ids in and out) or openai
    (/v1/completions). fast: the verify request sets skip_reading_prefix_cache=False, so its context is read from
    the prefix cache that the same request salt filled in earlier rounds, and only the new rows are computed (vLLM
    otherwise recomputes the whole prompt for prompt_logprobs). selftest() keeps it only when it matches full
    scoring. Every request carries a cache_salt, so runs never share cache entries. stop: the family's EOS ids."""

    def __init__(self, name, base="http://127.0.0.1:8000", client=None, stop=EOS):
        if client is None:
            import httpx

            client = httpx.Client(timeout=600)
        self.name, self.base, self.c, self.stop = name, base, client, list(stop)
        self.transport, self.fast, self.fallbacks = "tito", False, 0

    def call(self, ids, n, salt, transport=None, **sp):
        t = transport or self.transport
        params = {"max_tokens": n, "temperature": 0.0, "repetition_penalty": 1.0, "stop_token_ids": self.stop, **sp}
        if t == "tito":
            r = self.c.post(self.base + "/inference/v1/generate",
                            json={"token_ids": ids, "sampling_params": params, "cache_salt": salt})
            r.raise_for_status()
            j = r.json()
            return j["choices"][0]["token_ids"], j.get("prompt_logprobs")
        r = self.c.post(self.base + "/v1/completions",
                        json={"model": self.name, "prompt": ids, "return_token_ids": True, "cache_salt": salt, **params})
        r.raise_for_status()
        ch = r.json()["choices"][0]
        return ch["token_ids"], ch.get("prompt_logprobs")

    def gen(self, ids, n, salt):
        return self.call(ids, n, salt)[0]

    def pick_transport(self, ids) -> str:
        """For a server that only drafts: the first transport that answers."""
        for t in ("tito", "openai"):
            try:
                self.call(ids, 1, "pick", t)
                self.transport = t
                return t
            except Exception:  # noqa: BLE001
                continue
        raise RuntimeError("neither /inference/v1/generate nor /v1/completions answers")

    def verify(self, ctx, d, salt, fast=None, transport=None):
        if not d:
            return 0, self.call(ctx, 1, salt, transport)[0][0]
        fast = self.fast if fast is None else fast
        sp = {"prompt_logprobs": 1}
        if fast:
            sp["skip_reading_prefix_cache"] = False
        toks, pl = self.call(ctx + d, 1, salt, transport, **sp)
        try:
            m, miss = accept_from_prompt_logprobs(pl or [], len(ctx), d)
        except IncompleteScores:
            if not fast:
                raise
            self.fallbacks += 1  # a cache hit reached into the draft rows: score this round in full
            return self.verify(ctx, d, salt + ":full", fast=False, transport=transport)
        return m, (miss if m < len(d) else toks[0])

    def top2(self, ctx, salt):
        """The two best next tokens after ctx with their logprobs, from a prefill row (near-tie check)."""
        _, pl = self.call(ctx + [self.stop[0]], 1, salt, prompt_logprobs=2)
        return ranked(pl[-1])[:2]

    def selftest(self, ids) -> dict:
        """Pick the first transport that works; keep the fast verify path only if it agrees with full scoring."""
        rep = {}
        for t in ("tito", "openai"):
            try:
                g = self.call(ids, 24, f"st-{t}-g", t)[0]
                d1 = g[:8]
                d1[5] = 13 if d1[5] != 13 else 14  # a wrong token at position 5
                ctx2, d2 = ids + g[:6], g[6:14]
                plain = [self.verify(ids, d1, f"st-{t}-p", False, t), self.verify(ctx2, d2, f"st-{t}-p", False, t)]
                rep[t] = {"plain": plain, "agrees_with_decode": plain[0] == (5, g[5])}
                try:
                    f0 = self.fallbacks
                    fast = [self.verify(ids, d1, f"st-{t}-f", True, t), self.verify(ctx2, d2, f"st-{t}-f", True, t)]
                    rep[t].update(fast=fast, fast_ok=fast == plain and self.fallbacks == f0)
                except Exception as e:  # noqa: BLE001
                    rep[t].update(fast=repr(e)[:300], fast_ok=False)
                self.transport, self.fast = t, rep[t]["fast_ok"]
                rep["chosen"] = {"transport": t, "fast": self.fast}
                return rep
            except Exception as e:  # noqa: BLE001
                rep[t] = repr(e)[:300]
        raise RuntimeError(f"no verify path works: {rep}")
