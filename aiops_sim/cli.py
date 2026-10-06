"""Command line interface.

    python -m aiops_sim run --out-dir docs
    python -m aiops_sim run --seed 11 --hours 48 --incidents 20 --window 600 --no-chart
"""

from __future__ import annotations

import argparse
import csv
import logging
import sys
from pathlib import Path

from aiops_sim import __version__
from aiops_sim.engine import EngineConfig, run_pipeline
from aiops_sim.generator import GeneratorConfig, generate
from aiops_sim.metrics import evaluate
from aiops_sim.report import LABEL, write_outputs
from aiops_sim.topology import build_topology

log = logging.getLogger("aiops_sim")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="aiops_sim",
                                description="Alert correlation simulator (synthetic data only)")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="generate alerts, run the pipeline, write the report")
    run.add_argument("--seed", type=int, default=7)
    run.add_argument("--hours", type=int, default=24)
    run.add_argument("--incidents", type=int, default=12)
    run.add_argument("--noise", type=int, default=160, help="background noise alerts")
    run.add_argument("--window", type=int, default=300, help="correlation window (s)")
    run.add_argument("--max-hops", type=int, default=3)
    run.add_argument("--flap-threshold", type=int, default=3)
    run.add_argument("--out-dir", default="reports")
    run.add_argument("--alerts-csv", help="also export the raw synthetic alert stream as CSV")
    run.add_argument("--no-chart", action="store_true")
    return p


def cmd_run(args: argparse.Namespace) -> int:
    if args.hours < 2 or args.incidents < 1:
        log.error("--hours must be >= 2 and --incidents >= 1")
        return 1
    topology = build_topology()
    scenario = generate(topology, seed=args.seed, config=GeneratorConfig(
        hours=args.hours, incidents=args.incidents, noise_alerts=args.noise))
    log.info("Generated %d raw events over %d h", len(scenario.alerts), args.hours)
    engine_cfg = EngineConfig(correlation_window_s=args.window, max_hops=args.max_hops,
                              flap_threshold=args.flap_threshold)
    result = run_pipeline(scenario.alerts, topology, engine_cfg)
    ev = evaluate(scenario, result)
    paths = write_outputs(scenario, result, ev, args.out_dir, chart=not args.no_chart)

    if args.alerts_csv:
        target = Path(args.alerts_csv)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("w", newline="", encoding="utf-8") as fh:
            rows = [a.to_dict() for a in scenario.alerts]
            writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)

    print(f"[{LABEL}]")
    print(f"raw events {ev.raw_alerts} -> dedup {ev.deduplicated_alerts} -> groups "
          f"{ev.correlated_groups} -> actionable {ev.actionable_incidents} "
          f"({ev.noise_reduction_pct}% noise reduction)")
    print(f"RCA top-1 {ev.rca_top1_accuracy_pct}% | simulated MTTR {ev.mttr_baseline_min} -> "
          f"{ev.mttr_aiops_min} min (-{ev.mttr_improvement_pct}%)")
    for kind, path in paths.items():
        print(f"{kind}: {path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s", stream=sys.stderr)
    return cmd_run(args)
