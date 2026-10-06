"""Event processing pipeline: dedup -> flap suppression -> correlation ->
priority scoring -> root-cause candidates.

The stages mirror concepts found in event management platforms (message-key
deduplication, flap detection, time and topology based alert grouping,
priority scoring, probable root cause). This is an independent, simplified
implementation for learning and demonstration.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from aiops_sim.generator import Alert
from aiops_sim.topology import KIND_RANK, Topology

SEVERITY_WEIGHT = {"Critical": 1.0, "Major": 0.75, "Minor": 0.35, "Warning": 0.15}
CRITICALITY_FACTOR = {1: 1.0, 2: 0.6, 3: 0.3}


@dataclass
class EngineConfig:
    correlation_window_s: int = 300      # join a group if within this gap of its last alert
    max_group_span_s: int = 3600         # never extend a group beyond this from its start
    max_hops: int = 3                    # topology relation distance
    flap_window_s: int = 900             # re-opens of the same key within this gap form a chain
    flap_threshold: int = 3              # chain length that counts as flapping
    actionable_score: float = 50.0       # groups at or above this score become incidents


@dataclass
class DedupAlert:
    """One de-duplicated alert (many raw events with the same message key)."""
    key: tuple[str, str, str]
    node: str
    metric: str
    severity: str
    first_ts: int
    last_ts: int
    closed_ts: int | None
    count: int
    raw_ids: list[str]
    truth: Counter = field(default_factory=Counter)
    truth_root: bool = False
    flapping: bool = False
    flap_cycles: int = 0

    @property
    def truth_label(self) -> str | None:
        return self.truth.most_common(1)[0][0] if self.truth else None


@dataclass
class RootCauseCandidate:
    node: str
    coverage: float  # share of group nodes downstream of (or equal to) this node
    inferred: bool   # True when the node raised no alert itself


@dataclass
class AlertGroup:
    group_id: str
    alerts: list[DedupAlert]
    start: int
    last_ts: int
    score: float = 0.0
    priority: str = "P4"
    actionable: bool = False
    impacted_services: list[str] = field(default_factory=list)
    candidates: list[RootCauseCandidate] = field(default_factory=list)

    @property
    def nodes(self) -> list[str]:
        return sorted({a.node for a in self.alerts})

    @property
    def raw_count(self) -> int:
        return sum(a.count for a in self.alerts)

    @property
    def truth_label(self) -> str | None:
        votes: Counter = Counter()
        for a in self.alerts:
            votes.update(a.truth)
        return votes.most_common(1)[0][0] if votes else None


# ---------------------------------------------------------------- stage 1
def deduplicate(raw: list[Alert]) -> list[DedupAlert]:
    """Collapse repeats of an open condition into one alert; a reset closes it."""
    open_alerts: dict[tuple, DedupAlert] = {}
    out: list[DedupAlert] = []
    for ev in sorted(raw, key=lambda a: (a.ts, a.alert_id)):
        current = open_alerts.get(ev.key)
        if ev.state == "reset":
            if current:
                current.closed_ts = ev.ts
                del open_alerts[ev.key]
            continue
        if current:
            current.count += 1
            current.last_ts = ev.ts
            current.raw_ids.append(ev.alert_id)
            if SEVERITY_WEIGHT[ev.severity] > SEVERITY_WEIGHT[current.severity]:
                current.severity = ev.severity
        else:
            current = DedupAlert(ev.key, ev.node, ev.metric, ev.severity, ev.ts, ev.ts, None,
                                 1, [ev.alert_id])
            open_alerts[ev.key] = current
            out.append(current)
        current.truth[ev.truth_incident or "noise"] += 1
        current.truth_root = current.truth_root or ev.truth_root
    return out


# ---------------------------------------------------------------- stage 2
def suppress_flapping(alerts: list[DedupAlert], cfg: EngineConfig) -> list[DedupAlert]:
    """Merge chains of re-opened alerts on the same key into one flapping alert."""
    by_key: dict[tuple, list[DedupAlert]] = {}
    for a in alerts:
        by_key.setdefault(a.key, []).append(a)
    result: list[DedupAlert] = []
    for chain_source in by_key.values():
        chain_source.sort(key=lambda a: a.first_ts)
        chain: list[DedupAlert] = []
        for a in chain_source + [None]:  # sentinel flushes the last chain
            if a is not None and chain and a.first_ts - chain[-1].first_ts <= cfg.flap_window_s:
                chain.append(a)
                continue
            if chain:
                if len(chain) >= cfg.flap_threshold:
                    head = chain[0]
                    for extra in chain[1:]:
                        head.count += extra.count
                        head.raw_ids += extra.raw_ids
                        head.truth.update(extra.truth)
                        head.last_ts = max(head.last_ts, extra.last_ts)
                        head.closed_ts = extra.closed_ts
                    head.flapping = True
                    head.flap_cycles = len(chain)
                    result.append(head)
                else:
                    result.extend(chain)
            chain = [a] if a is not None else []
    return sorted(result, key=lambda a: (a.first_ts, a.node, a.metric))


# ---------------------------------------------------------------- stage 3
def correlate(alerts: list[DedupAlert], topology: Topology, cfg: EngineConfig) -> list[AlertGroup]:
    """Group alerts that are close in time AND related in the topology."""
    groups: list[AlertGroup] = []
    for a in sorted(alerts, key=lambda x: (x.first_ts, x.node)):
        if a.flapping:
            continue  # suppressed: tracked, but never opens or joins incidents
        best: AlertGroup | None = None
        best_rank: tuple = ()
        ancestors = topology.ancestors(a.node)
        for g in groups:
            if a.first_ts - g.last_ts > cfg.correlation_window_s:
                continue
            if a.first_ts - g.start > cfg.max_group_span_s:
                continue
            related = sum(1 for n in g.nodes if topology.related(a.node, n, cfg.max_hops))
            if not related:
                continue
            # Prefer the group holding the most severe alert on one of this alert's
            # upstream dependencies (the likeliest cause), then the group with the most
            # related nodes, then the oldest group.
            cause_severity = max((SEVERITY_WEIGHT[x.severity] for x in g.alerts if x.node in ancestors),
                                 default=0.0)
            rank = (cause_severity, related, -g.start)
            if best is None or rank > best_rank:
                best, best_rank = g, rank
        if best is None:
            best = AlertGroup(f"GRP{len(groups) + 1:04d}", [], a.first_ts, a.first_ts)
            groups.append(best)
        best.alerts.append(a)
        best.last_ts = max(best.last_ts, a.first_ts)
    return groups


# ---------------------------------------------------------------- stage 4
def score_group(group: AlertGroup, topology: Topology, cfg: EngineConfig) -> None:
    """Priority = severity (60) + business criticality of impacted services (25) + breadth (15)."""
    severity = max(SEVERITY_WEIGHT[a.severity] for a in group.alerts)
    services: dict[str, int] = {}
    for node in group.nodes:
        for svc in topology.impacted_services(node):
            services[svc.name] = svc.criticality
    crit = max((CRITICALITY_FACTOR[c] for c in services.values()), default=0.0)
    breadth = min(15.0, 3.0 * len(group.nodes))
    group.score = round(60 * severity + 25 * crit + breadth, 1)
    group.priority = ("P1" if group.score >= 85 else "P2" if group.score >= 70
                      else "P3" if group.score >= cfg.actionable_score else "P4")
    group.actionable = group.score >= cfg.actionable_score
    group.impacted_services = sorted(services, key=lambda s: (services[s], s))


# ---------------------------------------------------------------- stage 5
def root_cause_candidates(group: AlertGroup, topology: Topology, top_n: int = 3,
                          infer_below: float = 0.75) -> list[RootCauseCandidate]:
    """Rank alerting nodes by how much of the group sits downstream of them.

    Tie-breakers: closer to the network core, then earliest alert.
    If no alerting node explains at least ``infer_below`` of the group, the
    lowest common upstream dependency is offered first as an inferred
    (non-alerting) candidate - e.g. an unmonitored switch behind two failed servers.
    """
    nodes = group.nodes
    first_seen = {}
    for a in group.alerts:
        first_seen[a.node] = min(first_seen.get(a.node, a.first_ts), a.first_ts)

    def coverage(candidate: str) -> float:
        below = set(topology.descendants(candidate)) | {candidate}
        return sum(1 for n in nodes if n in below) / len(nodes)

    ranked = sorted(nodes, key=lambda n: (-coverage(n), KIND_RANK[topology.nodes[n].kind],
                                          first_seen[n], n))
    candidates = [RootCauseCandidate(n, round(coverage(n), 2), False) for n in ranked[:top_n]]
    if len(nodes) > 1 and candidates[0].coverage < infer_below:
        lca = topology.lowest_common_ancestor(nodes)
        if lca and lca not in nodes:
            candidates.insert(0, RootCauseCandidate(lca, 1.0, True))
    return candidates[:top_n]


@dataclass
class PipelineResult:
    raw_count: int
    deduped: list[DedupAlert]
    after_flap: list[DedupAlert]
    groups: list[AlertGroup]

    @property
    def actionable(self) -> list[AlertGroup]:
        return [g for g in self.groups if g.actionable]


def run_pipeline(raw: list[Alert], topology: Topology, cfg: EngineConfig | None = None) -> PipelineResult:
    cfg = cfg or EngineConfig()
    deduped = deduplicate(raw)
    after_flap = suppress_flapping([_copy(a) for a in deduped], cfg)
    groups = correlate(after_flap, topology, cfg)
    for g in groups:
        score_group(g, topology, cfg)
        g.candidates = root_cause_candidates(g, topology)
    trigger_count = sum(1 for a in raw if a.state == "trigger")
    return PipelineResult(trigger_count, deduped, after_flap, groups)


def _copy(a: DedupAlert) -> DedupAlert:
    return DedupAlert(a.key, a.node, a.metric, a.severity, a.first_ts, a.last_ts, a.closed_ts,
                      a.count, list(a.raw_ids), Counter(a.truth), a.truth_root)
