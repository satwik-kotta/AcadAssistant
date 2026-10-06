# Retrieval chunk-size experiment

Does cutting the chunk size from 1,000 to 500 characters help the assistant find the right passage?

**Answer: no measurable difference. The app keeps 1,000-character chunks.**

This is a randomized offline experiment on retrieval only. No users took part, so it is not an A/B test of user behaviour.

## Result

350 queries, 175 randomly assigned to each arm. Both arms retrieve the same amount of text (5,000 characters).

| | Control: 1,000 chars, 150 overlap | Treatment: 500 chars, 75 overlap | Difference | p-value |
|---|---|---|---|---|
| **Hit rate with 5,000 chars of context (primary)** | 80.0% | 79.4% | −0.6 pts (95% CI −9.0 to +7.9) | 0.89 |
| Hit rate with 2,000 chars | 68.0% | 70.3% | +2.3 pts | 0.64 (Holm 0.64) |
| Hit rate with 1,000 chars | 53.1% | 62.3% | +9.1 pts | 0.08 (Holm 0.17) |

A hit means one retrieved chunk contains the whole target sentence.

The interval on the primary metric excludes a change of 10 points in either direction, which was the smallest effect set in advance as worth acting on. Smaller chunks look better when very little context is retrieved, but that difference is not significant after correcting for two secondary tests.

## Design

1. **Queries.** Every eligible sentence in three PDFs in `uploads/` becomes one query: a random 60% of its content words, in order. The sentence's position is the ground truth. 411 sentences qualified.
2. **Pilot.** 60 queries, used only to estimate the control hit rate (72%). They take no part in the experiment.
3. **Sample size.** Detecting a 10-point change at α = 0.05 with 80% power needs 278 queries per arm.
4. **Randomization.** The remaining queries are split at random, half to each arm. Each query is scored under its own arm only.
5. **Analysis.** Two-proportion z-test with Wald and bootstrap intervals on the primary metric; Holm correction across the secondary metrics; a likelihood-ratio test for a document-by-arm interaction.

The seed, metrics, α, power and minimum effect are constants at the top of `experiment.py`.

## Checks

| Check | Result |
|---|---|
| Group sizes | 175 and 175 |
| Sentence length balanced across arms | p = 0.92 |
| Document mix balanced across arms | p = 0.99 |
| A/A test: both groups get the control, 2,000 re-randomizations | Rejects 5.2% of the time (5% expected) |

## By document (exploratory)

| Document | Control | Treatment | n per arm |
|---|---|---|---|
| China CBDC report | 66.7% | 86.0% | 42, 43 |
| Long-run risks paper | 83.1% | 77.8% | 118, 117 |
| OCR manuscripts paper | 93.3% | 73.3% | 15, 15 |

The interaction test gives p = 0.02, so the effect may differ by document. This was not a planned test and the groups are small. It is a reason to rerun on more documents, not a finding.

## Paired comparison, for reference

Because this is offline, every query can also be scored under both arms. That paired comparison gives 80.3% against 78.6% (McNemar p = 0.62), the same conclusion. A paired design is the more efficient choice offline; the between-query design is used here because it is the one that carries over to a test on real users.

## Limits

- **Underpowered against the plan.** The plan called for 278 queries per arm and the corpus supplied 175. Power to detect a 10-point change was 60%; the smallest change detectable at 80% power was 12.5 points.
- **Two things changed after a first run.** The sentence filter was loosened because the first version produced only 275 queries. A secondary metric (characters read before the hit) was dropped because it favours smaller chunks by construction. The primary metric, α, power, minimum effect and seed did not change.
- **Synthetic queries.** Queries are built from the target sentence's own words, so they share its vocabulary. Real student questions would be harder.
- **Offline embedder.** The test uses the app's local hash embeddings (`LocalHashEmbeddings`), which run without an API key. The app prefers Gemini embeddings when a key is set, and results could differ with them.
- **Three documents, about 110,000 characters.**

## Run it

```bash
pip install langchain-core langchain-text-splitters faiss-cpu pypdf scipy statsmodels pandas pytest
python -m experiments.retrieval_ab.experiment      # writes results.json, about 5 seconds
python -m pytest -q experiments/retrieval_ab       # 5 tests
```
