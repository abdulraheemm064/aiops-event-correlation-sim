"""Evaluate the pipeline against the generator's ground truth.

ALL NUMBERS PRODUCED HERE ARE SIMULATION RESULTS ON SYNTHETIC DATA. The MTTR
model is a deliberately simple, transparent set of assumptions (see
MttrAssumptions); it illustrates *why* correlation shortens triage, it does not
predict the effect in any real environment.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field

from aiops_sim.engine import PipelineResult
from aiops_sim.generator import Scenario


@dataclass
class MttrAssumptions:
    baseline_minutes_per_alert: float = 2.0   # operator skims each raw alert of the storm
    baseline_triage_cap: float = 45.0
    baseline_diagnosis: float = 40.0          # manual hunting for the cause
    aiops_triage: float = 5.0                 # one grouped, prioritised alert
    aiops_diagnosis_correct_rca: float = 10.0  # confirm the suggested root cause
    aiops_diagnosis_wrong_rca: float = 40.0   # fall back to manual diagnosis


@dataclass
class Evaluation:
    raw_alerts: int
    deduplicated_alerts: int
    after_flap_suppression: int
    flapping_suppressed: int
    correlated_groups: int
    actionable_incidents: int
    noise_reduction_pct: float
    dedup_reduction_pct: float
    true_incidents: int
    incidents_detected: int
    mean_fragments_per_incident: float
    group_purity_pct: float
    rca_top1_accuracy_pct: float
    rca_top3_accuracy_pct: float
    mttr_baseline_min: float
    mttr_aiops_min: float
    mttr_improvement_pct: float
    noise_groups_actionable: int
    assumptions: dict = field(default_factory=dict)
    per_incident: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def _pct(part: float, whole: float) -> float:
    return round(100.0 * part / whole, 1) if whole else 0.0


def evaluate(scenario: Scenario, result: PipelineResult,
             assumptions: MttrAssumptions | None = None) -> Evaluation:
    mttr = assumptions or MttrAssumptions()
    actionable = result.actionable

    # Which groups carry each true incident's alerts?
    groups_by_incident: dict[str, list] = defaultdict(list)
    for g in result.groups:
        labels = Counter()
        for a in g.alerts:
            labels.update(a.truth)
        for label in labels:
            if label.startswith("INC-"):
                groups_by_incident[label].append(g)

    raw_by_incident = Counter(a.truth_incident for a in scenario.alerts
                              if a.state == "trigger" and a.truth_incident)

    purity_hits = sum(sum(a.truth[g.truth_label] for a in g.alerts) for g in result.groups)
    purity_total = sum(sum(a.truth.values()) for g in result.groups for a in g.alerts)

    per_incident = []
    top1 = top3 = detected = 0
    fragments = []
    for inc in scenario.incidents:
        groups = [g for g in groups_by_incident.get(inc.incident_id, []) if g.actionable]
        main = max(groups, key=lambda g: sum(a.truth[inc.incident_id] for a in g.alerts), default=None)
        is_detected = main is not None
        detected += is_detected
        fragments.append(len(groups) or 1)
        cand = [c.node for c in main.candidates] if main else []
        hit1 = bool(cand) and cand[0] == inc.root_node
        hit3 = inc.root_node in cand
        top1 += hit1
        top3 += hit3
        storm = raw_by_incident[inc.incident_id]
        baseline = (min(mttr.baseline_triage_cap, storm * mttr.baseline_minutes_per_alert)
                    + mttr.baseline_diagnosis + inc.fix_minutes)
        if is_detected:
            aiops = (mttr.aiops_triage + (mttr.aiops_diagnosis_correct_rca if hit1
                                          else mttr.aiops_diagnosis_wrong_rca) + inc.fix_minutes)
        else:
            aiops = baseline
        per_incident.append({
            "incident": inc.incident_id, "root_node": inc.root_node, "raw_alerts": storm,
            "groups": len(groups), "priority": main.priority if main else None,
            "top_candidate": cand[0] if cand else None, "rca_top1": hit1,
            "mttr_baseline_min": round(baseline, 1), "mttr_aiops_min": round(aiops, 1),
        })

    n = len(scenario.incidents)
    base_mean = sum(p["mttr_baseline_min"] for p in per_incident) / n if n else 0.0
    aiops_mean = sum(p["mttr_aiops_min"] for p in per_incident) / n if n else 0.0
    return Evaluation(
        raw_alerts=result.raw_count,
        deduplicated_alerts=len(result.deduped),
        after_flap_suppression=sum(1 for a in result.after_flap if not a.flapping),
        flapping_suppressed=sum(1 for a in result.after_flap if a.flapping),
        correlated_groups=len(result.groups),
        actionable_incidents=len(actionable),
        noise_reduction_pct=_pct(result.raw_count - len(actionable), result.raw_count),
        dedup_reduction_pct=_pct(result.raw_count - len(result.deduped), result.raw_count),
        true_incidents=n,
        incidents_detected=detected,
        mean_fragments_per_incident=round(sum(fragments) / n, 2) if n else 0.0,
        group_purity_pct=_pct(purity_hits, purity_total),
        rca_top1_accuracy_pct=_pct(top1, n),
        rca_top3_accuracy_pct=_pct(top3, n),
        mttr_baseline_min=round(base_mean, 1),
        mttr_aiops_min=round(aiops_mean, 1),
        mttr_improvement_pct=_pct(base_mean - aiops_mean, base_mean),
        noise_groups_actionable=sum(1 for g in actionable if g.truth_label in (None, "noise")
                                    or str(g.truth_label).startswith("FLAP")),
        assumptions=asdict(mttr),
        per_incident=per_incident,
    )
