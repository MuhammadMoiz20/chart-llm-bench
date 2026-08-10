"""Run the chart-pipeline benchmark against every model on the Bedrock proxy.

    python -m bench.run selection   # pass 1: question -> template
    python -m bench.run captions    # pass 2: series digest -> one-sentence caption
    python -m bench.run judge       # LLM-judge the captions (uses JUDGE_MODEL)

Every call is appended to results/<task>.jsonl as it completes, so a crash or
budget stop loses nothing and re-running skips what's already done.
"""

import json
import os
import re
import sys
import time
from datetime import date
from pathlib import Path

import requests
from dotenv import load_dotenv
from pydantic import ValidationError

from bench.prompts import INSIGHT_PROMPT, INSIGHT_TOOL, SELECTION_PROMPT, SELECTION_TOOL
from bench.schemas import ChartTemplateSelection

load_dotenv(os.getenv("ENV_FILE", ".env"))

ROOT = Path(__file__).resolve().parents[1]
BASE_URL = os.getenv("LLM_PROXY_URL", "https://llm.evergreen-services-staging.dartmouth.edu")
KEY = os.getenv("BEDROCK_KEY", "")  # only needed to call the proxy; analyze imports the scorer without it
TODAY = date(2026, 8, 24)
REPS = int(os.getenv("REPS", "3"))
JUDGE_MODEL = os.getenv("JUDGE_MODEL", "us.anthropic.claude-sonnet-4-6")

MODELS = {m: c for m, c in json.loads((ROOT / "bench/models.json").read_text()).items() if not c.get("disabled")}
if os.getenv("ONLY"):  # run one model per process so models can be benchmarked in parallel
    MODELS = {m: c for m, c in MODELS.items() if m == os.environ["ONLY"]}
SUFFIX = "." + os.environ["ONLY"].split(".")[-1] if os.getenv("ONLY") else ""
# Prompt-patch experiments: PROMPT_VARIANT=<name> appends data/variants/<name>.txt to the selection prompt
# and writes to results/variant-<name>.selection.*.jsonl so the main analysis never sees it.
VARIANT = os.getenv("PROMPT_VARIANT")
if VARIANT:
    SELECTION_PROMPT = SELECTION_PROMPT.replace("QUESTION:", (ROOT / f"data/variants/{VARIANT}.txt").read_text().strip() + "\n\nQUESTION:")
    SUFFIX = f"-{VARIANT}" + SUFFIX
# ponytail: models that reject the `tools` param get the schema pasted into the prompt instead
NO_TOOLS = {m for m, cfg in MODELS.items() if cfg.get("json_mode")}


def chat(model: str, prompt: str, tool: dict, max_tokens: int = 1024) -> dict:
    body = {"model": model, "max_tokens": max_tokens, "temperature": 0,
            "messages": [{"role": "user", "content": prompt}]}
    if model in NO_TOOLS:
        body["messages"][0]["content"] += (
            "\n\nRespond with ONLY a JSON object (no prose, no code fence) matching this schema:\n"
            + json.dumps(tool["function"]["parameters"]))
    else:
        body["tools"] = [tool]
        body["tool_choice"] = {"type": "function", "function": {"name": tool["function"]["name"]}}
    t0 = time.perf_counter()
    r = requests.post(f"{BASE_URL}/chat/completions", json=body, timeout=180,
                      headers={"Authorization": f"Bearer {KEY}"})
    latency = time.perf_counter() - t0
    if r.status_code != 200:
        return {"error": r.text[:500], "latency_s": latency}
    d = r.json()
    msg = d["choices"][0]["message"]
    raw = None
    if msg.get("tool_calls"):
        raw = msg["tool_calls"][0]["function"]["arguments"]
    elif msg.get("content"):
        m = re.search(r"\{.*\}", msg["content"], re.S)
        raw = m.group(0) if m else msg["content"]
    try:
        payload = json.loads(raw) if raw else None
    except json.JSONDecodeError:
        payload = None
    if payload and model in NO_TOOLS:  # no schema enforcement in JSON mode: drop explicit nulls like any integration would
        payload = {k: v for k, v in payload.items() if v is not None}
    u = d.get("usage", {})
    return {"payload": payload, "raw": raw, "latency_s": latency,
            "in_tokens": u.get("prompt_tokens", 0), "out_tokens": u.get("completion_tokens", 0),
            "reasoning_tokens": (u.get("completion_tokens_details") or {}).get("reasoning_tokens", 0)}


def cost_usd(model: str, in_tokens: int, out_tokens: int) -> float:
    p = MODELS[model]["price_per_m"]
    return (in_tokens * p[0] + out_tokens * p[1]) / 1e6


# --------------------------------------------------------------------------
# Pass 1 scoring: deterministic, against the gold label
# --------------------------------------------------------------------------

def _normalize_partial_date(payload: dict) -> dict:  # mirrors production
    has_start = payload.get("start_date") not in (None, "")
    has_end = payload.get("end_date") not in (None, "")
    if has_start == has_end:
        return payload
    return {**payload, "template": "none", "range_days": None, "start_date": None,
            "end_date": None, "metrics": [], "clarification": "date"}


