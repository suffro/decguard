"""Pure metric functions over plain sequences.

Kept dependency-free and deterministic: sums use :func:`math.fsum` over inputs in their
given order, so the same results always produce bit-identical metrics. Definitions follow
the usual conventions (scikit-learn for F1/NLL, Guo et al. 2017 for ECE); see
docs/metrics.md.
"""

from __future__ import annotations

import math
from bisect import bisect_left
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

NLL_EPSILON = 1e-15
"""Probabilities are clipped to this floor inside the log so one confident miss yields a
large but finite NLL (about 34.5) instead of infinity."""


def mean(values: Sequence[float]) -> float | None:
    return math.fsum(values) / len(values) if values else None


def accuracy(expected: Sequence[str], predicted: Sequence[str]) -> float | None:
    return mean([float(e == p) for e, p in zip(expected, predicted, strict=True)])


@dataclass(frozen=True)
class LabelScores:
    precision: float
    recall: float
    f1: float
    support: int


def per_label_scores(
    expected: Sequence[str], predicted: Sequence[str], labels: Sequence[str]
) -> dict[str, LabelScores]:
    """Precision/recall/F1 per label; undefined ratios count as 0 (scikit-learn's default)."""
    scores = {}
    for label in labels:
        tp = sum(1 for e, p in zip(expected, predicted, strict=True) if e == label and p == label)
        predicted_n = sum(1 for p in predicted if p == label)
        support = sum(1 for e in expected if e == label)
        precision = tp / predicted_n if predicted_n else 0.0
        recall = tp / support if support else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        scores[label] = LabelScores(precision, recall, f1, support)
    return scores


def macro_f1(
    expected: Sequence[str], predicted: Sequence[str], labels: Sequence[str]
) -> float | None:
    """Unweighted mean F1 over the labels that occur in ``expected`` or ``predicted``."""
    present = [label for label in labels if label in expected or label in predicted]
    if not present:
        return None
    scores = per_label_scores(expected, predicted, present)
    return math.fsum(scores[label].f1 for label in present) / len(present)


def nll(expected: Sequence[str], probabilities: Sequence[Mapping[str, float]]) -> float | None:
    """Mean negative log-likelihood (natural log) of the expected label."""
    return mean(
        [-math.log(max(p[e], NLL_EPSILON)) for e, p in zip(expected, probabilities, strict=True)]
    )


def brier(expected: Sequence[str], probabilities: Sequence[Mapping[str, float]]) -> float | None:
    """Multi-class Brier score: mean of sum_k (p_k - y_k)^2, in [0, 2]."""
    return mean(
        [
            math.fsum((value - (label == e)) ** 2 for label, value in p.items())
            for e, p in zip(expected, probabilities, strict=True)
        ]
    )


@dataclass(frozen=True)
class CalibrationBin:
    lower: float
    upper: float
    count: int
    mean_confidence: float | None
    accuracy: float | None


def reliability_bins(
    confidences: Sequence[float], correct: Sequence[bool], n_bins: int
) -> list[CalibrationBin]:
    """Equal-width bins over top-label confidence; bin i covers (i/n, (i+1)/n], the first
    bin also includes 0."""
    edges = [(i + 1) / n_bins for i in range(n_bins)]
    members: list[list[int]] = [[] for _ in range(n_bins)]
    for index, confidence in enumerate(confidences):
        members[min(bisect_left(edges, confidence), n_bins - 1)].append(index)
    bins = []
    for i, indices in enumerate(members):
        bins.append(
            CalibrationBin(
                lower=i / n_bins,
                upper=edges[i],
                count=len(indices),
                mean_confidence=mean([confidences[j] for j in indices]),
                accuracy=mean([float(correct[j]) for j in indices]),
            )
        )
    return bins


def expected_calibration_error(bins: Sequence[CalibrationBin]) -> float | None:
    """Sample-weighted mean |accuracy - confidence| over non-empty bins."""
    total = sum(b.count for b in bins)
    if total == 0:
        return None
    return math.fsum(
        b.count / total * abs(b.accuracy - b.mean_confidence)
        for b in bins
        if b.count and b.accuracy is not None and b.mean_confidence is not None
    )


def percentile(values: Sequence[float], q: float) -> float | None:
    """Linear interpolation between closest ranks (NumPy's default method)."""
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * q / 100.0
    low = math.floor(position)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def ordinal_mae(
    expected: Sequence[str], predicted: Sequence[str], levels: Sequence[str]
) -> float | None:
    """Mean absolute distance, in scale steps, between predicted and expected levels."""
    rank = {level: i for i, level in enumerate(levels)}
    return mean([float(abs(rank[p] - rank[e])) for e, p in zip(expected, predicted, strict=True)])
