# Tasks: LoRA distillation

Built so far: nothing. Data table `teacher_pairs` exists in `deploy/sql/005_memory.sql`.

- [ ] 1. Export script from `teacher_pairs` with scrub and split (R1): `bench/lora/export.py`, offline test with fakes
- [ ] 2. Check that Ollama on the Akash box can serve a LoRA adapter (R2)
- [ ] 3. Train on the Akash box (R2)
- [ ] 4. Evaluate adapter vs base (R3)
- [ ] 5. `bench/results_lora.md` (R4)
