# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
Helpers for the sizing budgets' report tables.

Each budget's `report.py` builds its table as a frame, and renders it for
reading with `styled_report`. The editor's Budgets tab reads the same frame, with
the same headers and formats, so the two show the same table.

"""

from collections.abc import Callable, Collection

import pandas as pd
from pandas.io.formats.style import Styler


def bold_rows(row_types: Collection[str]) -> Callable[[pd.Series], str]:
    """
    A row style that makes some rows bold, such as the subtotals and the total.

    Parameters
    ----------
    row_types : collection of str
        The values of the `row_type` column whose rows are bold

    Returns
    -------
    style : callable
        The CSS rule for one row of the report
    """
    return lambda row: "font-weight: bold" if row["row_type"] in row_types else ""


def styled_report(
    report: pd.DataFrame,
    formats: dict[str, str],
    headers: dict[str, str],
    row_style: Callable[[pd.Series], str],
    hidden: Collection[str] = (),
) -> Styler:
    """
    A report table, rendered for reading.

    The cells take their formats, and an empty cell shows as a blank. The index
    is hidden, and each column takes its header. Columns are hidden rather than
    dropped, so the frame in `.data` keeps them all. The headers are found by the
    column's name, rather than given as a list by position, which would no
    longer match once a column is hidden.

    Parameters
    ----------
    report : pd.DataFrame
        The report's rows
    formats : dict of str to str
        The format of each column of numbers, by the column's name
    headers : dict of str to str
        The header of each column shown, by the column's name
    row_style : callable
        The CSS rule for each row, given the row
    hidden : collection of str, optional
        The columns to hide

    Returns
    -------
    styled : Styler
        The report rendered for reading
    """
    styled = (
        report.style.format(formats, na_rep="")  # pyright: ignore[reportArgumentType]
        .apply(lambda row: [row_style(row)] * len(row), axis=1)  # pyright: ignore[reportAttributeAccessIssue]
        .hide(axis="index")
    )
    if hidden:
        styled = styled.hide(list(hidden), axis="columns")
    shown = [headers[name] for name in report.columns if name not in hidden]
    return styled.relabel_index(shown, axis="columns")
