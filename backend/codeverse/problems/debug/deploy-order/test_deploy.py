import unittest

from deploy import CycleError, Resolver, plan_deploy

GRAPH = {
    "web": ["api", "cdn"],
    "api": ["auth", "db", "cache"],
    "auth": ["db"],
    "worker": ["queue", "db"],
    "queue": [],
    "cache": [],
    "db": [],
    "cdn": [],
}

# A long chain: s0 depends on nothing, s1 on s0, ... s11 on s10.
CHAIN = {f"s{i}": ([f"s{i - 1}"] if i else []) for i in range(12)}


def assert_valid_order(test, graph, steps):
    pos = {name: i for i, name in enumerate(steps)}
    test.assertEqual(len(pos), len(steps), f"duplicate services in {steps}")
    for name in steps:
        for dep in graph.get(name, []):
            if dep in pos:
                test.assertLess(pos[dep], pos[name], f"{name} starts before its dependency {dep}: {steps}")


class ResolverTests(unittest.TestCase):
    def test_leaf(self):
        self.assertEqual(Resolver(GRAPH).start_order("db"), ["db"])

    def test_dependencies_come_first(self):
        order = Resolver(GRAPH).start_order("web")
        self.assertEqual(order[-1], "web")
        self.assertEqual(set(order), {"web", "api", "cdn", "auth", "db", "cache"})
        assert_valid_order(self, GRAPH, order)

    def test_direct_cycle_raises(self):
        with self.assertRaises(CycleError):
            Resolver({"a": ["b"], "b": ["a"]}).start_order("a")

    def test_indirect_cycle_raises(self):
        with self.assertRaises(CycleError):
            Resolver({"a": ["b"], "b": ["c"], "c": ["a"], "d": []}).start_order("a")

    def test_self_dependency_raises(self):
        with self.assertRaises(CycleError):
            Resolver({"a": ["a"]}).start_order("a")

    def test_diamond_is_not_a_cycle(self):
        graph = {"top": ["left", "right"], "left": ["base"], "right": ["base"], "base": []}
        order = Resolver(graph).start_order("top")
        assert_valid_order(self, graph, order)
        self.assertEqual(order.count("base"), 1)


class PlanDeployTests(unittest.TestCase):
    def test_single_target(self):
        steps = plan_deploy(Resolver(GRAPH), ["api"])
        self.assertEqual(set(steps), {"api", "auth", "db", "cache"})
        assert_valid_order(self, GRAPH, steps)

    def test_long_chain_order_is_preserved(self):
        steps = plan_deploy(Resolver(CHAIN), ["s11"])
        self.assertEqual(steps, [f"s{i}" for i in range(12)])

    def test_multiple_targets_share_dependencies_once(self):
        steps = plan_deploy(Resolver(GRAPH), ["web", "worker"])
        self.assertEqual(steps.count("db"), 1)
        assert_valid_order(self, GRAPH, steps)

    def test_already_running_services_are_skipped(self):
        steps = plan_deploy(Resolver(GRAPH), ["api"], already_running=["db"])
        self.assertNotIn("db", steps)
        assert_valid_order(self, GRAPH, steps)

    def test_planning_twice_with_one_resolver_is_stable(self):
        # The deploy daemon keeps one Resolver for the life of the process.
        resolver = Resolver(GRAPH)
        plan_deploy(resolver, ["api"], already_running=["db", "cache"])
        steps = plan_deploy(resolver, ["api"])
        self.assertIn("db", steps, "a later deploy lost db because an earlier one skipped it")
        self.assertIn("cache", steps)

    def test_planning_does_not_change_start_order(self):
        resolver = Resolver(GRAPH)
        before = list(resolver.start_order("web"))
        plan_deploy(resolver, ["web"], already_running=["cdn"])
        self.assertEqual(resolver.start_order("web"), before)


if __name__ == "__main__":
    unittest.main()
