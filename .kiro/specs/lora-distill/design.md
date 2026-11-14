# Design: LoRA distillation (planned)

## Flow
```
teacher_pairs (verified, tests passed) -> export + scrub + split -> LoRA train on Akash
   -> adapter -> eval vs base 30B (held-out + suite) -> verdict -> (only if better) serve beside the base
```

## Decisions
- Data comes from the table the memory feature already fills; no new collection step.
- Adapter served beside the base, so the running 30B is never turned off.
- Export code goes under `bench/lora/`; product code is untouched until the eval passes.

## Open
- Serving an adapter on Ollama is not checked. Verify before tasks beyond 2.

## Correctness properties
Router properties are owned by `.kiro/specs/chimera-speculative-os/`.

| ID | Property | Requirement |
|---|---|---|
| P1 | Every exported row has `verified` and `tests_passed` true. | R1.1 |
| P2 | Train and test splits are disjoint, for any seed. | R1.3 |
| P3 | No exported text matches an email, key, JWT or DSN pattern. | R1.2 |
| P4 | The export of tenant A contains no row of tenant B. | R1.2 |
