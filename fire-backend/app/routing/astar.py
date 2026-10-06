"""A* pathfinding (paper §V-C, Algorithm 2).

Multi-goal search: the goal set is every usable exit (or refuge). The heuristic is the
admissible lower bound to the nearest goal, so the first goal popped is optimal.
"""

from __future__ import annotations

import heapq
import itertools
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from app.routing.graph import BuildingGraph, GEdge

# cost_fn(edge, from_node, to_node) -> cost, or None when the step is unsafe (pruned)
CostFn = Callable[[GEdge, int, int], float | None]


@dataclass(frozen=True)
class PathResult:
    path: list[int]
    cost: float
    length: float

    @property
    def goal(self) -> int:
        return self.path[-1]


def astar(
    graph: BuildingGraph,
    start: int,
    goals: Iterable[int],
    cost_fn: CostFn,
    blocked: set[int] | None = None,
) -> PathResult | None:
    goal_set = set(goals)
    blocked = blocked or set()
    goal_set -= blocked
    if not goal_set or start not in graph.nodes:
        return None
    if start in goal_set:
        return PathResult([start], 0.0, 0.0)

    def h(n: int) -> float:
        return min(graph.lower_bound(n, g) for g in goal_set)

    # 1: initialise open and closed sets; set scores
    counter = itertools.count()
    g_score: dict[int, float] = {start: 0.0}
    length_so_far: dict[int, float] = {start: 0.0}
    came_from: dict[int, int] = {}
    open_heap: list[tuple[float, int, int]] = [(h(start), next(counter), start)]
    closed: set[int] = set()

    # 2: while open set is not empty
    while open_heap:
        # 3: select node with lowest f-score
        _, _, current = heapq.heappop(open_heap)
        if current in closed:
            continue
        # 4: if goal reached then return path
        if current in goal_set:
            path = [current]
            while path[-1] in came_from:
                path.append(came_from[path[-1]])
            path.reverse()
            return PathResult(path, g_score[current], length_so_far[current])
        closed.add(current)

        # 5: for each neighbour
        for edge in graph.adjacency[current]:
            nb = edge.other(current)
            # 6: if neighbour is in unsafe segments then skip
            if nb in closed or nb in blocked:
                continue
            step = cost_fn(edge, current, nb)
            if step is None:
                continue
            # 7: compute tentative g-score
            tentative = g_score[current] + step
            # 8-10: if lower, update came-from and f-score, add to open set
            if tentative < g_score.get(nb, float("inf")):
                came_from[nb] = current
                g_score[nb] = tentative
                length_so_far[nb] = length_so_far[current] + edge.length
                heapq.heappush(open_heap, (tentative + h(nb), next(counter), nb))

    # 16: return failure if no path is found
    return None


def plain_length_cost(edge: GEdge, _a: int, _b: int) -> float:
    return edge.length
