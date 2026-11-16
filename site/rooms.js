window.ROOMS = [
  {
    "id": "observatory",
    "art": "room-tower",
    "title": "The Observatory",
    "door": "Live: every call, every token, as it happens.",
    "say": [
      "Welcome to the Observatory. Every call the router handles shows up here as it happens.",
      "Watch the counters, the tier donut and the per-model token ledger. Demo data is labelled as demo."
    ],
    "posters": []
  },
  {
    "id": "crypt",
    "title": "The Crypt",
    "door": "Cache: the cheapest answer is one we already have.",
    "say": [
      "Welcome to the Crypt. Here we keep every answer we have given before.",
      "A call that matches an old one costs nothing and comes back in a blink.",
      "Two lessons came the hard way. Read the last posters."
    ],
    "posters": [
      {
        "at": 0,
        "bats": 2,
        "title": "Cache hits",
        "big": "$0",
        "lines": [
          "8 of 30 calls: 3 exact repeats, 5 paraphrases.",
          "Answered in 0 to 126 ms."
        ],
        "src": [
          "bench/results.md",
          "bench/results.md"
        ]
      },
      {
        "at": 1,
        "bats": 1,
        "title": "Two locks",
        "steps": [
          "exact hash",
          "meaning match"
        ],
        "lines": [
          "Exact match first, then cosine similarity of 0.97 or more.",
          "One SQLite file on disk, or one shared Supabase table. Exact-only mode needs no embedding model."
        ],
        "src": [
          "docs/architecture.md",
          "docs/architecture.md"
        ]
      },
      {
        "at": 2,
        "bats": 3,
        "title": "A lesson",
        "big": "0.94",
        "lines": [
          "At 0.94 the cache served wrong answers (r2 and p4).",
          "At 0.97 the ladder run served no wrong cached answer, and p4 missed the cache and was answered correctly."
        ],
        "src": [
          "bench/results_ladder.md",
          "bench/results_ladder.md"
        ]
      },
      {
        "at": 2,
        "bats": 2,
        "title": "Shared cache",
        "big": "48/60",
        "lines": [
          "A second machine avoided 48 of 60 GPU calls: hit rate 0.80, 0 false hits.",
          "The cost: a lookup took a median 121 ms against 8.9 ms local. At a 150 ms budget it fell back 59 of 60 times."
        ],
        "src": [
          "docs/vector-store.md",
          "docs/vector-store.md"
        ]
      },
      {
        "at": 2,
        "bats": 3,
        "title": "Cache guard",
        "big": "4 \u2192 2",
        "lines": [
          "Wrong hits at 0.97 fell from 4 to 2 on 800 QQP pairs. Recall of duplicates also fell, from 10.1% to 9.1%.",
          "Off by default. Counts are small."
        ],
        "src": [
          "bench/results_research_cache.md",
          "bench/results_research_cache.md"
        ]
      }
    ]
  },
  {
    "id": "ladder",
    "title": "The Ladder",
    "door": "How routing works: climb only when you must.",
    "say": [
      "This is the Ladder. Every call starts on the lowest rung: the shared cache, then our own GPU 30B.",
      "When a draft is not good enough, it climbs one rung. Never more.",
      "Big and small models of one family can also check each other. I will tell you what is proven, and what is not. Mostly it lost."
    ],
    "posters": [
      {
        "at": 0,
        "bats": 3,
        "title": "Four rungs",
        "steps": [
          "shared cache (Supabase)",
          "GPU 30B, self-hosted",
          "H200 120B (optional)",
          "Crusoe 763B"
        ],
        "lines": [
          "The smallest product tier is a 30B model. The Mac 3B is kept only as an experiment, switched off.",
          "Thinking is off on every tier."
        ],
        "src": [
          "docs/architecture.md",
          "docs/architecture.md"
        ]
      },
      {
        "at": 1,
        "bats": 2,
        "title": "Confidence gate",
        "big": "0.95",
        "lines": [
          "The GPU 30B answers alone when its mean token probability is 0.95 or more. Without logprobs, its own self-check decides.",
          "The first benchmarks used a 0.85 gate on a Mac 3B. That 3B is no longer in the product."
        ],
        "src": [
          "chimera.example.toml",
          "chimera.example.toml"
        ]
      },
      {
        "at": 1,
        "bats": 1,
        "title": "Short briefs",
        "big": "200",
        "lines": [
          "Most tokens a heavy-task brief may carry. Or send none.",
          "A long brief plus draft raised GPU tokens by 37%."
        ],
        "src": [
          "bench/results_gpu.md",
          "bench/results_gpu.md"
        ]
      },
      {
        "at": 2,
        "bats": 2,
        "title": "Checked, not resent",
        "steps": [
          "draft",
          "[token_id, logprob]",
          "verify"
        ],
        "lines": [
          "Only token ids and log probabilities cross the wire. Same model family. The verifier must be a llama.cpp server.",
          "Over the internet this was 4.5x to 7x slower than plain Ollama. The round trip alone is about 0.6 s."
        ],
        "src": [
          "bench/spec_results.md",
          "bench/spec_results.md"
        ]
      },
      {
        "at": 2,
        "bats": 3,
        "title": "Spec+",
        "big": "1.14\u20131.22x",
        "lines": [
          "1.14x to 1.22x over the best plain spec at a simulated round trip of 0 to 300 ms.",
          "Against a stand-in target, not a real big model. It still did not beat the big model alone (13.36 against 19.27 tok/s at 150 ms)."
        ],
        "src": [
          "bench/results_specplus.md",
          "bench/results_specplus.md"
        ]
      }
    ]
  },
  {
    "id": "familiar",
    "title": "The Familiar",
    "door": "Phone, Android: a small helper in your pocket.",
    "say": [
      "The Familiar is a small model for your phone.",
      "I must be honest. The setup is written, but no phone has run it yet."
    ],
    "posters": [
      {
        "at": 0,
        "bats": 1,
        "title": "Phone rung",
        "big": "untested",
        "lines": [
          "A Qwen2.5 3B (1.5B on a small phone) through Termux, reached over USB.",
          "Not tested on a phone. There are no phone numbers."
        ],
        "src": [
          "docs/android.md",
          "docs/android.md"
        ]
      },
      {
        "at": 1,
        "bats": 2,
        "title": "The old laptop rung",
        "big": "3B",
        "lines": [
          "In the first benchmark a Qwen2.5-3B on a MacBook answered 14 of 30 prompts alone. 13 of those 14 were right.",
          "It is now an experiment tier, switched off. The product starts at the GPU 30B."
        ],
        "src": [
          "bench/results.md",
          "bench/results.md"
        ]
      }
    ]
  },
  {
    "id": "workshop",
    "art": "room-castle",
    "title": "The Workshop",
    "door": "How Kiro built it: specs, hooks, agents, tests.",
    "say": [
      "This is the Workshop. Kiro built the castle here.",
      "Every count on these posters is read from the .kiro folder, powers/ and tests/ when the site is built."
    ],
    "posters": [],
    "generated": "kiro",
    "clip": false
  },
  {
    "id": "gpus",
    "art": "room-manor",
    "title": "The Manor and The Castle",
    "door": "GPUs: your own box first, then a rented one.",
    "say": [
      "The Manor is your own GPU box. The Castle is the big rented one.",
      "On the Manor's GPU the cascade saved calls and time. But it did not save tokens, and it lost some quality. The Castle's H200 never answered.",
      "Look at the red numbers. They are the truth."
    ],
    "posters": [
      {
        "at": 0,
        "bats": 2,
        "title": "GPU calls",
        "big": "30 \u2192 9",
        "lines": [
          "Qwen3-30B on one V100, against the cascade in front of it.",
          "Median latency fell from 4.9 s to 1.9 s."
        ],
        "src": [
          "bench/results_gpu.md",
          "bench/results_gpu.md"
        ]
      },
      {
        "at": 1,
        "bats": 3,
        "title": "Tokens went up",
        "big": "+37%",
        "lines": [
          "9,334 GPU tokens, against 6,809 for the GPU alone.",
          "The handed-off prompts carried a brief and a draft."
        ],
        "src": [
          "bench/results_gpu.md",
          "bench/results_gpu.md"
        ]
      },
      {
        "at": 2,
        "bats": 2,
        "title": "Quality",
        "big": "20/24",
        "lines": [
          "Passed, against 24 of 24 for the GPU alone.",
          "Misses: r2 and p4 (cache), c3 (local 3B)."
        ],
        "src": [
          "bench/results_gpu.md",
          "bench/results_gpu.md"
        ]
      },
      {
        "at": 2,
        "bats": 1,
        "title": "A slow tail",
        "big": "305 s",
        "lines": [
          "The p90 latency, against 28 s. Four handoffs took about 300 s each.",
          "The cause was not found. Treat it as unreliable."
        ],
        "src": [
          "bench/results_gpu.md",
          "bench/results_gpu.md"
        ]
      },
      {
        "at": 2,
        "bats": 2,
        "title": "The Manor's box",
        "big": "V100",
        "lines": [
          "Qwen3-30B on one rented Tesla V100 (Akash), reached through an SSH tunnel.",
          "It is ours alone. Calls took 25 to 90 s because Ollama ran 149 threads on 4 CPUs. Tuned, the median is 2.7 s."
        ],
        "src": [
          "bench/results_ladder.md",
          "bench/results_akash_tuning.md"
        ]
      },
      {
        "at": 2,
        "bats": 3,
        "title": "The Castle's H200",
        "big": "20x",
        "lines": [
          "gpt-oss-120b on a Modal H200 took every call off the 763B (25 to 0), with 24/24 asserts in both runs. Its first cold start took 376 s.",
          "But 90 s of H200 time cost about $0.11, about 20x the $0.0058 the 763B charged. Median 1,352 ms against 728 ms. Optional, off by default."
        ],
        "src": [
          "bench/results_modal.md",
          "bench/results_modal.md"
        ]
      }
    ]
  },
  {
    "id": "tower",
    "title": "The Tower",
    "door": "Cloud: the biggest model, called last.",
    "say": [
      "The Tower holds the largest model. It is strong, and it is priced by the token.",
      "The cascade sent far fewer calls up here. Whether that made things better depends on what you value.",
      "Then came the ladder run. Only 6 prompts climbed to the 120B model, and 4 to the 763B model."
    ],
    "posters": [
      {
        "at": 0,
        "bats": 2,
        "title": "Cloud calls",
        "big": "30 \u2192 8",
        "lines": [
          "Qwen3.8-27B on Crusoe, against sending all 30 prompts.",
          "Cost at list price: $0.01483 down to $0.01047 (29% lower)."
        ],
        "src": [
          "bench/results.md",
          "bench/results.md"
        ]
      },
      {
        "at": 1,
        "bats": 3,
        "title": "But slower",
        "big": "145 s",
        "lines": [
          "Total wall time, against 31.8 s for cloud only.",
          "Median latency rose from 689 ms to 1,547 ms."
        ],
        "src": [
          "bench/results.md",
          "bench/results.md"
        ]
      },
      {
        "at": 1,
        "bats": 1,
        "title": "Heavy code",
        "big": "$0.00976",
        "lines": [
          "Cascade cost on the 6 heavy coding tasks, against $0.00760.",
          "Brief and draft added input tokens."
        ],
        "src": [
          "bench/results.md",
          "bench/results.md"
        ]
      },
      {
        "at": 2,
        "bats": 2,
        "title": "Top tokens, ladder",
        "big": "45.1%",
        "lines": [
          "Fewer gpt-oss-120b tokens: 14,741 down to 8,087.",
          "6 of 30 prompts reached it."
        ],
        "src": [
          "bench/results_ladder.md",
          "bench/results_ladder.md"
        ]
      },
      {
        "at": 2,
        "bats": 3,
        "title": "Top dollars",
        "big": "40.8%",
        "lines": [
          "Lower: $0.00307 down to $0.00181.",
          "That is only $0.0013 on 30 prompts, because the model is cheap."
        ],
        "src": [
          "bench/results_ladder.md",
          "bench/results_ladder.md"
        ]
      },
      {
        "at": 2,
        "bats": 1,
        "title": "The largest model",
        "big": "763B",
        "lines": [
          "DeepSeek-V4.1-Flash is the biggest on the key. The ladder cut its tokens 65.6% (6,365 to 2,192) and dollars 67.3% ($0.00652 to $0.00213).",
          "Only 4 of 30 prompts reached it. The ladder median was 1.9 s against 0.7 s."
        ],
        "src": [
          "bench/results_ladder.md",
          "bench/results_ladder.md"
        ]
      }
    ]
  },
  {
    "id": "ledger",
    "title": "The Ledger",
    "door": "Results and token savings, with every loss.",
    "say": [
      "The Ledger keeps the true count. Single runs, 30 prompts, no repeats.",
      "We hoped to save 60 to 80% of tokens. Only one count got there, in one run: top-model tokens for the 763B model.",
      "What we did save is calls and money on easy and repeated prompts. Speculation lost."
    ],
    "posters": [
      {
        "at": 0,
        "bats": 2,
        "title": "The target",
        "big": "MIXED",
        "lines": [
          "The goal was 60 to 80% fewer tokens.",
          "Missed on the GPU run (+37%) and for the 120B top model (45.1%). Met only for the 763B top model (65.6%)."
        ],
        "src": [
          "bench/results_ladder.md",
          "bench/results_ladder.md"
        ]
      },
      {
        "at": 1,
        "bats": 2,
        "title": "Cloud tokens",
        "big": "7,229 \u2192 4,599",
        "lines": [
          "Output tokens. But input tokens rose from 1,502 to 5,102.",
          "Cost fell 29%, about $0.004 on 30 prompts."
        ],
        "src": [
          "bench/results.md",
          "bench/results.md"
        ]
      },
      {
        "at": 2,
        "bats": 3,
        "title": "Losses",
        "big": "5/6",
        "lines": [
          "Small coding tasks passed, against 6 of 6.",
          "Cascade wall time was 145 s against 31.8 s."
        ],
        "src": [
          "bench/results.md",
          "bench/results.md"
        ]
      },
      {
        "at": 1,
        "bats": 2,
        "title": "Ladder run",
        "big": "65.6%",
        "lines": [
          "Fewer 763B top-model tokens, 6,365 to 2,192. For the 120B model: 45.1%, 14,741 to 8,087.",
          "Code checks passed 6/6 in every mode. Heavy-code grades were 3.83 (top only) and 4.00 (ladder), one noisy grader."
        ],
        "src": [
          "bench/results_ladder.md",
          "bench/results_ladder.md"
        ]
      },
      {
        "at": 2,
        "bats": 2,
        "title": "Ladder is slower",
        "big": "2.2 s",
        "lines": [
          "Median latency, against 0.88 s calling the 120B model directly. p90 was 46 s against 3.9 s.",
          "The slow calls are the GPU 30B before tuning. A 30B brief cost the same and was 4.4x slower."
        ],
        "src": [
          "bench/results_ladder.md",
          "bench/results_ladder.md"
        ]
      },
      {
        "at": 2,
        "bats": 3,
        "title": "Spec over the net",
        "big": "0.15x",
        "lines": [
          "Plain speculative decoding, 3B drafts and a GPU 30B checks, was 4.5x to 7x slower than plain Ollama (alpha 0.68 at K=4).",
          "The round trip alone was about 0.6 s."
        ],
        "src": [
          "bench/spec_results.md",
          "bench/spec_results.md"
        ]
      },
      {
        "at": 2,
        "bats": 2,
        "title": "Spec+ stand-in",
        "big": "1.2x",
        "lines": [
          "1.14x to 1.22x over the best plain spec, measured against a stand-in target. Not a real big model.",
          "Big model alone: 19.27 tok/s. Spec+: 13.36 tok/s."
        ],
        "src": [
          "bench/results_specplus.md",
          "bench/results_specplus.md"
        ]
      },
      {
        "at": 2,
        "bats": 2,
        "title": "Shared cache",
        "big": "0.80",
        "lines": [
          "48 of 60 GPU calls avoided on a second machine, 0 false hits. Hit rate 0.80.",
          "Lookup median 121 ms against 8.9 ms local. One run."
        ],
        "src": [
          "docs/vector-store.md",
          "docs/vector-store.md"
        ]
      },
      {
        "at": 2,
        "bats": 1,
        "title": "Still unmeasured",
        "big": "GAPS",
        "lines": [
          "Modal H200: one pair of runs only (it lost on cost and speed). Android phone: not tested.",
          "Real Qwen-family Spec+, the short brief, and the GPU tail latency are not measured."
        ],
        "src": [
          "bench/results_modal.md",
          "bench/results_modal.md"
        ]
      }
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
      {
        "at": 0,
        "bats": 2,
        "title": "OpenAI-compatible",
        "steps": [
          "your app",
          "gateway :8088",
          "router"
        ],
        "lines": [
          "Change only base_url and the API key.",
          "Every request goes through the ladder router."
        ],
        "src": [
          "deploy/README.md",
          "deploy/README.md"
        ]
      },
      {
        "at": 1,
        "bats": 1,
        "title": "Keys per tenant",
        "big": "SHA-256",
        "lines": [
          "Only a hash of each key is stored, never the key.",
          "Each tenant has its own cache namespace."
        ],
        "src": [
          "deploy/README.md",
          "deploy/README.md"
        ]
      },
      {
        "at": 2,
        "bats": 2,
        "title": "Prometheus",
        "big": "/metrics",
        "lines": [
          "Text by tenant and tier.",
          "Scrape it from inside your network."
        ],
        "src": [
          "deploy/README.md",
          "deploy/README.md"
        ]
      },
      {
        "at": 2,
        "bats": 3,
        "title": "Action firewall",
        "big": "70+",
        "lines": [
          "Risky actions score 0 to 100. At 70 or more they wait for approval.",
          "It is a rule list and can miss unusual phrasing."
        ],
        "src": [
          "docs/architecture.md",
          "docs/architecture.md"
        ]
      }
    ]
  },
  {
    "id": "gate",
    "art": "gate",
    "title": "The Gate",
    "door": "Get started: four commands and you are in.",
    "say": [
      "You have seen the castle. Now build your own.",
      "Tests are offline. They need no models and no keys.",
      "Good night, and may your tokens be few."
    ],
    "posters": [
      {
        "at": 0,
        "bats": 2,
        "title": "Four commands",
        "steps": [
          "make setup",
          "make test",
          "make serve-local",
          "make demo"
        ],
        "lines": [
          "Setup makes a venv and installs. Tests need no keys.",
          "serve-local starts llama.cpp on 127.0.0.1:8080."
        ],
        "src": [
          "README.md",
          "README.md"
        ]
      },
      {
        "at": 1,
        "bats": 1,
        "title": "Keys stay home",
        "big": ".env",
        "lines": [
          "Cloud keys go in .env (copy .env.example). It is git-ignored.",
          "Models are not in the repo."
        ],
        "src": [
          ".env.example",
          ".env.example"
        ]
      },
      {
        "at": 2,
        "bats": 3,
        "title": "Read more",
        "big": "3 docs",
        "lines": [
          "The HUD shows every call live.",
          "Deploy and architecture notes sit in the repo."
        ],
        "src": [
          "apps/phantom-phone/hud-web/README.md",
          "apps/phantom-phone/hud-web/README.md"
        ]
      }
    ]
  }
];
