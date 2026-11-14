import sys, time
from llama_cpp import Llama
t = time.time()
llm = Llama(model_path=sys.argv[1], n_gpu_layers=int(sys.argv[2]), n_ctx=2048, n_batch=512, logits_all=True, verbose=False,
            n_threads=int(sys.argv[3]))
print("load", time.time() - t, flush=True)
ids = [151644, 872, 198, 6023, 151645, 198, 151644, 77091, 198, 9707, 0]
for _ in range(3):
    t = time.time()
    llm.n_tokens = 0
    llm.eval(ids)
    print("eval", len(ids), time.time() - t, flush=True)
