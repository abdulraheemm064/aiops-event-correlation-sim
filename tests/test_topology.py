import pytest

from aiops_sim.topology import Topology, build_topology


@pytest.fixture(scope="module")
def topo():
    return build_topology()


def test_reference_topology_shape(topo):
    assert len(topo.nodes) == 43
    assert len(topo.services) == 8
    kinds = {n.kind for n in topo.nodes.values()}
    assert kinds == {"core_switch", "firewall", "load_balancer", "access_switch", "server",
                     "db_server", "application"}


def test_ancestors_and_descendants(topo):
    anc = topo.ancestors("cbk-ob-app-01")
    assert anc == {"cb-acc-sw-01": 1, "cb-core-sw-01": 2}
    assert "APP-OnlineBanking" in topo.descendants("cb-acc-sw-01")
    assert topo.descendants("APP-OnlineBanking") == {}


def test_related_rules(topo):
    assert topo.related("cbk-ob-app-01", "cb-acc-sw-01")            # depends on
    assert topo.related("cbk-ob-app-01", "cbk-ob-app-02")           # share access switch
    assert not topo.related("cbk-ob-app-01", "cbk-pol-app-01")
    # Sharing only a core switch is too broad to imply a relationship.
    assert not topo.related("cb-acc-sw-01", "cb-acc-sw-02")
    assert topo.related("cb-core-sw-01", "APP-OnlineBanking", max_hops=3)
    assert not topo.related("cb-core-sw-01", "APP-OnlineBanking", max_hops=2)


def test_impacted_services_ordered_by_criticality(topo):
    names = [s.name for s in topo.impacted_services("cb-lb-01")]
    assert names == ["Card Authorization", "Mobile API", "Online Banking", "Payments Gateway"]
    assert topo.impacted_services("cbk-dwh-db-01")[0].criticality == 3


def test_lowest_common_ancestor(topo):
    assert topo.lowest_common_ancestor(["cbk-ob-app-01", "cbk-ob-app-02"]) == "cb-acc-sw-01"
    assert topo.lowest_common_ancestor(["cbk-ob-app-01"]) == "cbk-ob-app-01"
    assert topo.lowest_common_ancestor([]) is None


def test_add_validates():
    t = Topology()
    t.add("a", "server")
    with pytest.raises(ValueError):
        t.add("a", "server")
    with pytest.raises(ValueError):
        t.add("b", "server", ["missing"])
