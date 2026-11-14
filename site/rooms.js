window.ROOMS = [
  {
    "id": "crypt",
    "title": "The Crypt",
    "door": "Cache: the cheapest answer is one we already have.",
    "say": [
      "Welcome to the Crypt. Here we keep every answer we have given before.",
      "A call that matches an old one costs nothing and comes back in a blink.",
      "One lesson was learned the hard way. Read the last poster."
    ],
    "posters": [
      {"at": 0, "bats": 2, "title": "Cache hits", "big": "$0",
       "lines": ["8 of 30 calls: 3 exact repeats, 5 paraphrases.", "Answered in 0 to 126 ms."],
       "src": ["bench/results.md", "bench/results.md"]},
      {"at": 1, "bats": 1, "title": "Two locks", "steps": ["exact hash", "meaning match"],
       "lines": ["Exact match first, then cosine similarity of 0.97 or more.", "One SQLite file on disk. Exact-only mode needs no embedding model."],
       "src": ["docs/architecture.md", "docs/architecture.md"]},
      {"at": 2, "bats": 3, "title": "A lesson", "big": "0.94",
       "lines": ["At this threshold the cache served wrong answers (r2 and p4).", "The threshold is now 0.97. That fix is not yet measured."],
       "src": ["bench/results_gpu.md", "bench/results_gpu.md"]}
    ]
  },
  {
    "id": "ladder",
    "title": "The Ladder",
    "door": "How routing works: climb only when you must.",
    "say": [
      "This is the Ladder. Every call starts on the lowest rung.",
      "When a draft is not good enough, it climbs one rung. Never more.",
      "Big and small models of one family can also check each other. I will tell you what is proven, and what is not."
    ],
    "posters": [
      {"at": 0, "bats": 3, "title": "Six rungs", "steps": ["crypt cache", "phone", "laptop", "small GPU", "big GPU", "cloud tower"],
       "lines": ["The phone rung is planned, not built.", "Thinking is off on every tier."],
       "src": ["docs/architecture.md", "docs/architecture.md"]},
      {"at": 1, "bats": 2, "title": "Confidence gate", "big": "0.85",
       "lines": ["The laptop 3B answers alone when mean token probability is 0.85 or more.", "Heavy tasks skip the 3B."],
       "src": ["bench/results.md", "bench/results.md"]},
      {"at": 1, "bats": 1, "title": "Short briefs", "big": "200",
       "lines": ["Most tokens a heavy-task brief may carry. Or send none.", "A long brief plus draft raised GPU tokens by 37%."],
       "src": ["bench/results_gpu.md", "bench/results_gpu.md"]},
      {"at": 2, "bats": 2, "title": "Checked, not resent", "steps": ["draft", "[token_id, logprob]", "verify"],
       "lines": ["Only token ids and log probabilities cross the wire. Same model family. The verifier must be a llama.cpp server.", "Not measured yet, so no speedup is claimed."],
       "src": ["docs/architecture.md", "docs/architecture.md"]}
    ]
  },
  {
    "id": "familiar",
    "title": "The Familiar",
    "door": "Phone, Android: a small helper in your pocket.",
    "say": [
      "The Familiar is a small model that would live on your phone.",
      "I must be honest. It is planned, and none of it is built yet."
    ],
    "posters": [
      {"at": 0, "bats": 1, "title": "Phone rung", "big": "planned",
       "lines": ["A Gemma 3 1B or 4B model on Android is the plan.", "No phone code is built."],
       "src": ["docs/architecture.md", "docs/architecture.md"]},
      {"at": 1, "bats": 2, "title": "What runs today", "big": "3B",
       "lines": ["Qwen2.5-3B (q4_k_m) on llama.cpp, on a MacBook.", "It answered 14 of 30 prompts alone. 13 of those 14 were right."],
       "src": ["bench/results.md", "bench/results.md"]}
    ]
  },
  {
    "id": "gpus",
    "title": "The Manor and The Castle",
    "door": "GPUs: your own box first, then a rented one.",
    "say": [
      "The Manor is your own GPU box. The Castle is the big rented one.",
      "On the GPU the cascade saved calls and time. But it did not save tokens, and it lost some quality.",
      "Look at the red numbers. They are the truth."
    ],
    "posters": [
      {"at": 0, "bats": 2, "title": "GPU calls", "big": "30 \u2192 9",
       "lines": ["Qwen3-30B on one V100, against the cascade in front of it.", "Median latency fell from 4.9 s to 1.9 s."],
       "src": ["bench/results_gpu.md", "bench/results_gpu.md"]},
      {"at": 1, "bats": 3, "title": "Tokens went up", "big": "+37%",
       "lines": ["9,334 GPU tokens, against 6,809 for the GPU alone.", "The handed-off prompts carried a brief and a draft."],
       "src": ["bench/results_gpu.md", "bench/results_gpu.md"]},
      {"at": 2, "bats": 2, "title": "Quality", "big": "20/24",
       "lines": ["Passed, against 24 of 24 for the GPU alone.", "Misses: r2 and p4 (cache), c3 (local 3B)."],
       "src": ["bench/results_gpu.md", "bench/results_gpu.md"]},
      {"at": 2, "bats": 1, "title": "A slow tail", "big": "305 s",
       "lines": ["The p90 latency, against 28 s. Four handoffs took about 300 s each.", "The cause was not found. Treat it as unreliable."],
       "src": ["bench/results_gpu.md", "bench/results_gpu.md"]}
    ]
  },
  {
    "id": "tower",
    "title": "The Tower",
    "door": "Cloud: the biggest model, called last.",
    "say": [
      "The Tower holds the largest model. It is strong, and it is priced by the token.",
      "The cascade sent far fewer calls up here. Whether that made things better depends on what you value."
    ],
    "posters": [
      {"at": 0, "bats": 2, "title": "Cloud calls", "big": "30 \u2192 8",
       "lines": ["Qwen3.8-27B on Crusoe, against sending all 30 prompts.", "Cost at list price: $0.01483 down to $0.01047 (29% lower)."],
       "src": ["bench/results.md", "bench/results.md"]},
      {"at": 1, "bats": 3, "title": "But slower", "big": "145 s",
       "lines": ["Total wall time, against 31.8 s for cloud only.", "Median latency rose from 689 ms to 1,547 ms."],
       "src": ["bench/results.md", "bench/results.md"]},
      {"at": 1, "bats": 1, "title": "Heavy code", "big": "$0.00976",
       "lines": ["Cascade cost on the 6 heavy coding tasks, against $0.00760.", "Brief and draft added input tokens."],
       "src": ["bench/results.md", "bench/results.md"]}
    ]
  },
  {
    "id": "ledger",
    "title": "The Ledger",
    "door": "Results and token savings, with every loss.",
    "say": [
      "The Ledger keeps the true count. Single runs, 30 prompts, no repeats.",
      "We hoped to save 60 to 80% of tokens. We did not.",
      "What we did save is calls and money on easy and repeated prompts."
    ],
    "posters": [
      {"at": 0, "bats": 2, "title": "The target", "big": "not met",
       "lines": ["The goal was 60 to 80% fewer tokens.", "No run reached it."],
       "src": ["README.md", "README.md"]},
      {"at": 1, "bats": 2, "title": "Cloud tokens", "big": "7,229 \u2192 4,599",
       "lines": ["Output tokens. But input tokens rose from 1,502 to 5,102.", "Cost fell 29%, about $0.004 on 30 prompts."],
       "src": ["bench/results.md", "bench/results.md"]},
      {"at": 2, "bats": 3, "title": "Losses", "big": "5/6",
       "lines": ["Small coding tasks passed, against 6 of 6.", "Cascade wall time was 145 s against 31.8 s."],
       "src": ["bench/results.md", "bench/results.md"]},
      {"at": 2, "bats": 1, "title": "Still unmeasured", "big": "2 GAPS",
       "lines": ["No speculative-verify speedup. bench/spec_results.md does not exist yet.", "No cold-load time for the GPU model."],
       "src": ["bench/run_spec.py", "bench/run_spec.py"]}
    ]
  },
  {
    "id": "guild",
    "title": "The Guild",
    "door": "For companies: the gateway, keys and metrics.",
    "say": [
      "The Guild is for companies. Run your own hardware first.",
      "Your apps keep their OpenAI SDK. They change one address and one key.",
      "Each tenant gets its own keys, and Prometheus can watch it all."
    ],
    "posters": [
      {"at": 0, "bats": 2, "title": "OpenAI-compatible", "steps": ["your app", "gateway :8088", "router"],
       "lines": ["Change only base_url and the API key.", "Every request goes through the ladder router."],
       "src": ["deploy/README.md", "deploy/README.md"]},
      {"at": 1, "bats": 1, "title": "Keys per tenant", "big": "SHA-256",
       "lines": ["Only a hash of each key is stored, never the key.", "Each tenant has its own cache namespace."],
       "src": ["deploy/README.md", "deploy/README.md"]},
      {"at": 2, "bats": 2, "title": "Prometheus", "big": "/metrics",
       "lines": ["Text by tenant and tier.", "Scrape it from inside your network."],
       "src": ["deploy/README.md", "deploy/README.md"]},
      {"at": 2, "bats": 3, "title": "Action firewall", "big": "70+",
       "lines": ["Risky actions score 0 to 100. At 70 or more they wait for approval.", "It is a rule list and can miss unusual phrasing."],
       "src": ["docs/architecture.md", "docs/architecture.md"]}
    ]
  },
  {
    "id": "gate",
    "title": "The Gate",
    "door": "Get started: four commands and you are in.",
    "say": [
      "You have seen the castle. Now build your own.",
      "Tests are offline. They need no models and no keys.",
      "Good night, and may your tokens be few."
    ],
    "posters": [
      {"at": 0, "bats": 2, "title": "Four commands", "steps": ["make setup", "make test", "make serve-local", "make demo"],
       "lines": ["Setup makes a venv and installs. Tests need no keys.", "serve-local starts llama.cpp on 127.0.0.1:8080."],
       "src": ["README.md", "README.md"]},
      {"at": 1, "bats": 1, "title": "Keys stay home", "big": ".env",
       "lines": ["Cloud keys go in .env (copy .env.example). It is git-ignored.", "Models are not in the repo."],
       "src": [".env.example", ".env.example"]},
      {"at": 2, "bats": 3, "title": "Read more", "big": "3 docs",
       "lines": ["The HUD shows every call live.", "Deploy and architecture notes sit in the repo."],
       "src": ["apps/phantom-phone/hud-web/README.md", "apps/phantom-phone/hud-web/README.md"]}
    ]
  }
];
