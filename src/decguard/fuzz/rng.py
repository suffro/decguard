"""A tiny deterministic random source.

``random.Random`` only guarantees reproducible ``random()`` output across Python versions;
``shuffle``/``sample``/``randrange`` may change. Fuzz runs must replay identically on any
supported Python, so sampling is derived from SHA-256 instead.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from typing import TypeVar

T = TypeVar("T")


class Rng:
    """Stream of integers derived from ``sha256(parts, counter)``."""

    def __init__(self, *parts: object) -> None:
        self._key = hashlib.sha256("\x1f".join(str(p) for p in parts).encode()).digest()
        self._counter = 0

    def below(self, n: int) -> int:
        """A uniform-enough integer in ``[0, n)`` (128-bit draw, negligible modulo bias)."""
        if n <= 0:
            raise ValueError("n must be positive")
        block = hashlib.sha256(self._key + self._counter.to_bytes(8, "big")).digest()
        self._counter += 1
        return int.from_bytes(block[:16], "big") % n

    def choice(self, items: Sequence[T]) -> T:
        return items[self.below(len(items))]

    def sample(self, items: Sequence[T], k: int) -> list[T]:
        """``k`` distinct positions of ``items`` (all of them if ``k >= len(items)``), in
        draw order."""
        pool = list(items)
        k = min(k, len(pool))
        for i in range(k):
            j = i + self.below(len(pool) - i)
            pool[i], pool[j] = pool[j], pool[i]
        return pool[:k]

    def shuffled(self, items: Sequence[T]) -> list[T]:
        return self.sample(items, len(items))
