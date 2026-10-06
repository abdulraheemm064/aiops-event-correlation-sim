"""Synthetic service topology (a small CMDB-like dependency graph).

Edges point *upstream*: ``upstream["app-server"] = ["access-switch"]`` means the
app server depends on the access switch. If an upstream node fails, everything
downstream of it can raise symptoms.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

# Lower rank = closer to the network core. Used as a tie-breaker in RCA.
KIND_RANK = {
    "core_switch": 0,
    "firewall": 1,
    "load_balancer": 1,
    "access_switch": 2,
    "server": 3,
    "db_server": 3,
    "application": 4,
}


@dataclass(frozen=True)
class Node:
    name: str
    kind: str


@dataclass(frozen=True)
class Service:
    name: str
    criticality: int  # 1 = most critical
    app_node: str


@dataclass
class Topology:
    nodes: dict[str, Node] = field(default_factory=dict)
    upstream: dict[str, list[str]] = field(default_factory=dict)
    services: dict[str, Service] = field(default_factory=dict)
    _down: dict[str, list[str]] | None = field(default=None, init=False, repr=False)

    def add(self, name: str, kind: str, depends_on: list[str] | None = None) -> None:
        if name in self.nodes:
            raise ValueError(f"duplicate node {name}")
        for dep in depends_on or []:
            if dep not in self.nodes:
                raise ValueError(f"{name} depends on unknown node {dep}")
        self.nodes[name] = Node(name, kind)
        self.upstream[name] = list(depends_on or [])
        self._down = None  # invalidate cache

    @property
    def downstream(self) -> dict[str, list[str]]:
        if self._down is None:
            down: dict[str, list[str]] = {n: [] for n in self.nodes}
            for child, parents in self.upstream.items():
                for parent in parents:
                    down[parent].append(child)
            self._down = down
        return self._down

    def _walk(self, start: str, edges: dict[str, list[str]]) -> dict[str, int]:
        """Return {node: hops} reachable from start (excluding start)."""
        seen: dict[str, int] = {}
        queue = deque([(start, 0)])
        while queue:
            node, depth = queue.popleft()
            for nxt in edges.get(node, []):
                if nxt not in seen:
                    seen[nxt] = depth + 1
                    queue.append((nxt, depth + 1))
        return seen

    def ancestors(self, name: str) -> dict[str, int]:
        return self._walk(name, self.upstream)

    def descendants(self, name: str) -> dict[str, int]:
        return self._walk(name, self.downstream)

    def related(self, a: str, b: str, max_hops: int = 3) -> bool:
        """Topologically related: one depends on the other, or they share an
        upstream dependency, each within ``max_hops``."""
        if a == b:
            return True
        anc_a, anc_b = self.ancestors(a), self.ancestors(b)
        if anc_a.get(b, max_hops + 1) <= max_hops or anc_b.get(a, max_hops + 1) <= max_hops:
            return True
        shared = set(anc_a) & set(anc_b)
        return any(anc_a[s] <= max_hops and anc_b[s] <= max_hops
                   and self.nodes[s].kind != "core_switch" for s in shared)

    def impacted_services(self, name: str) -> list[Service]:
        affected = set(self.descendants(name)) | {name}
        return sorted((s for s in self.services.values() if s.app_node in affected),
                      key=lambda s: (s.criticality, s.name))

    def lowest_common_ancestor(self, names: list[str]) -> str | None:
        """Most specific node that every name depends on (or is)."""
        if not names:
            return None
        common: set[str] | None = None
        for n in names:
            reach = set(self.ancestors(n)) | {n}
            common = reach if common is None else common & reach
        if not common:
            return None
        # most specific = the one that has the fewest descendants
        return min(common, key=lambda c: (len(self.descendants(c)), c))


SERVICES = [
    ("Online Banking", 1, "ob"),
    ("Card Authorization", 1, "card"),
    ("Payments Gateway", 1, "pay"),
    ("Mobile API", 1, "mob"),
    ("Claims Portal", 2, "clm"),
    ("Policy Administration", 2, "pol"),
    ("Branch Teller", 2, "tel"),
    ("Data Warehouse", 3, "dwh"),
]


def build_topology() -> Topology:
    """Contoso Bank reference topology: 2 core switches, firewall, 2 load
    balancers, 6 access switches, 8 services x (2 app servers + 1 db server)."""
    t = Topology()
    t.add("cb-core-sw-01", "core_switch")
    t.add("cb-core-sw-02", "core_switch")
    t.add("cb-fw-01", "firewall", ["cb-core-sw-01"])
    t.add("cb-lb-01", "load_balancer", ["cb-fw-01"])
    t.add("cb-lb-02", "load_balancer", ["cb-core-sw-02"])
    for i in range(1, 7):
        t.add(f"cb-acc-sw-{i:02d}", "access_switch", [f"cb-core-sw-0{1 if i <= 3 else 2}"])
    for idx, (service, crit, code) in enumerate(SERVICES):
        access = f"cb-acc-sw-{idx % 6 + 1:02d}"
        db_access = f"cb-acc-sw-{(idx + 3) % 6 + 1:02d}"
        lb = "cb-lb-01" if crit == 1 else "cb-lb-02"
        servers = [f"cbk-{code}-app-0{n}" for n in (1, 2)]
        for s in servers:
            t.add(s, "server", [access])
        t.add(f"cbk-{code}-db-01", "db_server", [db_access])
        app = f"APP-{service.replace(' ', '')}"
        t.add(app, "application", [lb, *servers, f"cbk-{code}-db-01"])
        t.services[service] = Service(service, crit, app)
    return t
