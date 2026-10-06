"""Markdown/JSON report and PNG chart."""

from __future__ import annotations

import json
from pathlib import Path

from aiops_sim import __version__
from aiops_sim.engine import PipelineResult
from aiops_sim.generator import Scenario
from aiops_sim.metrics import Evaluation

LABEL = "SIMULATION RESULT ON SYNTHETIC DATA - not a measurement of any real environment"
DISCLAIMER = ("Representative portfolio project built with synthetic data. "
              "Not derived from any employer or client code.")

# Reference palette (light surface); single hue for magnitude, neutral for the baseline.
SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_2 = "#52514e"
GRID = "#e4e3df"
SERIES = "#2a78d6"
BASELINE = "#a3a29c"


def _fmt_minutes(seconds: int) -> str:
    h, rem = divmod(seconds, 3600)
    return f"{h:02d}:{rem // 60:02d}"


def to_markdown(scenario: Scenario, result: PipelineResult, ev: Evaluation, chart_name: str | None) -> str:
    out = [
        "# AIOps Event Correlation - Simulation Report",
        "",
        f"> **{LABEL}.**",
        f"> {DISCLAIMER}",
        "",
        f"- Scenario: {scenario.hours} h of synthetic monitoring traffic, seed `{scenario.seed}`, "
        f"{ev.true_incidents} injected incidents",
        f"- Engine version: {__version__}",
        "",
    ]
    if chart_name:
        out += [f"![Alert funnel and simulated MTTR]({chart_name})", ""]
    out += [
        "## Alert funnel",
        "",
        "| Stage | Count |",
        "|---|---|",
        f"| Raw alert events (triggers) | {ev.raw_alerts} |",
        f"| After de-duplication | {ev.deduplicated_alerts} |",
        f"| After flap suppression (active, non-flapping) | {ev.after_flap_suppression} "
        f"(+{ev.flapping_suppressed} flapping alerts suppressed) |",
        f"| Correlated alert groups | {ev.correlated_groups} |",
        f"| Actionable incidents (score >= threshold) | {ev.actionable_incidents} |",
        "",
        f"**Noise reduction (raw events -> actionable incidents): {ev.noise_reduction_pct}%** "
        f"(de-duplication alone: {ev.dedup_reduction_pct}%).",
        "",
        "## Quality against ground truth",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Injected incidents detected as actionable | {ev.incidents_detected} / {ev.true_incidents} |",
        f"| Mean groups per incident (1.0 = never fragmented) | {ev.mean_fragments_per_incident} |",
        f"| Group purity (events in a group sharing its dominant label) | {ev.group_purity_pct}% |",
        f"| Root cause: top-1 candidate correct | {ev.rca_top1_accuracy_pct}% |",
        f"| Root cause: correct within top-3 | {ev.rca_top3_accuracy_pct}% |",
        f"| Actionable groups that were really noise (false positives) | {ev.noise_groups_actionable} |",
        "",
        "## Simulated MTTR",
        "",
        "| | Mean minutes |",
        "|---|---|",
        f"| Baseline (operators work from raw alerts) | {ev.mttr_baseline_min} |",
        f"| With correlation + root-cause hint | {ev.mttr_aiops_min} |",
        f"| Improvement | {ev.mttr_improvement_pct}% |",
        "",
        "Model assumptions (minutes) - change them in `MttrAssumptions`:",
        "",
    ]
    out += [f"- `{k}` = {v}" for k, v in ev.assumptions.items()]
    out += [
        "- Fix time per incident is drawn at random (15-60 min) and is identical in both arms.",
        "",
        "## Per-incident detail",
        "",
        "| Incident | True root | Raw events | Groups | Priority | Top candidate | Top-1 hit "
        "| MTTR base | MTTR AIOps |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for p in ev.per_incident:
        out.append(f"| {p['incident']} | {p['root_node']} | {p['raw_alerts']} | {p['groups']} | "
                   f"{p['priority'] or '-'} | {p['top_candidate'] or '-'} | "
                   f"{'yes' if p['rca_top1'] else 'no'} | {p['mttr_baseline_min']} | {p['mttr_aiops_min']} |")
    out += ["", "## Actionable incidents (highest priority first)", "",
            "| Group | Start (hh:mm) | Priority | Score | Alerts | Raw events | Services "
            "| Root-cause candidates |",
            "|---|---|---|---|---|---|---|---|"]
    for g in sorted(result.actionable, key=lambda g: (-g.score, g.start)):
        cands = ", ".join(f"{c.node}{' (inferred)' if c.inferred else ''} {c.coverage:.0%}"
                          for c in g.candidates)
        services = ", ".join(g.impacted_services[:3]) + (" ..." if len(g.impacted_services) > 3 else "")
        out.append(f"| {g.group_id} | {_fmt_minutes(g.start)} | {g.priority} | {g.score} | "
                   f"{len(g.alerts)} | {g.raw_count} | {services or '-'} | {cands} |")
    out += ["", f"_{LABEL}._", ""]
    return "\n".join(out)


def to_json(scenario: Scenario, result: PipelineResult, ev: Evaluation) -> dict:
    return {
        "label": LABEL,
        "disclaimer": DISCLAIMER,
        "version": __version__,
        "scenario": {"hours": scenario.hours, "seed": scenario.seed,
                     "incidents": [vars(i) for i in scenario.incidents]},
        "evaluation": ev.to_dict(),
        "actionable_groups": [
            {"group_id": g.group_id, "start_s": g.start, "priority": g.priority, "score": g.score,
             "nodes": g.nodes, "raw_events": g.raw_count, "impacted_services": g.impacted_services,
             "candidates": [vars(c) for c in g.candidates]}
            for g in result.actionable
        ],
    }


def render_chart(ev: Evaluation, path: Path) -> Path:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    stages = ["Raw alert events", "After de-duplication", "After flap suppression",
              "Correlated groups", "Actionable incidents"]
    values = [ev.raw_alerts, ev.deduplicated_alerts, ev.after_flap_suppression,
              ev.correlated_groups, ev.actionable_incidents]

    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10})
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 4.4), gridspec_kw={"width_ratios": [1.7, 1]})
    fig.patch.set_facecolor(SURFACE)
    for ax in (ax1, ax2):
        ax.set_facecolor(SURFACE)
        for side in ("top", "right", "left"):
            ax.spines[side].set_visible(False)
        ax.spines["bottom"].set_color(GRID)
        ax.tick_params(colors=INK_2, length=0)

    y = list(range(len(stages)))[::-1]
    ax1.barh(y, values, color=SERIES, height=0.6, edgecolor=SURFACE, linewidth=2)
    ax1.set_yticks(y, stages, color=INK)
    ax1.xaxis.grid(True, color=GRID, linewidth=0.8)
    ax1.set_axisbelow(True)
    for yi, v in zip(y, values, strict=True):
        ax1.text(v + max(values) * 0.01, yi, f"{v:,}", va="center", color=INK, fontsize=10)
    ax1.set_xlim(0, max(values) * 1.12)
    ax1.set_title(f"Alert funnel: {ev.noise_reduction_pct}% noise reduction",
                  loc="left", color=INK, fontsize=12, fontweight="bold")
    ax1.set_xlabel("Count", color=INK_2)

    labels = ["Baseline", "Correlated + RCA hint"]
    mttr = [ev.mttr_baseline_min, ev.mttr_aiops_min]
    ax2.bar(labels, mttr, color=[BASELINE, SERIES], width=0.55, edgecolor=SURFACE, linewidth=2)
    ax2.yaxis.grid(True, color=GRID, linewidth=0.8)
    ax2.set_axisbelow(True)
    for xi, v in enumerate(mttr):
        ax2.text(xi, v + max(mttr) * 0.02, f"{v:.0f} min", ha="center", color=INK, fontsize=10)
    ax2.set_ylim(0, max(mttr) * 1.18)
    ax2.set_ylabel("Mean minutes to resolve", color=INK_2)
    ax2.set_xticks(range(2), labels, color=INK)
    ax2.set_title(f"Simulated MTTR: -{ev.mttr_improvement_pct}%", loc="left", color=INK,
                  fontsize=12, fontweight="bold")

    fig.text(0.01, 0.015, f"{LABEL}. Assumptions in docs/sample-report.md.", color=INK_2, fontsize=8)
    fig.tight_layout(rect=(0, 0.05, 1, 1))
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=144, facecolor=SURFACE, metadata={"Software": None})
    plt.close(fig)
    return path


def write_outputs(scenario: Scenario, result: PipelineResult, ev: Evaluation, out_dir: str | Path,
                  chart: bool = True) -> dict[str, Path]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}
    chart_name = None
    if chart:
        paths["chart"] = render_chart(ev, out_dir / "noise-reduction.png")
        chart_name = paths["chart"].name
    paths["markdown"] = out_dir / "sample-report.md"
    paths["markdown"].write_text(to_markdown(scenario, result, ev, chart_name), encoding="utf-8")
    paths["json"] = out_dir / "sample-report.json"
    paths["json"].write_text(json.dumps(to_json(scenario, result, ev), indent=2) + "\n", encoding="utf-8")
    return paths
