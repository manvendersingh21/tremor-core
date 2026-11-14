# Requirements: LoRA distillation

**Status: planned. No code exists in the tree.** The user paused it for Mac memory. Training data source exists: Supabase `teacher_pairs` (`docs/memory.md`). Related research: DistillSpec in `docs/research.md`.

Intent: fine-tune the self-hosted 30B with a LoRA adapter on verified big-model answers, so it needs the 763B less often.

## Requirements

### R1 Training data
1. THE dataset SHALL come only from `teacher_pairs` rows with `verified` true and `tests_passed` true.
2. THE export SHALL be scrubbed and tenant-scoped, and SHALL NOT contain keys, DSNs or personal data.
3. THE export SHALL hold out a test split that training never sees.

### R2 Where it runs
1. TRAINING SHALL run on the Akash box. It SHALL NOT run on the Mac.
2. TRAINING SHALL NOT stop the running Ollama `qwen3:30b-instruct` or other apps there.

### R3 Evaluation before use
1. THE adapter SHALL be compared with the base 30B on the held-out split and on the real-dataset suite, pass rate and tokens, with losses reported.
2. THE adapter SHALL NOT replace the base model in the ladder unless it beats the base on pass rate.

### R4 Reproducible record
1. THE run SHALL write `bench/results_lora.md` with data size, hyperparameters, hardware, time and a verdict that names failures.
