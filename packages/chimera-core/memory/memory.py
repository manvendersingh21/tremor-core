"""N+1 memory: verified big-model solutions in, similar solutions and their key ideas out."""
from __future__ import annotations

import math
import re
import time
import logging
from dataclasses import dataclass, field
from typing import Callable

from .extract import heuristic_extract
from .graph import GraphStore, Pair
from .safety import scrub

log = logging.getLogger("chimera.memory")
MAX_CONTEXT_TOKENS = 800
MIN_SCORE = 0.30          # below this a "similar" problem is not shown
HALF_LIFE_S = 30 * 86400  # recency halves every 30 days
SIMILAR_AT = 0.80         # problem-problem similar_to edge threshold
GRAPH_COOLDOWN_S = 60.0   # after a graph error, skip the graph this long (an unreachable Aura cost 10 s per call)


def est_tokens(text: str) -> int:
    return max(1, len(text) // 4)  # shortcut: chars/4 estimate, not a tokenizer; upgrade if the cap must be exact


@dataclass
class Example:
    problem: str
    solution: str
    why: str
    score: float = 0.0


@dataclass
class MemoryContext:
    examples: list[Example] = field(default_factory=list)
    concepts: list[str] = field(default_factory=list)

    def render(self, max_tokens: int = MAX_CONTEXT_TOKENS) -> str:
        """Prompt text, cut so it stays at or under `max_tokens`. Empty string when memory has nothing."""
        if not self.examples and not self.concepts:
            return ""
        head = "Notes from earlier solved problems (verified). Use the ideas if they fit; solve the new task yourself.\n"
        if self.concepts:
            head += "Useful ideas: " + ", ".join(self.concepts) + "\n"
        out, used = head, est_tokens(head)
        for i, e in enumerate(self.examples, 1):
            block = f"\nExample {i}\nProblem: {e.problem}\nSolution:\n{e.solution}\nWhy it works: {e.why}\n"
            room = (max_tokens - used) * 4
            if room < 200:
                break
            if len(block) > room:  # shrink the problem text first, then the solution; keep the idea line
                p = e.problem[: max(80, room // 5)]
                s = e.solution[: max(120, room - len(p) - len(e.why) - 60)]
                block = f"\nExample {i}\nProblem: {p}\nSolution:\n{s}\nWhy it works: {e.why}\n"
                if len(block) > room:
                    break
            out += block
            used += est_tokens(block)
        return out

    @property
    def tokens(self) -> int:
        return est_tokens(self.render()) if self.render() else 0


class Memory:
    def __init__(self, store: GraphStore, embedder, tenant: str = "default",
                 extractor: Callable[[str, str], tuple[list[str], str]] = heuristic_extract,
                 max_tokens: int = MAX_CONTEXT_TOKENS, min_score: float = MIN_SCORE) -> None:
        self.graph, self.embedder, self.tenant = store, embedder, tenant
        self.extractor, self.max_tokens, self.min_score = extractor, max_tokens, min_score
        self.rejected = 0
        self.stored = 0
        # After a graph error the graph is skipped for GRAPH_COOLDOWN_S. Without it an Aura that never answers
        # cost every call the driver's 10 s connect timeout (bench/results_backend_v3.md).
        self._graph_down_until = 0.0

    def _graph_up(self) -> bool:
        return time.monotonic() >= self._graph_down_until

    def _graph_failed(self, what: str, e: Exception) -> None:
        self._graph_down_until = time.monotonic() + GRAPH_COOLDOWN_S
        log.warning("memory: %s (%s); graph skipped for %.0f s", what, type(e).__name__, GRAPH_COOLDOWN_S)

    def _emb(self, text: str) -> list[float]:
        v = [float(x) for x in self.embedder.embed(text)]
        n = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / n for x in v]

    # -- write ---------------------------------------------------------------------------------------------
    def store(self, prompt: str, answer: str, model: str, tier: str, verified: bool,
                     tests: bool | None, tokens: dict | None = None, score: float | None = None) -> int | None:
        """Store a teacher pair and graph nodes. Returns the pair id, or None when the answer is not verified.

        Verified means unit tests passed (`tests=True`) or a blind grader gave `score` >= 4 of 5. `verified=True`
        with neither is refused: the flag alone is not trusted."""
        ok = bool(verified) and (tests is True or (tests is None and score is not None and score >= 4))
        if not ok or not answer.strip() or not prompt.strip():
            self.rejected += 1
            return None
        prompt, answer = scrub(prompt), scrub(answer)
        tk = tokens or {}
        t = self.tenant
        pe = self._emb(prompt)
        try:
            pid = self.graph.add_pair(t, Pair(prompt, answer, model, tier, True, tests, int(tk.get("in", 0)),
                                              int(tk.get("out", 0))), pe)
        except Exception as e:  # noqa: BLE001  never fail the caller's request because the teacher store is down
            log.warning("memory: teacher pair not saved (%s)", type(e).__name__)
            pid = 0
        if not self._graph_up():
            self.stored += 1
            return pid
        try:
            concepts, why = self.extractor(prompt, answer)
            w = 1.0 if tests is True else min(1.0, (score or 4) / 5)
            prob = self.graph.add_node(t, "problem", prompt, pe)
            sol = self.graph.add_node(t, "solution", answer, self._emb(answer))
            self.graph.add_edge(t, sol, prob, "solves", w)
            pat = self.graph.add_node(t, "pattern", scrub(why), self._emb(why))
            self.graph.add_edge(t, pat, sol, "part_of", w)
            for c in concepts[:5]:
                c = scrub(c)
                cid = self.graph.find_node(t, "concept", c)
                if cid is None:
                    cid = self.graph.add_node(t, "concept", c, self._emb(c))
                self.graph.add_edge(t, sol, cid, "uses", w)
            for other, sim in self.graph.nearest(t, "problem", pe, 4):
                if other.id != prob and sim >= SIMILAR_AT:
                    self.graph.add_edge(t, prob, other.id, "similar_to", sim)
        except Exception as e:  # noqa: BLE001  the pair is saved; only the graph part is skipped
            self._graph_failed("graph write skipped", e)
        self.stored += 1
        return pid

    # -- read ----------------------------------------------------------------------------------------------
    def retrieve(self, prompt: str, k: int = 3) -> MemoryContext:
        """Three signals: (a) nearest stored problems, (b) 1-2 hop expansion over shared concepts,
        (c) rank = similarity x edge weight x recency."""
        if not self._graph_up():
            return MemoryContext()
        try:
            return self._retrieve(prompt, k)
        except Exception as e:  # noqa: BLE001  graph down: no memory context for this call, the call itself goes on
            self._graph_failed("graph skipped for this call", e)
            return MemoryContext()

    def _retrieve(self, prompt: str, k: int) -> MemoryContext:
        t, now = self.tenant, time.time()
        pe = self._emb(scrub(prompt))
        seeds = self.graph.nearest(t, "problem", pe, max(k * 3, 6))
        if not seeds:
            return MemoryContext()
        score: dict[int, float] = {}   # problem id -> score
        text: dict[int, str] = {}
        for n, sim in seeds:
            score[n.id], text[n.id] = sim, n.text
        # hop 1: problem -> solution(s) -> concepts and why-patterns
        e1 = self.graph.neighbors(t, list(score))
        sol_of: dict[int, tuple[int, str, float]] = {}  # problem id -> (solution id, text, edge weight)
        sol_nodes = {}
        for ed, a, b in e1:
            if ed.rel == "solves" and b.id in score:
                if b.id not in sol_of or ed.weight > sol_of[b.id][2]:
                    sol_of[b.id] = (a.id, a.text, ed.weight)
                sol_nodes[a.id] = b.id
        e2 = self.graph.neighbors(t, list(sol_nodes)) if sol_nodes else []
        concept_w: dict[int, float] = {}
        concept_text: dict[int, str] = {}
        why_of: dict[int, str] = {}
        for ed, a, b in e2:
            if ed.rel == "uses" and a.id in sol_nodes:
                concept_w[b.id] = concept_w.get(b.id, 0.0) + score[sol_nodes[a.id]] * ed.weight
                concept_text[b.id] = b.text
            elif ed.rel == "part_of" and b.id in sol_nodes:
                why_of[b.id] = a.text
        # hop 2: concept -> other solutions that use it -> their problems (shared idea, different problem)
        if concept_w:
            top = sorted(concept_w, key=lambda c: -concept_w[c])[:6]
            e3 = self.graph.neighbors(t, top)
            new_sols = {a.id: concept_w[b.id] for ed, a, b in e3 if ed.rel == "uses" and b.id in top}
            e4 = self.graph.neighbors(t, list(new_sols)) if new_sols else []
            for ed, a, b in e4:
                if ed.rel == "solves" and a.id in new_sols:
                    score[b.id] = max(score.get(b.id, 0.0), 0.5 * min(1.0, new_sols[a.id]) * self._base(seeds))  # 2 hops: decayed
                    text[b.id] = b.text
                    sol_of[b.id] = (a.id, a.text, ed.weight)
                    sol_nodes[a.id] = b.id
            ids = [s for s in new_sols if s in sol_nodes]
            for ed, a, b in (self.graph.neighbors(t, ids) if ids else []):
                if ed.rel == "part_of" and b.id in sol_nodes:
                    why_of[b.id] = a.text
        age = {n.id: now - n.created_at for n, _ in seeds}
        ranked = []
        for pid, s in score.items():
            if pid not in sol_of or s < self.min_score:
                continue
            rec = 0.5 + 0.5 * 0.5 ** (age.get(pid, 0.0) / HALF_LIFE_S)
            ranked.append((s * (0.5 + 0.5 * sol_of[pid][2]) * rec, pid))
        ranked.sort(reverse=True)
        ex = [Example(text[pid], sol_of[pid][1], why_of.get(sol_of[pid][0], ""), sc) for sc, pid in ranked[:k]]
        names = [concept_text[c] for c in sorted(concept_w, key=lambda c: -concept_w[c])[:5]]
        return MemoryContext(ex, names if ex else [])

    @staticmethod
    def _base(seeds) -> float:
        return seeds[0][1]

    def stats(self) -> dict:
        s = self.graph.stats(self.tenant)
        s.update(stored_this_session=self.stored, rejected_this_session=self.rejected, tenant=self.tenant)
        return s

    def purge(self) -> int:
        """Delete everything this tenant has stored (pairs, nodes, edges)."""
        return self.graph.purge(self.tenant)
