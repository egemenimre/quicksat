# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
Rendering of the delta-V budget as a document.

This is presentation only. It reads a resolved manoeuvre table and lays it out, and
nothing in it changes the arithmetic. It takes the frame and the config rather than a
`DeltaVBudget`. So the dependency runs one way only, and the layout can be tested
against a bare frame.

"""

from typing import TYPE_CHECKING, Any

import pandas as pd
from pandas.io.formats.style import Styler

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

_HEADERS = {
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

_FORMATS = {
    "loss_factor": "{:,.3g}",
    "each": "{:,.3f}",
    "occurrences": "{:,.1f}",
    "deltav": "{:,.2f}",
}

_BOLD_ROW_TYPES = frozenset({"phase_subtotal", "subtotal", "margin", "total"})


def tabulate(
    frame: pd.DataFrame,
    config: "DeltaVConfig",
    margin: bool = True,
    comments: bool = False,
    loss_factor: bool = False,
) -> Styler:
    """
    The delta-V budget laid out as a document.

    Manoeuvres are grouped into mission phases, each with a subtotal. Then come the
    budget total, the margin, and the total with margin.

    Parameters
    ----------
    frame : pd.DataFrame
        A resolved manoeuvre table, as `DeltaVBudget.resolve` returns
    config : DeltaVConfig
        Budget settings, for the margin
    margin : bool
        Show the margin line and the total that includes it
    comments : bool
        Show the manoeuvre file's comments column
    loss_factor : bool
        Show the loss factor that scaled each manoeuvre's delta-V

    Returns
    -------
    report : Styler
        One row per manoeuvre and per subtotal, rendered for reading
    """
    return _style(_assemble(frame, config, margin), comments, loss_factor)


def _row(manoeuvre_id: str, name: str, row_type: str, **values) -> dict[str, Any]:
    """
    One row of the report, with everything not supplied left blank.

    Parameters
    ----------
    manoeuvre_id : str
        The item's id, blank on the summary rows so captions indent
    name : str
        The manoeuvre name, or the caption for a subtotal
    row_type : str
        What kind of row this is
    **values
        Any report columns that apply to this row

    Returns
    -------
    row : dict[str, Any]
        One report row
    """
    row: dict[str, Any] = dict.fromkeys(_COLUMNS, NAN)
    row.update(manoeuvre_id=manoeuvre_id, name=name, type="", value="", comments="")
    row.update(row_type=row_type)
    row.update(values)
    return row


def _assemble(
    frame: pd.DataFrame, config: "DeltaVConfig", margin: bool
) -> pd.DataFrame:
    """
    Builds the report rows from a resolved manoeuvre table.

    Phases keep the order in which they first appear, rather than being sorted. So the
    report keeps the structure of the manoeuvre file. That order is usually
    chronological, so the report follows the mission.

    Parameters
    ----------
    frame : pd.DataFrame
        A resolved manoeuvre table
    config : DeltaVConfig
        Budget settings, for the margin
    margin : bool
        Add the margin and the total with margin

    Returns
    -------
    report : pd.DataFrame
        One row per manoeuvre and per subtotal, tagged by `row_type`
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


def _style(report: pd.DataFrame, comments: bool, loss_factor: bool) -> Styler:
    """
    Renders the report for reading: blanks instead of NaN, bold summaries.

    Columns are hidden rather than dropped, so `.data` stays complete whatever the
    flags. Headers are looked up per column, rather than passed as a list by position. A
    list would no longer match as soon as a column is hidden.

    Parameters
    ----------
    report : pd.DataFrame
        The assembled report rows
    comments : bool
        Show the comments column
    loss_factor : bool
        Show the loss factor column. Off by default, because in a budget of impulsive
        burns it is a column of ones. It is worth the width only once a manoeuvre has a
        correction

    Returns
    -------
    styled : Styler
        The report rendered for reading
    """

    def _bold_summary(row):
        """Makes a row bold if it is a subtotal or a total."""
        style = "font-weight: bold" if row["row_type"] in _BOLD_ROW_TYPES else ""
        return [style] * len(row)

    hidden = ["row_type"]
    if not comments:
        hidden.append("comments")
    if not loss_factor:
        hidden.append("loss_factor")
    headers = [_HEADERS[name] for name in report.columns if name not in hidden]

    return (
        report.style.format(_FORMATS, na_rep="")  # pyright: ignore[reportArgumentType]
        .apply(_bold_summary, axis=1)  # pyright: ignore[reportAttributeAccessIssue]
        .hide(axis="index")
        .hide(hidden, axis="columns")
        .relabel_index(headers, axis="columns")
    )
