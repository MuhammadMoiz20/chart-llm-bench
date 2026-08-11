"""Turn results/*.jsonl into figures/*.png and results/summary.md.

    python -m bench.analyze
"""

import json
from pathlib import Path

import matplotlib
import matplotlib.ticker
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

matplotlib.use("Agg")
ROOT = Path(__file__).resolve().parents[1]
FIG = ROOT / "figures"
MODELS = {m: c for m, c in json.loads((ROOT / "bench/models.json").read_text()).items() if not c.get("disabled")}
LABEL = {m: c["label"] for m, c in MODELS.items()}
FAMILY = {m: c["family"] for m, c in MODELS.items()}
COLOR = {"open": "#2a78d6", "closed": "#eb6834"}
SURFACE, INK, INK2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e6e5e1"
# Production traffic shape from the Slack estimate: 2 calls/request.
REQUESTS_PER_MONTH = 3000

plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "axes.edgecolor": GRID,
    "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2, "text.color": INK,
    "axes.spines.top": False, "axes.spines.right": False, "axes.grid": True,
    "grid.color": GRID, "grid.linewidth": 0.6, "axes.axisbelow": True,
    "font.family": "DejaVu Sans", "font.size": 11, "axes.titleweight": "bold", "axes.titlesize": 13,
    "figure.dpi": 150, "savefig.bbox": "tight", "savefig.pad_inches": 0.3,
})


def _load(name: str) -> pd.DataFrame:
    rows = [json.loads(l) for p in sorted(ROOT.glob(f"results/{name}*.jsonl")) for l in p.read_text().splitlines()]
    return pd.DataFrame(rows)


def _bar(ax, labels, values, colors, fmt="{:.0%}", xlim=None):
    y = np.arange(len(labels))
    ax.barh(y, values, color=colors, height=0.6)
    ax.set_yticks(y, labels)
    ax.invert_yaxis()
    ax.grid(axis="y", visible=False)
    for i, v in enumerate(values):
        ax.text(v, i, " " + fmt.format(v), va="center", fontsize=10, color=INK)
    if xlim:
        ax.set_xlim(*xlim)


def _legend(ax):
    from matplotlib.patches import Patch
    ax.legend(handles=[Patch(color=COLOR["open"], label="open-weight"), Patch(color=COLOR["closed"], label="closed (Anthropic)")],
              frameon=False, loc="lower right")


def _save(fig, name, caption, y=-0.04):
    fig.text(0.01, y, caption, fontsize=9, color=INK2, ha="left", va="top", wrap=True)
    fig.savefig(FIG / f"{name}.png")
    plt.close(fig)


