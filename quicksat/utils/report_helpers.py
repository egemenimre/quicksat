# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
Helpers for the sizing budgets' report tables, which the notebooks and the Budgets tab
share.

"""

from collections.abc import Callable, Collection

import pandas as pd
from pandas.io.formats.style import Styler


def bold_rows(row_types: Collection[str]) -> Callable[[pd.Series], str]:
    """
    A row style that makes some rows bold, such as the subtotals.

    Parameters
    ----------
    row_types : collection of str
        The `row_type` values of the bold rows

    Returns
    -------
    style : callable
        The CSS rule for one row
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

    Hidden columns stay in `.data`, and the headers are matched by the column's name.

    Parameters
    ----------
    report : pd.DataFrame
        The report's rows
    formats : dict of str to str
        Each number column's format, by name
    headers : dict of str to str
        Each shown column's header, by name
    row_style : callable
        The CSS rule for each row
    hidden : collection of str, optional
        The columns to hide

    Returns
    -------
    styled : Styler
        The report
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
