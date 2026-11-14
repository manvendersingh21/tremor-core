# Technical Architecture & System Design: CHIMERA

## 1. Tier ladder
```mermaid
flowchart TD
    Q[Prompt] --> FW0[Firewall: score action 0-100]
    Q --> C{Exact or semantic cache >= 0.97}
    C -- hit --> A[Answer, 0 tokens]
    C -- miss --> H{Heavy task?}
    H -- no --> L[Tier 1 Mac: Qwen2.5-3B, llama.cpp, logprobs]
    L -- confidence >= 0.85 and check passes --> A
    L -- low confidence or failed check --> G[Tier 2 GPU: Ollama qwen3:30b-instruct, SSH tunnel]
    H -- yes, skip 3B --> G
    G -- ok --> A
    G -- heavy or ESCALATE or failed check --> T[Tier 3 Crusoe: Qwen3.8-27B / gpt-oss-120b]
    T --> A
    A --> S[Store in cache + emit telemetry]
```

## 2. Two ways a heavy task reaches a bigger model
```mermaid
flowchart LR
    subgraph BP["Brief path (built)"]
      B1[Heavy prompt] --> B2[No brief, or brief <= 200 tokens] --> B3[Bigger model answers alone]
    end
    subgraph VP["Verify path (runner built, not measured)"]
      V1[Mac 3B drafts K tokens] -- token ids + logprobs --> V2[llama.cpp verifier, same family]
      V2 -- accepted ids + correction --> V1
    end
```
- Brief path: works on any API. A long brief raised GPU tokens by 37% (`bench/results_gpu.md`), so it is capped.
- Verify path: needs a llama.cpp verifier on the GPU box (`bench/verify_server.py`). Ollama gives no prompt logprobs. Crusoe rejects `echo`. Same model family on both sides. No KV tensors cross the network.

## 3. Action firewall
Every proposed GUI or CLI action gets a score from 0 to 100 (`firewall/risk_scorer.py`). Below 70 it runs. At 70 or more it waits for a one-time token sent back by voice or SMS. Rule-based, so unusual phrasing can slip through.

## 4. Surfaces
- Kiro: `apps/kiro-trimmer/` (`cli.py`, `mcp_server.py`, `hook_interceptor.py`).
- HUD: static HTML plus Python SSE server reading the telemetry JSONL.
- Phone agent: planned.
