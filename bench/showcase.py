"""Write docs/side_by_side.md: what each model actually answered, question by question.

    python -m bench.showcase
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODELS = {m: c for m, c in json.loads((ROOT / "bench/models.json").read_text()).items() if not c.get("disabled")}


def _rows(name):
    return [json.loads(l) for p in sorted(ROOT.glob(f"results/{name}*.jsonl")) for l in p.read_text().splitlines()]


def _fmt_sel(p):
    if not p:
        return "*(no JSON)*"
    bits = [p.get("template", "?")]
    if p.get("range_days"): bits.append(f"{p['range_days']}d")
    if p.get("start_date"): bits.append(f"{p['start_date']}→{p.get('end_date')}")
    if p.get("metrics"): bits.append("+".join(p["metrics"]))
    if p.get("clarification"): bits.append(f"ask:{p['clarification']}")
    return "`" + " ".join(bits) + "`"


def main():
    items = json.loads((ROOT / "data/selection.json").read_text())
    sel = {}
    for r in _rows("selection"):
        if r.get("rep") == 0 and "payload" in r:
            sel[(r["model"], r["id"])] = r
    out = ["# Side by side — what every model said\n",
           "Rep 0 of each run. ✅ exact match to gold · ⚠️ right template, wrong range/metrics/clarification · ❌ wrong template or invalid JSON.\n"]
    cols = list(MODELS)
    out.append("## Pass 1 — question → template\n")
    out.append("| # | question | gold | " + " | ".join(MODELS[m]["label"] for m in cols) + " |")
    out.append("|---|---|---|" + "---|" * len(cols))
    for it in items:
        g = it["gold"]
        gold = _fmt_sel({k: v for k, v in g.items() if k != "accept_range_days"})
        cells = []
        for m in cols:
            r = sel.get((m, it["id"]))
            if not r:
                cells.append("—"); continue
            mark = "✅" if r.get("exact") else "⚠️" if r.get("template_ok") else "❌"
            cells.append(f"{mark} {_fmt_sel(r.get('payload'))}")
        out.append(f"| {it['id']} | {it['question'].replace('|', '¦')} | {gold} | " + " | ".join(cells) + " |")

    fixtures = json.loads((ROOT / "data/captions.json").read_text())
    caps = {(r["model"], r["id"]): r for r in _rows("captions")}
    grades = {(r["model"], r["id"]): r.get("grade") or {} for r in _rows("judge")}
    out.append("\n## Pass 2 — the caption each model wrote\n")
    for fx in fixtures:
        out.append(f"### {fx['id']} — *{fx['question']}*\n")
        out.append(f"`{fx['title']}`  \n<sub>{fx['series_digest'].replace(chr(10), '<br>')}</sub>\n")
        out.append("| model | caption | faithful | no advice | useful |")
        out.append("|---|---|---|---|---|")
        for m in cols:
            r = caps.get((m, fx["id"]), {}); g = grades.get((m, fx["id"]), {})
            tick = lambda k: "" if k not in g else ("✅" if g[k] else "❌")
            out.append(f"| {MODELS[m]['label']} | {r.get('insight') or '*(nothing)*'} | {tick('faithful')} | {tick('no_advice')} | {g.get('useful', '')} |")
        out.append("")
    (ROOT / "docs/side_by_side.md").write_text("\n".join(out))
    print("wrote docs/side_by_side.md")


if __name__ == "__main__":
    main()
