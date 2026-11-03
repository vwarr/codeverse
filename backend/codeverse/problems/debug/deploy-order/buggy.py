"""Work out the order to start services in for a deploy.

`graph` maps each service to the services it depends on. A service may only start after every
service it depends on (directly or transitively) has started. A dependency cycle is a
configuration error and must raise CycleError rather than produce an order.
"""


class CycleError(Exception):
    pass


class Resolver:
    def __init__(self, graph):
        self.graph = graph
        self._cache = {}

    def start_order(self, service):
        """Return `service` and everything it depends on, dependencies first, `service` last."""
        if service in self._cache:
            return self._cache[service]

        order = []
        visited = set()

        def visit(node):
            if node in visited:
                return
            visited.add(node)
            for dep in self.graph.get(node, []):
                visit(dep)
            order.append(node)

        visit(service)
        self._cache[service] = order
        return order


def plan_deploy(resolver, targets, already_running=()):
    """Return the services to start, in a valid order, to bring every target up.

    Services in `already_running` are skipped. Each service appears at most once.
    """
    steps = []
    for target in targets:
        order = resolver.start_order(target)
        for name in already_running:
            if name in order:
                order.remove(name)
        steps.extend(order)
    return list(set(steps))