def main() -> None:
    FIG.mkdir(exist_ok=True)
    sel = _load("selection")
    sel = sel[sel["error"].isna()] if "error" in sel else sel
    # rescore from stored payloads so scorer fixes never need a re-spend
    from bench.run import score_selection, NO_TOOLS
    gold = {it["id"]: it["gold"] for it in json.loads((ROOT / "data/selection.json").read_text())}
    sel = sel[sel["id"].isin(gold)].reset_index(drop=True)
    sel["payload"] = [{k: v for k, v in p.items() if v is not None} if isinstance(p, dict) and m in NO_TOOLS else p for p, m in zip(sel["payload"], sel["model"])]
    scores = pd.DataFrame([score_selection(p, gold[i]) for p, i in zip(sel["payload"], sel["id"])], index=sel.index)
    sel[scores.columns] = scores
    order = [m for m in MODELS if m in set(sel["model"])]
    g = sel.groupby("model")
    summary = pd.DataFrame({
        "label": pd.Series(LABEL), "family": pd.Series(FAMILY),
        "exact": g["exact"].mean(), "template_ok": g["template_ok"].mean(), "schema_valid": g["schema_valid"].mean(),
        "p50_s": g["latency_s"].median(), "p95_s": g["latency_s"].quantile(0.95),
        "in_tok": g["in_tokens"].mean(), "out_tok": g["out_tokens"].mean(), "reasoning_tok": g["reasoning_tokens"].mean(),
        "cost_per_call": g["cost_usd"].mean(),
    }).loc[order]
    # consistency: fraction of questions where all reps gave the same template
    cons = sel.groupby(["model", "id"])["payload"].apply(
        lambda s: len({(p or {}).get("template") for p in s}) == 1).groupby("model").mean()
    summary["consistency"] = cons
    colors = [COLOR[FAMILY[m]] for m in order]
    labels = [LABEL[m] for m in order]

    # 1. headline accuracy
    fig, ax = plt.subplots(figsize=(9, 4.5))
    _bar(ax, labels, summary["exact"].values, colors, xlim=(0, 1.08))
    ax.set_title("Pass 1 — question → chart template: exact-match accuracy")
    ax.set_xlabel("share of answers matching gold (template + range + metrics + clarification)")
    _legend(ax)
    _save(fig, "01_accuracy", f"n = {sel['id'].nunique()} questions × {sel['rep'].max() + 1} reps per model, temperature 0. Scored deterministically against hand-verified labels.")

    # 2. cost vs accuracy pareto
    cap = _load("captions")
    cap_cost = cap[cap["error"].isna()].groupby("model")["cost_usd"].mean() if len(cap) and "error" in cap else cap.groupby("model")["cost_usd"].mean() if len(cap) else pd.Series(dtype=float)
    summary["cost_per_request"] = summary["cost_per_call"] + cap_cost.reindex(order).fillna(summary["cost_per_call"])
    summary["monthly_usd"] = summary["cost_per_request"] * REQUESTS_PER_MONTH
    fig, ax = plt.subplots(figsize=(9, 5.5))
    ax.scatter(summary["cost_per_request"] * 1000, summary["exact"], s=140, c=colors, zorder=3)
    for m in order:
        ax.annotate(LABEL[m], (summary.loc[m, "cost_per_request"] * 1000, summary.loc[m, "exact"]),
                    xytext=(8, 6), textcoords="offset points", fontsize=10)
    ax.set_xscale("log")
    ax.xaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"${v:g}"))
    ax.set_xlim(right=summary["cost_per_request"].max() * 1000 * 3)
    ax.set_xlabel("cost per chart request, USD per 1,000 requests (log scale, both LLM passes)")
    ax.set_ylabel("exact-match accuracy")
    ax.set_ylim(min(0.5, summary["exact"].min() - 0.05), 1.02)
    ax.set_title("The money chart — accuracy vs. cost")
    _legend(ax)
    _save(fig, "02_cost_vs_accuracy", "Up and to the left is better. Cost from actual token usage × Bedrock list price. Each step right is 10× more expensive.")

    # 3. latency
    fig, ax = plt.subplots(figsize=(9, 4.5))
    data = [sel[sel["model"] == m]["latency_s"].values for m in order]
    bp = ax.boxplot(data, vert=False, widths=0.55, patch_artist=True, showfliers=False, medianprops={"color": INK})
    for patch, c in zip(bp["boxes"], colors):
        patch.set(facecolor=c, alpha=0.85, edgecolor="none")
    ax.set_yticks(range(1, len(order) + 1), labels)
    ax.invert_yaxis()
    ax.set_xlabel("seconds per selection call (box = IQR, line = median)")
    ax.set_title("Latency — how long the student waits for pass 1")
    ax.grid(axis="y", visible=False)
    _save(fig, "03_latency", "Measured end-to-end through the LiteLLM proxy from a laptop; includes network. A chart request pays this twice.")

    # 4. per-category heatmap
    cat = sel.pivot_table(index="category", columns="model", values="exact", aggfunc="mean").reindex(columns=order)
    fig, ax = plt.subplots(figsize=(9, 4.5))
    im = ax.imshow(cat.values, cmap=matplotlib.colors.LinearSegmentedColormap.from_list("blue", ["#cde2fb", "#0d366b"]), vmin=0, vmax=1, aspect="auto")
    ax.set_xticks(range(len(order)), labels)
    ax.set_yticks(range(len(cat.index)), cat.index)
    ax.grid(False)
    for i in range(cat.shape[0]):
        for j in range(cat.shape[1]):
            v = cat.values[i, j]
            ax.text(j, i, f"{v:.0%}", ha="center", va="center", fontsize=10, color="white" if v > 0.55 else INK)
    ax.set_title("Where each model breaks — accuracy by question category")
    _save(fig, "04_category_heatmap", "simple = plain single-metric asks · dates = exact/relative date arithmetic · comparison = multi-metric · clarify = must ask back · unsupported = must refuse (incl. prompt injection) · tricky = near-duplicate templates.", y=-0.2)

    # 5. failure modes
    fails = sel[~sel["exact"].astype(bool)].groupby(["model", "fail"]).size().unstack(fill_value=0)
    fails.columns = [c.split(":")[0] for c in fails.columns]
    fails = fails.T.groupby(level=0).sum().T.reindex(order).fillna(0)
    fails = fails.div(sel.groupby("model").size().reindex(order), axis=0)
    fig, ax = plt.subplots(figsize=(9, 4.5))
    left = np.zeros(len(order))
    ramp = ["#0d366b", "#256abf", "#5598e7", "#9ec5f4", "#cde2fb"]
    for k, col in enumerate(fails.columns):
        ax.barh(labels, fails[col].values, left=left, color=ramp[k % len(ramp)], label=col, height=0.6, edgecolor=SURFACE, linewidth=2)
        left += fails[col].values
    ax.invert_yaxis()
    ax.set_xlabel("share of all answers")
    ax.set_title("Failure modes — what went wrong when it went wrong")
    ax.legend(frameon=False, ncol=len(fails.columns), loc="upper center", bbox_to_anchor=(0.5, -0.18), fontsize=9)
    ax.xaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0))
    ax.grid(axis="y", visible=False)
    _save(fig, "05_failure_modes", y=-0.14, caption="partial_date = emitted only one of start/end date, which the server converts into a needless clarification · template = picked the wrong chart · range = right chart, wrong dates/window · clarification = should have asked (or asked needlessly) · invalid = JSON rejected by the schema · no_json = no parseable output.")

    # 6. tokens / reasoning overhead
    fig, ax = plt.subplots(figsize=(9, 4.5))
    y = np.arange(len(order))
    ax.barh(y, summary["out_tok"] - summary["reasoning_tok"], color=colors, height=0.6, label="answer tokens")
    ax.barh(y, summary["reasoning_tok"], left=summary["out_tok"] - summary["reasoning_tok"], color="#c3c2b7", height=0.6, label="hidden reasoning tokens")
    ax.set_yticks(y, labels)
    ax.invert_yaxis()
    ax.set_xlabel("mean output tokens per selection call (you pay for all of them)")
    ax.set_title("Output tokens — reasoning models think out loud on your bill")
    ax.legend(frameon=False)
    ax.grid(axis="y", visible=False)
    _save(fig, "06_output_tokens", "The visible tool call is ~30–50 tokens. Anything above that is reasoning the model does before answering.")

    # 7. consistency
    fig, ax = plt.subplots(figsize=(9, 4.5))
    _bar(ax, labels, summary["consistency"].values, colors, xlim=(0, 1.08))
    ax.set_title("Determinism — same question, same template across reps?")
    ax.set_xlabel("share of questions where every rep picked the same template (temperature 0)")
    _legend(ax)
    _save(fig, "07_consistency", "Temperature 0 is not deterministic on Bedrock. A model that flips its answer on identical input is a support ticket waiting to happen.")

    # 8. captions quality
    judge = _load("judge")
    if len(judge):
        jd = pd.json_normalize(judge["grade"]).assign(model=judge["model"].values)
        jg = jd.groupby("model").agg(faithful=("faithful", "mean"), no_advice=("no_advice", "mean"), useful=("useful", "mean")).reindex(order)
        summary = summary.join(jg)
        fig, axes = plt.subplots(1, 3, figsize=(12, 4.5), sharey=True)
        for ax, (col, title, lim, fmt) in zip(axes, [("faithful", "Faithful to the data", (0, 1.15), "{:.0%}"), ("no_advice", "No advice / no causal claims", (0, 1.15), "{:.0%}"), ("useful", "Usefulness (1–5)", (0, 5.6), "{:.1f}")]):
            _bar(ax, labels, jg[col].values, colors, fmt=fmt, xlim=lim)
            ax.set_title(title, fontsize=12)
        fig.suptitle("Pass 2 — one-sentence chart caption, graded by Claude Sonnet 4.6 against known facts", fontweight="bold")
        _save(fig, "08_caption_quality", f"n = {judge['id'].nunique()} fixtures per model incl. flat, sparse, outlier, opposing-series and prompt-injection cases. Judge sees the raw data and a list of true/forbidden claims.")

    # 9. monthly bill
    fig, ax = plt.subplots(figsize=(9, 4.5))
    _bar(ax, labels, summary["monthly_usd"].values, colors, fmt="${:,.2f}")
    ax.set_xscale("log")
    ax.xaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"${v:g}"))
    ax.set_xlim(right=summary["monthly_usd"].max() * 3)
    ax.set_title(f"Projected monthly bill at {REQUESTS_PER_MONTH:,} chart requests")
    ax.set_xlabel("USD / month (log scale)")
    _legend(ax)
    _save(fig, "09_monthly_bill", "Both passes per request, measured token counts, Bedrock on-demand pricing. Does not include the risk-classifier call, which is model-independent.", y=-0.16)

    # summary.md
    cols = ["label", "family", "exact", "template_ok", "schema_valid", "consistency", "p50_s", "p95_s", "out_tok", "reasoning_tok", "cost_per_request", "monthly_usd"] + [c for c in ("faithful", "no_advice", "useful") if c in summary]
    md = summary[cols].copy()
    for c in ("exact", "template_ok", "schema_valid", "consistency", "faithful", "no_advice"):
        if c in md:
            md[c] = md[c].map("{:.1%}".format)
    md["p50_s"] = md["p50_s"].map("{:.2f}".format); md["p95_s"] = md["p95_s"].map("{:.2f}".format)
    md["cost_per_request"] = md["cost_per_request"].map("${:.5f}".format); md["monthly_usd"] = md["monthly_usd"].map("${:.2f}".format)
    md["out_tok"] = md["out_tok"].round(0).astype(int); md["reasoning_tok"] = md["reasoning_tok"].round(0).astype(int)
    if "useful" in md:
        md["useful"] = md["useful"].map("{:.2f}".format)
    (ROOT / "results/summary.md").write_text(md.to_markdown(index=False) + "\n")
    summary.to_csv(ROOT / "results/summary.csv")
    print(md.to_string(index=False))
    print(f"\ntotal spend: ${sel['cost_usd'].sum() + (cap['cost_usd'].sum() if len(cap) else 0) + (judge['judge_cost_usd'].sum() if len(judge) else 0):.3f}")


