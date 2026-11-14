# N+1 memory: does the 30B get better when the big model's solved problems are remembered?

Single run, temperature 0, one try per problem (pass@1). All code was graded by running its unit tests in the sandbox (`bench/datasets/grade.py`). Test set: 80 coding problems. Memory is filled from a separate train stream of 260 problems; no problem is in both (checked by prompt text). Near-duplicate families (same concept, different problem) can sit on both sides on purpose.

## Plain words

- The 30B alone solved 68 of 80 (85.0%).
- With the full memory (200 stored big-model solutions) it solved 70 of 80 (87.5%). Memory fixed 3 problems and broke 1.
- With 3 random stored solutions in the same slot (control) it solved 70 of 80 (87.5%). It fixed 2 and broke 0.
- The big model alone solved 75 of 80 (93.8%).
- With these sample sizes the 95% intervals overlap (0.76-0.91 vs 0.78-0.93). Treat differences of a few problems as noise: this is one run of 80 problems.

## Table

| Condition | Pass@1 | 95% CI | Still need big model | Big tokens moved off | Big $ moved off | Avg 30B tokens in/out | Median ms |
|---|---|---|---|---|---|---|---|
| 30B alone (0 stored) | 68/80 (85.0%) | 0.76-0.91 | 12 | 16688 | $0.01169 | 145/165 | 91720 |
| 30B + memory (25 stored) | 71/80 (88.7%) | 0.80-0.94 | 9 | 17608 | $0.0122 | 525/105 | 93599 |
| 30B + memory (50 stored) | 70/80 (87.5%) | 0.78-0.93 | 10 | 17657 | $0.01216 | 697/112 | 87731 |
| 30B + memory (100 stored) | 69/80 (86.3%) | 0.77-0.92 | 11 | 16960 | $0.0118 | 748/136 | 94510 |
| 30B + memory (200 stored) | 70/80 (87.5%) | 0.78-0.93 | 10 | 17480 | $0.01211 | 766/128 | 108366 |
| CONTROL: 30B + 3 random stored solutions (200 stored) | 70/80 (87.5%) | 0.78-0.93 | 10 | 17518 | $0.01214 | 792/147 | 128798 |
| Big model alone (DeepSeek-V4.1-Flash) | 75/80 (93.8%) |  | - | 0 | $0 | / | 879 |

"Still need big model" = test problems the 30B failed, which a router would send up. "Moved off" = what the big model would have cost on the problems the 30B solved itself (big model on all 80: 21998 tokens, $0.0160).

## Learning curve (pass@1 vs stored solutions)

```
   0 stored | ##########################################         68/80 85.0%
  25 stored | ############################################       71/80 88.7%
  50 stored | ############################################       70/80 87.5%
 100 stored | ###########################################        69/80 86.3%
 200 stored | ############################################       70/80 87.5%
ctrl random | ############################################       70/80 87.5%
```

## Control: is it the memory or just a longer prompt?

Same slot, same size cap, but the 3 examples are random stored solutions instead of retrieved ones. Control 70/80 vs memory 70/80 vs none 68/80. Memory changed 3 up and 1 down; random examples changed 2 up and 0 down.

## Tokens and dollars

- Big-model cost to fill memory: $0.0363 on 260 train problems (200 passed and were stored). Extraction of concepts used the 30B itself (200 calls, 63912 tokens, $0 in cloud money).
- Extra 30B input per test call from memory: about 621 tokens on average (80 of 80 calls had a memory context).
- Big-model $ moved off at full memory: $0.01211 vs $0.01169 with no memory, out of $0.0160 for sending every test problem to the big model.
- The memory cost is paid once; the saving repeats on every later similar problem. At these prices the fill cost is larger than the saving on 80 test problems, so break-even needs more traffic than this test.

## Where memory did not help

| Source | n | 30B alone | 30B + full memory | Control |
|---|---|---|---|---|
| custom | 13 | 11 | 11 | 11 |
| humaneval | 30 | 27 | 27 | 27 |
| mbpp | 37 | 30 | 32 | 32 |

- Broken by memory (1): sql-left_join_none.
- Still failing with memory and also failed by the big model: humaneval-163, mbpp-164, mbpp-438, mbpp-430, mbpp-143.
- Failed by the 30B with and without memory, solved by the big model: 4.

## Stores

Real stores written from the same 200 verified answers: `Neo4jGraphStore` for the graph (teacher pairs in Supabase). Stats: `{"problem": 200, "solution": 200, "concept": 368, "pattern": 200, "error": 0, "edges": 1138, "teacher_pairs": 200, "stored_this_session": 200, "rejected_this_session": 0, "tenant": "bench-n1"}`. Top-1 retrieval agreed with the in-memory run on 20 of 20 test problems. The curve above used the in-memory store (same code path).

## Rerun

```
# open an SSH tunnel to your GPU box and to Neo4j first; CRUSOE_API_KEY, CHIMERA_DB_URL, CHIMERA_GRAPH_* in .env
.venv/bin/python bench/memory/run_memory.py all
N_TEST=80 W30=4 .venv/bin/python bench/memory/run_memory.py report
```

Rows are cached under `bench/.scratch/memory/`; delete a file there to redo that condition. Setup: `docs/memory.md`. Caveats: one run, temperature 0, 80 problems; the 30B box is shared, so latency numbers are noisy.
