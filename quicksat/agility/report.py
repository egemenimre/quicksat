# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
The document view of the agility budget.

It takes the slew frame, not the budget, so the dependency runs one way.

"""

from typing import cast

import pandas as pd
from pandas.io.formats.style import Styler

from quicksat.utils.report_helpers import styled_report

_COLUMNS = (
    "angle",
    "profile",
    "slew_time",
    "total_time",
    "peak_rate",
    "momentum_used",
    "margin",
    "verdict",
)

HEADERS = {
    "angle": "Slew [deg]",
    "profile": "Limited by",
    "slew_time": "Slew [s]",
    "total_time": "With settling [s]",
    "peak_rate": "Peak rate [deg/s]",
    "momentum_used": "Momentum used",
    "margin": "Time margin",
    "verdict": "",
}
"""The header of each column shown, by the column's name."""

FORMATS = {
    "angle": "{:,.0f}",
    "slew_time": "{:,.1f}",
    "total_time": "{:,.1f}",
    "peak_rate": "{:,.4f}",
    "momentum_used": "{:.1%}",
    "margin": "{:+.1%}",
}
"""The format of each column of numbers, by the column's name."""

_LIMIT_LABELS = {"triangular": "torque", "trapezoidal": "momentum"}


def _failed(row: pd.Series) -> str:
    """Colours a row red when its slew does not fit."""
    return "color: #b00020" if row.get("verdict") == "FAILS" else ""


def tabulate(frame: pd.DataFrame, target_duration=None) -> Styler:
    """
    The slew table laid out as a document.

    Given a target duration, it also says whether each slew fits.

    Parameters
    ----------
    frame : pd.DataFrame
        A slew table, from `AgilityBudget.slew_table`
    target_duration : Quantity, optional
        The time allowed for the whole manoeuvre

    Returns
    -------
    report : Styler
        One row per slew angle
    """
    return styled_report(_assemble(frame, target_duration), FORMATS, HEADERS, _failed)


def _assemble(frame: pd.DataFrame, target_duration=None) -> pd.DataFrame:
    """The slew table, with the margin and the verdict when there is a target."""
    report = frame.copy()
    report["profile"] = report["profile"].map(_LIMIT_LABELS)  # pyright: ignore[reportArgumentType]
    columns = [name for name in _COLUMNS if name not in ("margin", "verdict")]
    if target_duration is not None:
        seconds = target_duration.to_value("s")
        report["margin"] = (seconds - report["total_time"]) / report["total_time"]
        report["verdict"] = [
            "PASS" if fits else "FAILS" for fits in report["margin"] >= 0
        ]
        columns = list(_COLUMNS)
    return cast(pd.DataFrame, report[columns])
