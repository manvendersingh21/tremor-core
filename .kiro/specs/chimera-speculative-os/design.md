# Technical Architecture & System Design: CHIMERA-OS

## 1. End-to-End Cascade Architecture
```mermaid
sequenceDiagram
    participant User as Surface (Phone DND / Kiro IDE)
    participant FW as Quarantine Risk Firewall
    participant T1 as Tier 1: Semantic Cache (sqlite-vec)
    participant T2 as Tier 2: Local Draft (Gemma 1B/4B or Qwen 3B)
    participant T3 as Tier 3: Cloud Verifier (Gemma 27B / Qwen 30B)
    participant Tools as Execution (PhoneUse MCP / ElevenLabs / Tavily)

    User->>T1: Incoming Prompt / UI Screen State / File Diff
    alt Cosine Similarity >= 0.94 (e.g., "Capital of France?" or known UI button)
        T1-->>User: Instant Cached Answer (<5ms, 0 GPU/Cloud Tokens)
    else Cache Miss
        T1->>T2: Forward to Local Model (Warm Prefix KV Cache)
        T2->>T2: Generate K Draft Tokens + Compute Logprob Entropy
        alt Mean Token Confidence >= 0.85
            T2->>T1: Store in Semantic Cache
            T2-->>FW: Proposed Action / Response (0 Cloud Tokens)
        else Entropy Spike (Complex Code / Negotiation)
            T2->>T3: Stream K Draft Token IDs + Logprobs p_d(x)
            T3->>T3: Parallel 1-Pass Verification + Rejection Sampling
            T3-->>FW: Lossless 27B/30B Verified Response
        end
    end
    FW->>FW: Score Blast Radius (0-100)
    alt Risk Score < 70
        FW->>Tools: Execute PhoneUse Tap / Voice Reply / GitHub PR
    else Risk Score >= 70 (Pay / Delete / Merge)
        FW->>User: Trigger ElevenLabs Voice / SMS Approval Gate
    end