"""Route cache (paper §VI: "caching mechanisms ... minimize redundant calculations").

Keys include the graph and hazard versions plus a coarse congestion fingerprint, so a cached
route is only reused while the conditions that produced it are unchanged.
"""

from __future__ import annotations

from collections import OrderedDict
from typing import Any


class RouteCache:
    def __init__(self, max_size: int = 4096) -> None:
        self._data: OrderedDict[tuple, Any] = OrderedDict()
        self.max_size = max_size
        self.hits = 0
        self.misses = 0

    def get(self, key: tuple) -> Any:
        if key in self._data:
            self._data.move_to_end(key)
            self.hits += 1
            return self._data[key]
        self.misses += 1
        return None

    def put(self, key: tuple, value: Any) -> None:
        self._data[key] = value
        self._data.move_to_end(key)
        while len(self._data) > self.max_size:
            self._data.popitem(last=False)

    def clear(self) -> None:
        self._data.clear()


def congestion_fingerprint(congestion: dict[int, float], step: float = 0.25) -> int:
    """Hash of occupancy ratios quantised to ``step`` so tiny changes don't bust the cache."""
    return hash(tuple(sorted((n, int(r / step)) for n, r in congestion.items() if r >= step)))
