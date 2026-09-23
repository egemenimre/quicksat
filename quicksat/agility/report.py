# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
The document view of the agility model.

Takes the slew frame rather than an `AgilityBudget`, so the
dependency runs one way and the layout stays exercisable against a bare frame --
the same arrangement as the mass and delta-V reports.

"""

from typing import cast

import pandas as pd
from pandas.io.formats.style import Styler

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

_HEADERS = {
    "angle": "Slew [deg]",
    "profile": "Limited by",
    "slew_time": "Slew [s]",
    "total_time": "With settling [s]",
    "peak_rate": "Peak rate [deg/s]",
    "momentum_used": "Momentum used",
    "margin": "Time margin",
    "verdict": "",
}

_FORMATS = {
    "angle": "{:,.0f}",
    "slew_time": "{:,.1f}",
    "total_time": "{:,.1f}",
    "peak_rate": "{:,.4f}",
    "momentum_used": "{:.1%}",
    "margin": "{:+.1%}",
}

_LIMIT_LABELS = {"triangular": "torque", "trapezoidal": "momentum"}


def tabulate(frame: pd.DataFrame, target_duration=None) -> Styler:
    """
    The slew table laid out as a document.

    Each row is one slew angle: how long it takes, which limit binds, and how
    much of the wheel momentum it calls on. Given a target duration, it also says
    whether the manoeuvre fits -- without one those two columns are left out,
    since there is nothing to check against.

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
    return _style(_assemble(frame, target_duration))


def _assemble(frame: pd.DataFrame, target_duration=None) -> pd.DataFrame:
    """
    Adds the requirement check to the slew table, when there is one to add.

    The verdict is the thing a reader looks for first, so it gets its own column
    rather than being left implicit in the sign of a number.

    Parameters
    ----------
    frame : pd.DataFrame
        A slew table
    target_duration : Quantity, optional
        Time the operation allows. Without it the check is omitted entirely

    Returns
    -------
    report : pd.DataFrame
        The slew table, with `margin` and `verdict` columns when checked
    """
    report = frame.copy()
    report["profile"] = report["profile"].map(_LIMIT_LABELS)  # pyright: ignore[reportArgumentType]
    columns = [name for name in _COLUMNS if name not in ("margin", "verdict")]
    if target_duration is not None:
        seconds = target_duration.to("s").magnitude
        report["margin"] = (seconds - report["total_time"]) / report["total_time"]
        report["verdict"] = [
            "PASS" if fits else "FAILS" for fits in report["margin"] >= 0
        ]
        columns = list(_COLUMNS)
    return cast(pd.DataFrame, report[columns])


def _style(report: pd.DataFrame) -> Styler:
    """
    Renders the report for reading: fixed decimals, the failures marked.

    Parameters
    ----------
    report : pd.DataFrame
        The assembled report rows

    Returns
    -------
    styled : Styler
        The report rendered for reading
    """

    def _mark_failures(row):
        """Reds a row whose manoeuvre does not fit the target duration."""
        failed = row.get("verdict") == "FAILS"
        return ["color: #b00020" if failed else ""] * len(row)

    return (
        report.style.format(_FORMATS, na_rep="")  # pyright: ignore[reportArgumentType]
        .apply(_mark_failures, axis=1)  # pyright: ignore[reportAttributeAccessIssue]
        .hide(axis="index")
        .relabel_index([_HEADERS[name] for name in report.columns], axis="columns")
    )
