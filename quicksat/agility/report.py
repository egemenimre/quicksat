# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
The document view of the agility model.

It takes the slew frame rather than an `AgilityBudget`. So the dependency runs one way,
and the layout can be tested against a bare frame. The mass and delta-V reports work the
same way.

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
    """Colours a row red when its slew does not fit the target duration."""
    return "color: #b00020" if row.get("verdict") == "FAILS" else ""


def tabulate(frame: pd.DataFrame, target_duration=None) -> Styler:
    """
    The slew table laid out as a document.

    Each row is one slew angle. It gives how long the slew takes, which limit applies,
    and how much of the wheel momentum it uses. Given a target duration, it also says
    whether the slew fits. Without one, those two columns are left out, because there is
    nothing to check against.

    Parameters
    ----------
    frame : pd.DataFrame
        A slew table, as `AgilityBudget.slew_table` returns
    target_duration : Quantity, optional
        Time the operation allows for the whole manoeuvre

    Returns
    -------
    report : Styler
        One row per slew angle, rendered for reading
    """
    return styled_report(_assemble(frame, target_duration), FORMATS, HEADERS, _failed)


def _assemble(frame: pd.DataFrame, target_duration=None) -> pd.DataFrame:
    """
    Adds the requirement check to the slew table, when there is a target.

    A reader looks for the verdict first. So it gets its own column, rather than being
    left to the sign of a number.

    Parameters
    ----------
    frame : pd.DataFrame
        A slew table
    target_duration : Quantity, optional
        Time the operation allows. Without it, the check is left out

    Returns
    -------
    report : pd.DataFrame
        The slew table, with `margin` and `verdict` columns when checked
    """
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