def score_selection(payload: dict | None, gold: dict) -> dict:
    if payload is None:
        return {"schema_valid": False, "template_ok": False, "exact": False, "fail": "no_json"}
    if (payload.get("start_date") in (None, "")) != (payload.get("end_date") in (None, "")) and not gold["clarification"]:
        # production turns a one-ended range into a date clarification; that is its own failure mode
        return {"schema_valid": True, "template_ok": False, "exact": False, "fail": "partial_date"}
    try:
        sel = ChartTemplateSelection.model_validate(_normalize_partial_date(payload))
    except ValidationError as exc:
        return {"schema_valid": False, "template_ok": False, "exact": False,
                "fail": "invalid:" + str(exc).splitlines()[0][:80]}
    template_ok = sel.template.value == gold["template"]
    clar_ok = (sel.clarification.value if sel.clarification else None) == gold["clarification"]
    metrics_ok = sorted(m.value for m in sel.metrics) == sorted(gold["metrics"])
    if gold["start_date"]:
        range_ok = (str(sel.start_date) == gold["start_date"] and str(sel.end_date) == gold["end_date"])
    else:
        range_ok = sel.start_date is None and sel.range_days in set(gold["accept_range_days"]) | {gold["range_days"]}
    exact = template_ok and clar_ok and metrics_ok and (range_ok or gold["template"] == "none")
    fail = None if exact else ("template" if not template_ok else "clarification" if not clar_ok
                               else "metrics" if not metrics_ok else "range")
    return {"schema_valid": True, "template_ok": template_ok, "exact": exact, "fail": fail}


# --------------------------------------------------------------------------
# Runner
# --------------------------------------------------------------------------

def _done(path: Path) -> set[tuple]:
    if not path.exists():
        return set()
    return {(r["model"], r["id"], r["rep"]) for r in map(json.loads, path.read_text().splitlines())}


def run_selection() -> None:
    items = json.loads((ROOT / "data/selection.json").read_text())
    out = ROOT / (f"results/variant{SUFFIX}.jsonl" if VARIANT else f"results/selection{SUFFIX}.jsonl")
    done = _done(out)
    spent = 0.0
    with out.open("a") as f:
        for model in MODELS:
            for it in items:
                for rep in range(REPS):
                    if (model, it["id"], rep) in done:
                        continue
                    prompt = SELECTION_PROMPT.replace("{current_date}", TODAY.isoformat()).replace("{question}", it["question"])
                    res = chat(model, prompt, SELECTION_TOOL)
                    if "error" not in res:
                        res["cost_usd"] = cost_usd(model, res["in_tokens"], res["out_tokens"])
                        spent += res["cost_usd"]
                        res.update(score_selection(res["payload"], it["gold"]))
                    f.write(json.dumps({"model": model, "id": it["id"], "category": it["category"], "rep": rep, **res}) + "\n")
                    f.flush()
            print(f"{model}: done, session spend ${spent:.4f}", file=sys.stderr)


def run_captions() -> None:
    fixtures = json.loads((ROOT / "data/captions.json").read_text())
    out = ROOT / f"results/captions{SUFFIX}.jsonl"
    done = _done(out)
    with out.open("a") as f:
        for model in MODELS:
            for fx in fixtures:
                if (model, fx["id"], 0) in done:
                    continue
                prompt = (INSIGHT_PROMPT.replace("{title}", fx["title"])
                          .replace("{series_digest}", fx["series_digest"]).replace("{question}", fx["question"]))
                res = chat(model, prompt, INSIGHT_TOOL)
                if "error" not in res:
                    res["cost_usd"] = cost_usd(model, res["in_tokens"], res["out_tokens"])
                    ins = (res["payload"] or {}).get("insight")
                    res["insight"] = ins.strip()[:400] if isinstance(ins, str) else None
                f.write(json.dumps({"model": model, "id": fx["id"], "rep": 0, **res}) + "\n")
                f.flush()
            print(f"{model}: captions done", file=sys.stderr)


JUDGE_TOOL = {"type": "function", "function": {"name": "grade", "parameters": {"type": "object", "properties": {
    "faithful": {"type": "boolean", "description": "Every number/claim is supported by the data; nothing invented."},
    "no_advice": {"type": "boolean", "description": "No medical/behavioural advice, no causal inference, no diagnosis."},
    "one_sentence": {"type": "boolean"},
    "useful": {"type": "integer", "minimum": 1, "maximum": 5, "description": "How informative vs. generic."},
    "note": {"type": "string"}}, "required": ["faithful", "no_advice", "one_sentence", "useful", "note"]}}}


def run_judge() -> None:
    fixtures = {f["id"]: f for f in json.loads((ROOT / "data/captions.json").read_text())}
    rows = [json.loads(l) for p in sorted(ROOT.glob("results/captions*.jsonl")) for l in p.read_text().splitlines()]
    out = ROOT / "results/judge.jsonl"
    done = _done(out)
    with out.open("a") as f:
        for r in rows:
            if (r["model"], r["id"], 0) in done:
                continue
            fx = fixtures[r["id"]]
            prompt = (f"You grade a one-sentence chart caption.\n\nDATA:\n{fx['series_digest']}\n\n"
                      f"KNOWN TRUE FACTS: {fx['facts']}\nFORBIDDEN: {fx['forbidden']}\n\n"
                      f"CAPTION: {r.get('insight')!r}\n\nGrade it with the grade tool. A missing/None caption is unfaithful and useful=1.")
            g = chat(JUDGE_MODEL, prompt, JUDGE_TOOL, max_tokens=400)
            f.write(json.dumps({"model": r["model"], "id": r["id"], "rep": 0, "grade": g.get("payload"),
                                "judge_cost_usd": cost_usd(JUDGE_MODEL, g.get("in_tokens", 0), g.get("out_tokens", 0))}) + "\n")
            f.flush()


if __name__ == "__main__":
    {"selection": run_selection, "captions": run_captions, "judge": run_judge}[sys.argv[1]]()
