import json

import pytest

from aiops_sim.cli import main
from aiops_sim.engine import run_pipeline
from aiops_sim.generator import GeneratorConfig, generate
from aiops_sim.metrics import MttrAssumptions, evaluate
from aiops_sim.topology import build_topology


@pytest.fixture(scope="module")
def run7():
    topo = build_topology()
    scenario = generate(topo, seed=7)
    result = run_pipeline(scenario.alerts, topo)
    return scenario, result, evaluate(scenario, result)


def test_generator_is_deterministic():
    topo = build_topology()
    a = generate(topo, seed=3)
    b = generate(topo, seed=3)
    assert [x.to_dict() for x in a.alerts] == [x.to_dict() for x in b.alerts]
    assert [x.to_dict() for x in a.alerts] != [x.to_dict() for x in generate(topo, seed=4).alerts]


def test_generator_contents(run7):
    scenario, _, _ = run7
    assert len(scenario.incidents) == 12
    ids = [a.alert_id for a in scenario.alerts]
    assert len(ids) == len(set(ids))
    assert all(a.ts >= 0 for a in scenario.alerts)
    labels = {a.truth_incident for a in scenario.alerts}
    assert any(label and label.startswith("FLAP-") for label in labels)
    assert None in labels  # background noise


def test_funnel_is_monotonic(run7):
    _, _, ev = run7
    assert (ev.raw_alerts > ev.deduplicated_alerts >= ev.after_flap_suppression
            >= ev.correlated_groups > ev.actionable_incidents > 0)
    assert ev.flapping_suppressed == 4
    assert 90 < ev.noise_reduction_pct < 100


def test_quality_metrics_for_reference_seed(run7):
    _, _, ev = run7
    assert ev.incidents_detected == ev.true_incidents
    assert ev.mean_fragments_per_incident == 1.0
    assert ev.group_purity_pct > 90
    assert 50 <= ev.rca_top1_accuracy_pct <= ev.rca_top3_accuracy_pct <= 100
    assert ev.mttr_aiops_min < ev.mttr_baseline_min


def test_mttr_model_respects_assumptions():
    topo = build_topology()
    scenario = generate(topo, seed=7)
    result = run_pipeline(scenario.alerts, topo)
    same = MttrAssumptions(aiops_triage=45.0, aiops_diagnosis_correct_rca=40.0,
                           aiops_diagnosis_wrong_rca=40.0, baseline_minutes_per_alert=100.0)
    ev = evaluate(scenario, result, same)
    # With no triage or diagnosis advantage, correlation cannot improve MTTR.
    assert ev.mttr_improvement_pct == 0.0


def test_no_noise_means_no_false_positives():
    topo = build_topology()
    scenario = generate(topo, seed=7, config=GeneratorConfig(noise_alerts=0, flapping_interfaces=0))
    ev = evaluate(scenario, run_pipeline(scenario.alerts, topo))
    assert ev.noise_groups_actionable == 0
    assert ev.flapping_suppressed == 0


def test_cli_writes_report_chart_and_csv(tmp_path, capsys):
    csv_path = tmp_path / "alerts.csv"
    assert main(["run", "--out-dir", str(tmp_path), "--alerts-csv", str(csv_path)]) == 0
    out = capsys.readouterr().out
    assert "SIMULATION RESULT ON SYNTHETIC DATA" in out
    md = (tmp_path / "sample-report.md").read_text()
    assert "SIMULATION RESULT ON SYNTHETIC DATA" in md
    assert "![Alert funnel" in md
    assert (tmp_path / "noise-reduction.png").read_bytes()[:4] == b"\x89PNG"
    data = json.loads((tmp_path / "sample-report.json").read_text())
    assert data["evaluation"]["true_incidents"] == 12
    assert csv_path.read_text().startswith("alert_id,ts,node")


def test_cli_options_and_validation(tmp_path):
    assert main(["run", "--out-dir", str(tmp_path), "--no-chart", "--seed", "11", "--hours", "12",
                 "--incidents", "4", "--window", "600"]) == 0
    assert not (tmp_path / "noise-reduction.png").exists()
    assert main(["run", "--out-dir", str(tmp_path), "--hours", "1"]) == 1
