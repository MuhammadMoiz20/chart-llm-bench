# Testing strategy

**Goal.** Pick the cheapest model that is *reliable enough* to sit in front of a student, for the two LLM calls in the Evergreen chart pipeline. Not "which model is smartest" — which model is the sweet spot for *this* job.

## Why a task-specific benchmark instead of MMLU/LMArena

The chart pipeline is deliberately narrow: the model never writes SQL, never invents a chart, never sees more than a few hundred tokens. Pass 1 is a 9-way classification with date arithmetic; pass 2 is a one-sentence caption over ≤90 numbers. Public leaderboards measure none of that, and a 120B model that aces GPQA can still emit `range_days: 10` or an invalid tool call. So the benchmark **replays the exact production prompts and tool schemas** (`bench/prompts.py`, `bench/schemas.py` are lifted verbatim from the backend) and scores against the same Pydantic validator the server uses.

## Design principles

1. **Deterministic scoring wherever possible.** Pass 1 has a gold label, so it's scored by code, not by an LLM judge. Only pass 2 (free text) uses a judge, and the judge is handed the raw data plus a list of true and forbidden claims so it's checking facts, not vibes.
2. **Adversarially verified labels.** Questions were authored per category, then a separate skeptic pass re-derived each label from the prompt rules and *dropped* any item two careful readers could disagree on (6 of 60 dropped — the drop log is in `data/dropped.md`). A benchmark with ambiguous gold measures the labeler, not the model.
3. **Categories that map to product failure modes**, not to difficulty tiers:
   | category | what breaks in production if this fails |
   |---|---|
   | simple | the happy path — if this isn't ~100%, stop here |
   | dates | wrong window → chart of the wrong week, silently |
   | comparison | wrong metric list → wrong series, silently |
   | clarify | model guesses instead of asking → confident wrong chart |
   | unsupported | model charts something we don't track, or obeys a prompt injection |
   | tricky | near-duplicate templates (mood_trend vs mood_calendar, steps vs weekly_recap) |
4. **Repetitions at temperature 0.** Bedrock isn't deterministic; each question runs 3× so we can measure *consistency* separately from accuracy. A model that's 90% right but flips answers on identical input is worse than one that's 88% and stable.
5. **Cost from measured tokens, not estimates.** Every row records prompt/completion/reasoning tokens and the price-table cost. Reasoning models bill hidden tokens — the benchmark makes that visible.
6. **Latency end-to-end through the proxy**, because that's what the student waits for. Both passes run per request, so p50 × 2 is the real number.
7. **Budget-safe by construction.** Results are appended per call to JSONL; re-running skips completed rows. Total spend for the full sweep is reported by `bench.analyze`. The whole study cost under $5 of a $100 cap.

## What is *not* measured (yet)

- Long-context behaviour — irrelevant here, prompts are <1K tokens.
- The risk-classifier call — model-independent in this comparison.
- Models not yet on the proxy (Qwen3-235B, DeepSeek V3.1, Kimi K2, Llama 4, gpt-oss-20b). Adding one is one line in `bench/models.json`.

## Reproduce

```
uv sync
ENV_FILE=path/to/.env uv run python -m bench.run selection   # ~$2.5, ~5 min in parallel (ONLY=<model>)
ENV_FILE=path/to/.env uv run python -m bench.run captions
ENV_FILE=path/to/.env uv run python -m bench.run judge
uv run python -m bench.analyze                                  # figures/ + results/summary.md
```
