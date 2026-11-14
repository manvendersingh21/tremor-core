# Semantic cache false-hit guard (MeanCache idea, arXiv 2403.02694)

Data: 800 real QQP validation pairs (296 duplicates, 504 non-duplicates), MiniLM cosine.
A hit on a non-duplicate pair is a wrong answer served from cache. Single run, no repeats.
QQP labels are noisy: some 'duplicates' would not share an answer, so true precision is lower than shown.

| threshold | guard | hits | correct hits | wrong hits (false hits) | false-hit rate | recall of duplicates |
|---|---|---|---|---|---|---|
| 0.85 | off | 263 | 196 | 67 | 25.5% | 66.2% |
| 0.85 | on | 156 | 130 | 26 | 16.7% | 43.9% |
| 0.9 | off | 172 | 135 | 37 | 21.5% | 45.6% |
| 0.9 | on | 113 | 96 | 17 | 15.0% | 32.4% |
| 0.94 | off | 92 | 79 | 13 | 14.1% | 26.7% |
| 0.94 | on | 70 | 63 | 7 | 10.0% | 21.3% |
| 0.97 | off | 34 | 30 | 4 | 11.8% | 10.1% |
| 0.97 | on | 29 | 27 | 2 | 6.9% | 9.1% |
