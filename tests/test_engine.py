import pytest

from aiops_sim.engine import (
    EngineConfig,
    correlate,
    deduplicate,
    root_cause_candidates,
    run_pipeline,
    score_group,
    suppress_flapping,
)
from aiops_sim.generator import Alert
from aiops_sim.topology import build_topology

CFG = EngineConfig()


@pytest.fixture(scope="module")
def topo():
    return build_topology()


def ev(ts, node, metric="node_status", severity="Major", state="trigger", truth=None, root=False):
    return Alert(f"E{ts}-{node}-{metric}-{state}", ts, node, "Node", metric, severity,
                 f"{metric} on {node}", state, truth, root)


def test_dedup_counts_repeats_and_reopens_after_reset():
    raw = [ev(0, "h1"), ev(60, "h1"), ev(120, "h1", severity="Critical"),
           ev(180, "h1", state="reset"), ev(600, "h1")]
    alerts = deduplicate(raw)
    assert [a.count for a in alerts] == [3, 1]
    assert alerts[0].severity == "Critical"
    assert alerts[0].closed_ts == 180
    assert alerts[1].closed_ts is None


def test_dedup_keys_on_node_entity_metric():
    raw = [ev(0, "h1"), ev(0, "h1", metric="cpu_load"), ev(0, "h2")]
    assert len(deduplicate(raw)) == 3


def test_reset_without_open_alert_is_ignored():
    assert deduplicate([ev(0, "h1", state="reset")]) == []


def test_flapping_chain_is_collapsed_and_flagged():
    raw = []
    for i in range(4):  # down/up every ~3 minutes
        raw += [ev(i * 180, "sw", metric="if:1"), ev(i * 180 + 60, "sw", metric="if:1", state="reset")]
    raw += [ev(10_000, "sw", metric="if:1")]  # much later: a separate, normal alert
    result = suppress_flapping(deduplicate(raw), CFG)
    flapping = [a for a in result if a.flapping]
    assert len(flapping) == 1
    assert flapping[0].flap_cycles == 4
    assert flapping[0].count == 4
    assert [a.flapping for a in result] == [True, False]


def test_two_reopens_are_not_flapping():
    raw = [ev(0, "sw"), ev(30, "sw", state="reset"), ev(200, "sw")]
    assert not any(a.flapping for a in suppress_flapping(deduplicate(raw), CFG))


def test_correlation_needs_time_and_topology(topo):
    raw = [
        ev(0, "cb-acc-sw-01", severity="Critical"),
        ev(60, "cbk-ob-app-01"),
        ev(90, "APP-OnlineBanking"),
        ev(100, "cbk-pol-app-01"),   # concurrent but unrelated
        ev(4000, "cbk-ob-app-02"),   # related but far later
    ]
    groups = correlate(deduplicate(raw), topo, CFG)
    assert [g.nodes for g in groups] == [
        ["APP-OnlineBanking", "cb-acc-sw-01", "cbk-ob-app-01"],
        ["cbk-pol-app-01"],
        ["cbk-ob-app-02"],
    ]


def test_flapping_alerts_never_open_groups(topo):
    alerts = deduplicate([ev(0, "cb-acc-sw-01")])
    alerts[0].flapping = True
    assert correlate(alerts, topo, CFG) == []


def test_alert_joins_group_containing_its_cause(topo):
    # Group A: CPU noise on an Online Banking server. Group B: the load balancer fails
    # (unrelated to that server). The app alert relates to both; it must join B.
    raw = [ev(0, "cbk-ob-app-02", metric="cpu_load", severity="Warning"),
           ev(10, "cb-lb-01", severity="Critical"),
           ev(40, "APP-OnlineBanking", severity="Critical")]
    groups = correlate(deduplicate(raw), topo, CFG)
    by_node = {n: g.group_id for g in groups for n in g.nodes}
    assert len(groups) == 2
    assert by_node["APP-OnlineBanking"] == by_node["cb-lb-01"]


def test_priority_scoring(topo):
    critical_core = correlate(deduplicate([ev(0, "cb-acc-sw-01", severity="Critical"),
                                           ev(30, "cbk-ob-app-01"), ev(40, "APP-OnlineBanking")]),
                              topo, CFG)[0]
    warning_dwh = correlate(deduplicate([ev(0, "cbk-dwh-db-01", metric="cpu_load", severity="Warning")]),
                            topo, CFG)[0]
    score_group(critical_core, topo, CFG)
    score_group(warning_dwh, topo, CFG)
    assert critical_core.priority == "P1" and critical_core.actionable
    assert critical_core.impacted_services[0] in {"Online Banking", "Payments Gateway",
                                                  "Card Authorization", "Mobile API"}
    assert warning_dwh.priority == "P4" and not warning_dwh.actionable
    assert critical_core.score > warning_dwh.score


def test_root_cause_prefers_upstream_alerting_node(topo):
    raw = [ev(30, "cbk-ob-app-01"), ev(0, "cb-acc-sw-01", severity="Critical"),
           ev(45, "cbk-ob-app-02"), ev(60, "APP-OnlineBanking")]
    group = correlate(deduplicate(raw), topo, CFG)[0]
    cands = root_cause_candidates(group, topo)
    assert cands[0].node == "cb-acc-sw-01"
    assert cands[0].coverage == 1.0
    assert not cands[0].inferred


def test_root_cause_infers_silent_upstream(topo):
    # Access switch is unmonitored: only its two servers alert.
    raw = [ev(0, "cbk-ob-app-01"), ev(20, "cbk-ob-app-02")]
    group = correlate(deduplicate(raw), topo, CFG)[0]
    cands = root_cause_candidates(group, topo)
    assert cands[0].node == "cb-acc-sw-01"
    assert cands[0].inferred


def test_run_pipeline_counts_only_triggers(topo):
    raw = [ev(0, "cbk-ob-app-01"), ev(5, "cbk-ob-app-01", state="reset")]
    result = run_pipeline(raw, topo)
    assert result.raw_count == 1
    assert len(result.groups) == 1
