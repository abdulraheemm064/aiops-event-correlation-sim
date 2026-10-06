"""Synthetic alert stream in the style of a network/server/application monitor.

The generator produces three kinds of traffic over a time window:

* **Incidents** - a root fault on one node, then symptom alerts cascading to
  downstream nodes after short delays. Conditions are re-sent every poll
  interval while they persist (duplicates) and reset when the incident ends.
* **Flapping** - interfaces bouncing up/down repeatedly.
* **Background noise** - isolated, low-severity, self-clearing alerts.

Each alert carries ground-truth labels (``truth_incident`` / ``truth_root``).
The correlation engine never reads them; they exist only to score the engine.
"""

from __future__ import annotations

import random
from dataclasses import asdict, dataclass

from aiops_sim.topology import Topology

SEVERITIES = ["Critical", "Major", "Minor", "Warning"]

# Symptom templates by node kind: (entity, metric, severity, message)
ROOT_SYMPTOM = {
    "core_switch": ("Node", "node_status", "Critical", "Node {node} is DOWN (no ICMP response)"),
    "access_switch": ("Node", "node_status", "Critical", "Node {node} is DOWN (no ICMP response)"),
    "firewall": ("Interface", "interface_status", "Critical", "Interface Gi0/1 on {node} is DOWN"),
    "load_balancer": ("Application", "pool_status", "Critical", "Pool members unavailable on {node}"),
    "server": ("Node", "node_status", "Critical", "Node {node} is DOWN"),
    "db_server": ("Application", "db_availability", "Critical",
                  "Database listener not responding on {node}"),
    "application": ("Application", "app_availability", "Critical",
                    "Synthetic transaction failing for {node}"),
}
DOWNSTREAM_SYMPTOM = {
    "core_switch": ("Interface", "interface_status", "Major", "Uplink interface on {node} is DOWN"),
    "access_switch": ("Node", "node_status", "Major", "Node {node} is UNREACHABLE"),
    "firewall": ("Interface", "interface_status", "Major", "Interface on {node} has no carrier"),
    "load_balancer": ("Application", "pool_status", "Major", "Pool health degraded on {node}"),
    "server": ("Node", "node_status", "Major", "Node {node} is UNREACHABLE"),
    "db_server": ("Application", "db_availability", "Major", "Database connections failing on {node}"),
    "application": ("Application", "response_time", "Critical", "Response time > 5s for {node}"),
}
NOISE = [
    ("Node", "cpu_load", "Warning", "CPU load above 90% on {node}"),
    ("Node", "memory_used", "Warning", "Memory usage above 85% on {node}"),
    ("Volume", "disk_space", "Minor", "Volume /var above 85% on {node}"),
    ("Application", "response_time", "Warning", "Response time above 2s for {node}"),
]


@dataclass
class Alert:
    alert_id: str
    ts: int  # seconds since simulation start
    node: str
    entity: str
    metric: str
    severity: str
    message: str
    state: str  # "trigger" or "reset"
    truth_incident: str | None = None
    truth_root: bool = False

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.node, self.entity, self.metric)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class GroundTruthIncident:
    incident_id: str
    root_node: str
    start: int
    end: int
    fix_minutes: int


@dataclass
class Scenario:
    alerts: list[Alert]
    incidents: list[GroundTruthIncident]
    hours: int
    seed: int


@dataclass
class GeneratorConfig:
    hours: int = 24
    incidents: int = 12
    flapping_interfaces: int = 4
    noise_alerts: int = 160
    poll_interval_s: int = 120
    max_repeats: int = 12
    symptom_probability: float = 0.85
    root_silent_probability: float = 0.2  # root device unmonitored / its alert lost


ROOT_KIND_WEIGHTS = {
    "access_switch": 4, "server": 4, "db_server": 3, "load_balancer": 2,
    "core_switch": 1, "firewall": 1, "application": 2,
}


def generate(topology: Topology, seed: int = 7, config: GeneratorConfig | None = None) -> Scenario:
    cfg = config or GeneratorConfig()
    rng = random.Random(seed)
    horizon = cfg.hours * 3600
    raw: list[Alert] = []
    incidents: list[GroundTruthIncident] = []

    def emit_condition(node: str, template: tuple, start: int, end: int,
                       incident: str | None, is_root: bool) -> None:
        entity, metric, severity, message = template
        t = start
        repeats = 0
        while t < end and repeats < cfg.max_repeats:
            raw.append(Alert("", t, node, entity, metric, severity,
                             message.format(node=node), "trigger", incident, is_root))
            t += cfg.poll_interval_s + rng.randint(-10, 10)
            repeats += 1
        raw.append(Alert("", end, node, entity, metric, severity,
                         message.format(node=node) + " (cleared)", "reset", incident, is_root))

    # --- incidents ---
    by_kind: dict[str, list[str]] = {}
    for node in topology.nodes.values():
        by_kind.setdefault(node.kind, []).append(node.name)
    kinds = list(ROOT_KIND_WEIGHTS)
    weights = [ROOT_KIND_WEIGHTS[k] for k in kinds]
    slot = horizon // cfg.incidents
    for i in range(cfg.incidents):
        kind = rng.choices(kinds, weights)[0]
        root = rng.choice(sorted(by_kind[kind]))
        start = i * slot + rng.randint(600, max(601, slot - 4200))
        duration = rng.randint(15, 60) * 60
        end = start + duration
        inc_id = f"INC-SIM-{i + 1:03d}"
        incidents.append(GroundTruthIncident(inc_id, root, start, end, rng.randint(15, 60)))
        if rng.random() >= cfg.root_silent_probability or not topology.descendants(root):
            emit_condition(root, ROOT_SYMPTOM[kind], start, end, inc_id, True)
        for node, hops in sorted(topology.descendants(root).items()):
            if rng.random() > cfg.symptom_probability:
                continue
            delay = rng.randint(20, 90) * hops
            child_kind = topology.nodes[node].kind
            emit_condition(node, DOWNSTREAM_SYMPTOM[child_kind], start + delay,
                           end + rng.randint(0, 120), inc_id, False)

    # --- flapping interfaces (noise) ---
    switches = sorted(by_kind["access_switch"] + by_kind["core_switch"])
    for f in range(cfg.flapping_interfaces):
        node = rng.choice(switches)
        t = rng.randint(0, horizon - 3600)
        stop = t + rng.randint(20, 40) * 60
        port = f"Gi1/0/{rng.randint(1, 48)}"
        while t < stop:
            down_for = rng.randint(30, 150)
            raw.append(Alert("", t, node, "Interface", f"interface_status:{port}", "Minor",
                             f"Interface {port} on {node} is DOWN", "trigger", f"FLAP-{f + 1:02d}"))
            raw.append(Alert("", t + down_for, node, "Interface", f"interface_status:{port}", "Minor",
                             f"Interface {port} on {node} is UP", "reset", f"FLAP-{f + 1:02d}"))
            t += down_for + rng.randint(30, 180)

    # --- background noise ---
    noisy_nodes = sorted(by_kind["server"] + by_kind["db_server"] + by_kind["application"])
    for _ in range(cfg.noise_alerts):
        node = rng.choice(noisy_nodes)
        template = rng.choice(NOISE)
        start = rng.randint(0, horizon - 1800)
        emit_condition(node, template, start, start + rng.randint(4, 15) * 60, None, False)

    raw.sort(key=lambda a: (a.ts, a.node, a.metric, a.state))
    for n, alert in enumerate(raw, start=1):
        alert.alert_id = f"EVT{n:06d}"
    return Scenario(raw, incidents, cfg.hours, seed)
