# Items dropped by the label-verification pass

- **simple_10** — Ambiguous: 'recently' -> mood_trend/30, but 'since midterms started' is a 'since DATE' that cannot be resolved, which the prompt says maps to none + clarification date. Careful readers would split.
- **dates_05** — Prompt never says whether 'last N days' includes today; 2026-08-15 (inclusive) and 2026-08-14 (exclusive) are both defensible. Drop.
- **dates_06** — Same inclusivity ambiguity: 3 weeks back could be 2026-08-03 or 2026-08-04. Drop.
- **comparison_08** — Dropped: 'sleep vs everything else u track' is genuinely split between comparison (all four metrics) and weekly_recap; the prompt also says prefer none when guessing. The author's own rationale concedes models will pick weekly_recap. Two careful readers would disagree.
- **clarify_04** — Genuinely ambiguous: 'my stuff for last week' reads as a broad week overview (weekly_recap) to many careful readers, vs metric clarification. Drop.
- **clarify_08** — Both metric and date are unclear; prompt gives no precedence rule, so 'metric' vs 'date' is a coin flip between careful readers. Drop.
- **comparison_07** — 'last 10 days': same inclusive/exclusive ambiguity as dates_05/06 (Sonnet answered 08-14, gold said 08-15). Dropped after the run for consistency; its rows are ignored by the analysis.