def patches() -> None:
    """Figure 10: does the Qwen/Gemma lone-end_date habit yield to a prompt patch or to a code patch?"""
    from bench.run import score_selection
    gold = {it["id"]: it["gold"] for it in json.loads((ROOT / "data/selection.json").read_text())}

    def clean(p):
        return {k: v for k, v in p.items() if v is not None} if isinstance(p, dict) else None

    def code_patch(p):  # server-side: a lone end_date next to range_days is noise, not a range
        if p and p.get("range_days") and p.get("end_date") and not p.get("start_date"):
            p = {k: v for k, v in p.items() if k != "end_date"}
        return p

    def acc(rows, fix=lambda p: p):
        rows = [r for r in rows if r["id"] in gold and r.get("rep") == 0]
        return np.mean([score_selection(fix(clean(r["payload"])), gold[r["id"]])["exact"] for r in rows])

    models = ["qwen.qwen3-32b-v1:0", "google.gemma-3-27b-it", "openai.gpt-oss-120b-1:0", "us.anthropic.claude-sonnet-4-6"]
    rows = {}
    for m in models:
        base = [r for r in _load("selection").to_dict("records") if r["model"] == m]
        var = [r for r in _load("variant-strict_dates").to_dict("records") if r["model"] == m]
        rows[m] = {"baseline": acc(base), "prompt patch": acc(var) if var else np.nan, "code patch": acc(base, code_patch)}
    df = pd.DataFrame(rows).T
    fig, ax = plt.subplots(figsize=(9, 4.5))
    y = np.arange(len(models)); w = 0.26
    for k, (col, c) in enumerate(zip(df.columns, ["#9ec5f4", "#5598e7", "#0d366b"])):
        ax.barh(y + (k - 1) * w, df[col].values, height=w, color=c, label=col)
        for i, v in enumerate(df[col].values):
            if not np.isnan(v):
                ax.text(v, i + (k - 1) * w, f" {v:.0%}", va="center", fontsize=9)
    ax.set_yticks(y, [LABEL[m] for m in models]); ax.invert_yaxis(); ax.set_xlim(0, 1.12)
    ax.xaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0))
    ax.grid(axis="y", visible=False); ax.legend(frameon=False, loc="upper center", bbox_to_anchor=(0.5, -0.18), ncol=3)
    ax.set_title("Fix it in the prompt, or fix it in the code?")
    ax.set_xlabel("exact-match accuracy, rep 0")
    _save(fig, "10_prompt_vs_code_patch", "prompt patch = one extra sentence forbidding lone date fields (re-run, ~$0.02). code patch = server drops a lone end_date when range_days is present (rescored offline, $0). Small models ignore instructions; the code fix is free and model-independent.", y=-0.16)
    df.to_csv(ROOT / "results/patches.csv")
    print(df.round(3))


if __name__ == "__main__":
    main()
    patches()
