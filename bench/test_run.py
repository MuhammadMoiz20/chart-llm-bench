"""Smallest check that fails if the scorer breaks: python -m bench.test_run"""
import os
from bench.run import score_selection, _normalize_partial_date

gold = {"template": "sleep_trend", "range_days": 14, "accept_range_days": [14], "start_date": None, "end_date": None, "metrics": [], "clarification": None}
assert score_selection({"template": "sleep_trend", "range_days": 14, "reason": "r"}, gold)["exact"]
assert score_selection({"template": "sleep_trend", "range_days": 7, "reason": "r"}, gold)["fail"] == "range"
assert score_selection({"template": "steps_trend", "reason": "r"}, gold)["fail"] == "template"
assert score_selection({"template": "sleep_trend", "bogus": 1, "reason": "r"}, gold)["fail"].startswith("invalid")
assert score_selection(None, gold)["fail"] == "no_json"
assert _normalize_partial_date({"template": "sleep_trend", "start_date": "2026-08-01"})["clarification"] == "date"
gold_cmp = {"template": "comparison", "range_days": None, "accept_range_days": [None, 7], "start_date": None, "end_date": None, "metrics": ["sleep", "mood"], "clarification": None}
assert score_selection({"template": "comparison", "metrics": ["mood", "sleep"], "reason": "r"}, gold_cmp)["exact"]
print("ok")
assert score_selection({"template": "steps_trend", "end_date": "2026-08-24", "range_days": 30, "reason": "r"}, gold)["fail"] == "partial_date"
