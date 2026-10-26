# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
The document view of the data budget.

It reads the budget's public properties. The import is for type checking only, so the
dependency runs one way.

"""

from typing import TYPE_CHECKING

import pandas as pd
from pandas.io.formats.style import Styler

from quicksat import u
from quicksat.utils.report_helpers import bold_rows, styled_report

if TYPE_CHECKING:
    from quicksat.dataflow.budget import DataBudget

_COLUMNS = ("item", "value", "unit", "comment", "row_type")

HEADERS = {
    "item": "",
    "value": "Value",
    "unit": "Unit",
    "comment": "Comment",
}
"""The header of each column shown, by the column's name."""

FORMATS = {"value": "{:,.2f}"}
"""The format of each column of numbers, by the column's name."""

_BOLD_ROW_TYPES = frozenset({"margin", "storage"})


def tabulate(budget: "DataBudget") -> Styler:
    """
    The data budget laid out as a document, one row per quantity, in the chain's order.

    Parameters
    ----------
    budget : DataBudget
        The budget

    Returns
    -------
    report : Styler
        The budget, with its frame as `.data`
    """
    return styled_report(
        _assemble(budget), FORMATS, HEADERS, bold_rows(_BOLD_ROW_TYPES), ["row_type"]
    )


def _row(item: str, value, unit: str, comment: str, row_type: str) -> dict:
    """
    One row of the report: the item, its value in its unit, the comment and the row
    type.
    """
    return {
        "item": item,
        "value": value,
        "unit": unit,
        "comment": comment,
        "row_type": row_type,
    }


def _assemble(budget: "DataBudget") -> pd.DataFrame:
    """The report's rows, each tagged by `row_type`."""
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
            "Mass memory",
            budget.model.storage.capacity.to_value("GB"),
            "GB",
            "usable capacity",
            "input",
        ),
    ]
    orbits = budget.required_orbits
    if orbits is not None:
        rows.append(
            _row(
                "Storage required",
                budget.storage_required().to_value("GB"),
                "GB",
                f"{orbits:g} orbits without downlink",
                "storage",
            )
        )
    return pd.DataFrame(rows, columns=list(_COLUMNS))
