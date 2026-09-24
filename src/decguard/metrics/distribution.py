"""Distances between two probability distributions over the same labels.

Pure functions over ``{label: probability}`` mappings, iterated in the given canonical
label order so results are deterministic.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence


def tv_distance(p: Mapping[str, float], q: Mapping[str, float], labels: Sequence[str]) -> float:
    """Total variation distance: half the L1 distance, in [0, 1]."""
    return min(1.0, 0.5 * math.fsum(abs(p[label] - q[label]) for label in labels))


def max_abs_delta(p: Mapping[str, float], q: Mapping[str, float], labels: Sequence[str]) -> float:
    """Largest absolute change of any single label's probability."""
    return max(abs(p[label] - q[label]) for label in labels)


def js_divergence(p: Mapping[str, float], q: Mapping[str, float], labels: Sequence[str]) -> float:
    """Jensen-Shannon divergence in bits, in [0, 1]. Symmetric and finite for any inputs."""
    terms = []
    for label in labels:
        a, b = p[label], q[label]
        m = (a + b) / 2.0
        if a > 0.0:
            terms.append(0.5 * a * math.log2(a / m))
        if b > 0.0:
            terms.append(0.5 * b * math.log2(b / m))
    return min(1.0, max(0.0, math.fsum(terms)))


def expected_level(p: Mapping[str, float], labels: Sequence[str]) -> float:
    """Probability-weighted mean position on an ordered scale (lowest label = 0)."""
    return math.fsum(index * p[label] for index, label in enumerate(labels))


def ranking(p: Mapping[str, float], labels: Sequence[str]) -> tuple[str, ...]:
    """Labels from most to least probable; ties keep the canonical order."""
    position = {label: index for index, label in enumerate(labels)}
    return tuple(sorted(labels, key=lambda label: (-p[label], position[label])))
