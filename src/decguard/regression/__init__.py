"""Regression comparison between two stored reports (``decguard diff``)."""

from decguard.regression.diff import DiffReport, diff_reports, load_and_diff, write_diff

__all__ = ["DiffReport", "diff_reports", "load_and_diff", "write_diff"]
