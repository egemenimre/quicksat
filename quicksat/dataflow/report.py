# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
Rendering of the data budget as a document.

This is presentation only. It reads a budget and lays it out, and nothing in it changes
the arithmetic.

It takes the `DataBudget` itself rather than the values. This is the one way it differs
from `mass/report.py`. The mass report takes a frame and a config, so it never imports
the budget module at all. Here, the layout needs a dozen scalars, and a function with
twelve arguments would be worse than the coupling it avoids. The import is under
`TYPE_CHECKING`, so the dependency still runs one way. Only public properties are read.

"""

from typing import TYPE_CHECKING

import pandas as pd
from pandas.io.formats.style import Styler

from quicksat import u

if TYPE_CHECKING:
    from quicksat.dataflow.budget import DataBudget

_COLUMNS = ("item", "value", "unit", "comment", "row_type")

_HEADERS = {
    "item": "",
    "value": "Value",
    "unit": "Unit",
    "comment": "Comment",
}

_BOLD_ROW_TYPES = frozenset({"margin", "storage"})


def tabulate(budget: "DataBudget") -> Styler:
    """
    The data budget laid out as a document.

    One row per quantity, in the order the chain computes them: the mission, then
    generation, then downlink, then the margin they produce, then storage.

    Parameters
    ----------
    budget : DataBudget
        The budget to render

    Returns
    -------
    report : Styler
        The budget rendered for reading, with the frame available as `.data`
    """
    return _style(_assemble(budget))


def _row(item: str, value, unit: str, comment: str, row_type: str) -> dict:
    """
    One row of the report.

    Parameters
    ----------
    item : str
        What the row reports
    value : float
        The figure, already converted to `unit`
    unit : str
        Unit the figure is expressed in
    comment : str
        The assumption behind it, or how it was derived
    row_type : str
        `input`, `derived`, `margin` or `storage`

    Returns
    -------
    row : dict
        One report row
    """
    return {
        "item": item,
        "value": value,
        "unit": unit,
        "comment": comment,
        "row_type": row_type,
    }


def _assemble(budget: "DataBudget") -> pd.DataFrame:
    """
    Builds the report rows from a budget.

    Parameters
    ----------
    budget : DataBudget
        The budget to read

    Returns
    -------
    report : pd.DataFrame
        One row per quantity, tagged by `row_type`
    """
    mission, generation, downlink = (
        budget.mission,
        budget.model.generation,
        budget.model.downlink,
    )
    margin = budget.margin.to_value(u.dimensionless_unscaled)

    rows = [
        _row(
            "Orbital period",
            mission.period.to_value("min"),
            "min",
            f"{mission.altitude:.0f} circular",
            "input",
        ),
        _row(
            "Orbits per day",
            mission.orbits_per_day.to_value(u.dimensionless_unscaled),
            "-",
            "",
            "derived",
        ),
        _row(
            "Data generation rate",
            budget.effective_datarate.to_value("Mbit/s"),
            "Mbit/s",
            f"{generation.raw_datarate:.0f} raw, {generation.compression_ratio}x compression",
            "input",
        ),
        _row(
            "Data generation duration",
            budget.generation_duration.to_value("s"),
            "s/orbit",
            f"{generation.duty_cycle:g} duty cycle",
            "input",
        ),
        _row(
            "Data generated",
            budget.generated_per_orbit.to_value("GB"),
            "GB/orbit",
            "",
            "derived",
        ),
        _row("", budget.generated_per_day.to_value("GB"), "GB/day", "", "derived"),
        _row(
            "Data downlink rate",
            downlink.rate.to_value("Mbit/s"),
            "Mbit/s",
            "achieved throughput",
            "input",
        ),
        _row(
            "Contacts",
            downlink.contacts_per_day,
            "per day",
            f"{downlink.avg_contact_duration:.0f} average duration",
            "input",
        ),
        _row(
            "Data downlink duration",
            budget.contact_per_day.to_value("min"),
            "min/day",
            "",
            "derived",
        ),
        _row(
            "Data downlinked",
            budget.downlinked_per_orbit.to_value("GB"),
            "GB/orbit",
            "",
            "derived",
        ),
        _row("", budget.downlinked_per_day.to_value("GB"), "GB/day", "", "derived"),
        _row(
            "Margin",
            margin * 100,
            "%",
            "closes" if margin >= 0 else "does not close",
            "margin",
        ),
        _row(
            "Storage required",
            budget.storage_required().to_value("GB"),
            "GB",
            f"{budget.model.storage.orbits_without_contact:g} orbits without contact",
            "storage",
        ),
    ]
    return pd.DataFrame(rows, columns=list(_COLUMNS))


def _style(report: pd.DataFrame) -> Styler:
    """
    Renders the report for reading: fixed decimals, bold results, no index.

    `row_type` is hidden rather than dropped. So the frame in `.data` can still be
    filtered by what was typed in and what was computed.

    Parameters
    ----------
    report : pd.DataFrame
        The assembled report rows

    Returns
    -------
    styled : Styler
        The report rendered for reading
    """

    def _bold_results(row):
        """Makes bold the rows that hold a result rather than a step."""
        style = "font-weight: bold" if row["row_type"] in _BOLD_ROW_TYPES else ""
        return [style] * len(row)

    headers = [_HEADERS[name] for name in report.columns if name != "row_type"]

    return (
        report.style.format({"value": "{:,.2f}"}, na_rep="")
        .apply(_bold_results, axis=1)  # pyright: ignore[reportAttributeAccessIssue]
        .hide(axis="index")
        .hide(["row_type"], axis="columns")
        .relabel_index(headers, axis="columns")
    )
