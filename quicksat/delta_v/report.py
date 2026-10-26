# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
The document view of the delta-V budget.

It takes the resolved frame and the config, not the budget, so the dependency runs one
way.

"""

from typing import TYPE_CHECKING, Any

import pandas as pd
from pandas.io.formats.style import Styler

from quicksat.utils.report_helpers import bold_rows, styled_report

if TYPE_CHECKING:
    from quicksat.delta_v.budget import DeltaVConfig

NAN = float("nan")

_COLUMNS = (
    "manoeuvre_id",
    "name",
    "type",
    "value",
    "loss_factor",
    "each",
    "occurrences",
    "deltav",
    "comments",
    "row_type",
)

HEADERS = {
    "manoeuvre_id": "Item",
    "name": "Name",
    "type": "Type",
    "value": "Input",
    "loss_factor": "Loss factor",
    "each": "ΔV each [m/s]",
    "occurrences": "Times",
    "deltav": "ΔV total [m/s]",
    "comments": "Comments",
}
"""The header of each column shown, by the column's name."""

FORMATS = {
    "loss_factor": "{:,.3g}",
    "each": "{:,.3f}",
    "occurrences": "{:,.1f}",
    "deltav": "{:,.2f}",
}
"""The format of each column of numbers, by the column's name."""

_BOLD_ROW_TYPES = frozenset({"phase_subtotal", "subtotal", "margin", "total"})


def tabulate(
    frame: pd.DataFrame,
    config: "DeltaVConfig",
    margin: bool = True,
    comments: bool = False,
    loss_factor: bool = False,
) -> Styler:
    """
    The delta-V budget laid out as a document: the manoeuvres by phase, with subtotals,
    then the total and the margin.

    Parameters
    ----------
    frame : pd.DataFrame
        A resolved manoeuvre table, from `DeltaVBudget.resolve`
    config : DeltaVConfig
        The budget's settings, for the margin
    margin : bool
        Show the margin and the total with it
    comments : bool
        Show the comments column
    loss_factor : bool
        Show each manoeuvre's loss factor

    Returns
    -------
    report : Styler
        One row per manoeuvre and per subtotal
    """
    report = _assemble(frame, config, margin)
    hidden = ["row_type"]
    if not comments:
        hidden.append("comments")
    # in a budget of impulsive burns, the loss factor is a column of ones
    if not loss_factor:
        hidden.append("loss_factor")
    return styled_report(report, FORMATS, HEADERS, bold_rows(_BOLD_ROW_TYPES), hidden)


def _row(manoeuvre_id: str, name: str, row_type: str, **values) -> dict[str, Any]:
    """One report row, with the columns not given left blank."""
    row: dict[str, Any] = dict.fromkeys(_COLUMNS, NAN)
    row.update(manoeuvre_id=manoeuvre_id, name=name, type="", value="", comments="")
    row.update(row_type=row_type)
    row.update(values)
    return row


def _assemble(
    frame: pd.DataFrame, config: "DeltaVConfig", margin: bool
) -> pd.DataFrame:
    """
    The report's rows, with the phases in the file's order, each tagged by `row_type`.
    """
    rows = []

    for phase in frame["phase"].drop_duplicates():
        block = frame[frame["phase"] == phase]
        item: Any  # itertuples() fields are columns, invisible to a checker
        for item in block.itertuples():
            rows.append(
                _row(
                    item.manoeuvre_id,
                    item.manoeuvre_name,
                    "manoeuvre",
                    type=item.manoeuvre_type,
                    value=f"{item.value:.6g}",
                    loss_factor=item.loss_factor,
                    each=item.deltav_each,
                    occurrences=item.occurrences,
                    deltav=item.deltav_total,
                    comments=item.comments,
                )
            )
        rows.append(
            _row(
                "",
                f"{phase} subtotal",
                "phase_subtotal",
                deltav=block["deltav_total"].sum(),
            )
        )

    subtotal = frame["deltav_total"].sum()
    rows.append(_row("", "Total, before margin", "subtotal", deltav=subtotal))

    if margin:
        allowance = subtotal * config.margin / 100.0
        rows.append(
            _row("", f"Margin ({config.margin:g}%)", "margin", deltav=allowance)
        )
        rows.append(_row("", "Total ΔV", "total", deltav=subtotal + allowance))

    return pd.DataFrame(rows, columns=list(_COLUMNS))
