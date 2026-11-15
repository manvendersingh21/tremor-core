import importlib.util
import pathlib
import random

_p = pathlib.Path(__file__).resolve().parents[1] / "bench" / "spec_modal_core.py"
_s = importlib.util.spec_from_file_location("spec_modal_core", _p)
core = importlib.util.module_from_spec(_s)
_s.loader.exec_module(core)

EOS = 0


def target(ctx):  # fake big model: next token is a function of the last two tokens
    return (ctx[-1] * 7 + ctx[-2] * 3 + 1) % 50 if (ctx[-1] + len(ctx)) % 41 else EOS


def make(noise, seed=1):
    rnd = random.Random(seed)

    def draft(ctx, k):
        c, out = list(ctx), []
        for _ in range(k):
            t = target(c) if rnd.random() > noise else rnd.randrange(50)
            out.append(t)
            c.append(t)
        return out

    def verify(ctx, d):
        c = list(ctx)
        for i, t in enumerate(d):
            g = target(c)
            if g != t:
                return i, g
            c.append(t)
        return len(d), target(c)

    return draft, verify


def alone(prompt, n):
    c, out = list(prompt), []
    while len(out) < n:
        t = target(c)
        out.append(t)
        c.append(t)
        if t == EOS:
            break
    return out


def test_lossless_for_any_drafter_and_k():
    for noise in (0.0, 0.3, 1.0):
        for adaptive in (False, True):
            for seed in range(5):
                prompt = [random.Random(seed).randrange(1, 50) for _ in range(5)]
                d, v = make(noise, seed)
                out, st = core.spec_generate(d, v, prompt, 60, k=4, adaptive=adaptive, eos={EOS})
                assert core.first_diff(out, alone(prompt, 60)) == -1
                assert 0 <= st.alpha <= 1


def test_perfect_drafter_needs_fewer_rounds():
    d, v = make(0.0)
    _, st = core.spec_generate(d, v, [3, 4, 5], 40, k=8, eos={EOS})
    d, v = make(1.0)
    _, st_bad = core.spec_generate(d, v, [3, 4, 5], 40, k=8, eos={EOS})
    assert st.rounds < st_bad.rounds


def test_adaptive_k_bounds():
    assert core.adaptive_k(4, 4, 4) == 6
    assert core.adaptive_k(16, 16, 16) == 16
    assert core.adaptive_k(4, 0, 4) == 2
    assert core.adaptive_k(2, 0, 2) == 2
    assert core.adaptive_k(4, 3, 4) == 4
