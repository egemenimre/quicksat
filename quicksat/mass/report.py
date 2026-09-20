# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
Rendering of the mass budget as a document.

Presentation only: everything here reads a budget table and lays it out, and
nothing in it feeds back into the arithmetic. It takes the equipment frame and the
config rather than a `MassBudget`, which keeps the dependency one-directional and
lets the report be exercised against a bare frame.

"""

from typing import TYPE_CHECKING, Any

import pandas as pd
from pandas.io.formats.style import Styler

from quicksat.mass.equipment import MassClass

if TYPE_CHECKING:
    from quicksat.mass.budget import BudgetConfig


def tabulate(
    frame: pd.DataFrame,
    config: "BudgetConfig",
    in_orbit: bool = True,
    subsystem_subtotals: bool = False,
    comments: bool = False,
) -> Styler:
    """
    The mass budget laid out as a document.

    Parameters
    ----------
    frame : pd.DataFrame
        The validated equipment table, harness rows included
    config : BudgetConfig
        Margin settings, keyed on location
    in_orbit : bool
        Drop hardware left with the launcher, and report the in-orbit masses
    subsystem_subtotals : bool
        Add a subtotal line after each subsystem block
    comments : bool
        Show the equipment file's comments column

    Returns
    -------
    report : Styler
        One row per item and per subtotal, rendered for reading
    """
    return _style(_assemble(frame, config, in_orbit, subsystem_subtotals), comments)


NAN = float("nan")


_REPORT_COLUMNS = (
    "equipment_id",
    "name",
    "location",
    "subsystem",
    "units",
    "mass",
    "total_mass",
    "margin_pct",
    "total_mass_with_margin",
    "comments",
    "row_type",
)


_REPORT_FORMATS = {
    "units": "{:.0f}",
    "mass": "{:,.2f}",
    "total_mass": "{:,.2f}",
    "margin_pct": "{:.0f}",
    "total_mass_with_margin": "{:,.2f}",
}


_BOLD_ROW_TYPES = frozenset(
    {
        "subsystem_subtotal",
        "location_subtotal",
        "location_total",
        "dry_total",
        "propellant",
        "wet_total",
    }
)


_COLUMN_HEADERS = {
    "equipment_id": "Item",
    "name": "Name",
    "location": "Location",
    "subsystem": "Subsystem",
    "units": "Units",
    "mass": "Mass [kg]",
    "total_mass": "Total Mass [kg]",
    "margin_pct": "Margin [%]",
    "total_mass_with_margin": "Total + Margin [kg]",
    "comments": "Comments",
}


def _row(name: str, row_type: str, **values) -> dict[str, Any]:
    """
    One row of the tabulated report, with everything not supplied left blank.

    `name` carries the equipment name on an item row and the subtotal caption on
    the rows between them. Subtotals leave `equipment_id` blank, so the captions
    line up one column in from the items they summarise.

    Parameters
    ----------
    name : str
        Equipment name, or the caption for a subtotal row
    row_type : str
        What kind of row this is, used for styling and filtering
    **values
        Any report columns that apply to this row

    Returns
    -------
    row : dict[str, Any]
        One report row, with unsupplied columns left blank
    """
    row: dict[str, Any] = dict.fromkeys(_REPORT_COLUMNS, NAN)
    row.update(equipment_id="", location="", subsystem="", comments="")
    row.update(name=name, row_type=row_type)
    row.update(values)
    return row


def _assemble(
    frame: pd.DataFrame,
    config: "BudgetConfig",
    in_orbit: bool,
    subsystem_subtotals: bool,
) -> pd.DataFrame:
    """
    Assembles the mass budget document.

    Locations and subsystems come out in order of first appearance in the equipment
    file rather than sorted, so the report keeps the structure the file was written
    with — and the derived harness, appended last, lands at the foot of its location.

    Parameters
    ----------
    frame : pd.DataFrame
        The validated equipment table, harness rows included
    config : BudgetConfig
        Margin settings, keyed on location
    in_orbit : bool
        Drop hardware left with the launcher, and report the in-orbit masses
    subsystem_subtotals : bool
        Add a subtotal line after each subsystem block

    Returns
    -------
    report : pd.DataFrame
        One row per item and per subtotal, tagged by `row_type`
    """
    is_propellant = frame["mass_class"] == MassClass.PROPELLANT.value
    hardware = frame[~is_propellant]
    if in_orbit:
        retained = hardware["location"].map(
            lambda name: config.for_location(name).retained_in_orbit
        )
        hardware = hardware[retained]

    rows = []
    totals = []

    for location in hardware["location"].drop_duplicates():
        block = hardware[hardware["location"] == location]

        for subsystem in block["subsystem"].drop_duplicates():
            items = block[block["subsystem"] == subsystem]
            item_margined = _with_margin(items)
            item: Any  # itertuples() fields are columns, invisible to a checker
            for item in items.itertuples():
                rows.append(
                    _row(
                        item.equipment_name,
                        "equipment",
                        equipment_id=item.equipment_id,
                        location=location,
                        comments=item.comments,
                        subsystem=subsystem,
                        units=item.number_of_units,
                        mass=item.eqpt_mass,
                        margin_pct=item.eqpt_margin,
                        total_mass=item.eqpt_total_mass,
                        total_mass_with_margin=item_margined.loc[item.Index],
                    )
                )
            if subsystem_subtotals:
                rows.append(
                    _row(
                        f"{subsystem} subtotal",
                        "subsystem_subtotal",
                        location=location,
                        subsystem=subsystem,
                        total_mass=items["eqpt_total_mass"].sum(),
                        total_mass_with_margin=item_margined.sum(),
                    )
                )

        block_raw = block["eqpt_total_mass"].sum()
        block_margined = _with_margin(block).sum()
        margin_pct = config.for_location(location).system_margin
        margin_kg = block_margined * margin_pct / 100.0

        rows.append(
            _row(
                f"{location} subtotal (before system margin)",
                "location_subtotal",
                location=location,
                total_mass=block_raw,
                total_mass_with_margin=block_margined,
            )
        )
        rows.append(
            _row(
                f"{location} total",
                "location_total",
                location=location,
                total_mass=block_margined,
                margin_pct=margin_pct,
                total_mass_with_margin=block_margined + margin_kg,
            )
        )
        totals.append((block_raw, block_margined, block_margined + margin_kg))

    dry_margined = sum(entry[1] for entry in totals)
    dry_total = sum(entry[2] for entry in totals)
    propellant_kg = frame.loc[is_propellant, "eqpt_total_mass"].sum()

    rows.append(
        _row(
            "Total Dry Mass (with system margin)",
            "dry_total",
            total_mass=dry_margined,
            total_mass_with_margin=dry_total,
        )
    )
    rows.append(
        _row(
            "Propellant",
            "propellant",
            total_mass=propellant_kg,
            total_mass_with_margin=propellant_kg,
        )
    )
    rows.append(
        _row(
            "Total Wet Mass",
            "wet_total",
            total_mass=dry_margined + propellant_kg,
            total_mass_with_margin=dry_total + propellant_kg,
        )
    )

    return pd.DataFrame(rows, columns=list(_REPORT_COLUMNS))


def _style(report: pd.DataFrame, comments: bool) -> Styler:
    """
    Renders the report for reading: blanks instead of NaN, fixed decimals, bold
    subtotals, and human-friendly column headers with units.

    Columns are hidden rather than dropped, so `.data` stays complete: `row_type`
    is what makes the report filterable, `location` is worth grouping on, and the
    comments are worth keeping to hand. `location` is hidden because the subtotal
    and total rows already name the location they close, so the column only repeats
    what the row above it says.

    Headers are looked up per column rather than passed as a positional list, which
    would silently mismatch whenever a column is added or hidden.

    Parameters
    ----------
    report : pd.DataFrame
        The assembled report rows
    comments : bool
        Show the equipment file's comments column

    Returns
    -------
    styled : Styler
        The report rendered for reading
    """

    def _bold_summary(row):
        """
        Bolds a row if it is a subtotal or a total.

        Parameters
        ----------
        row : pd.Series
            One report row

        Returns
        -------
        styles : list[str]
            One CSS rule per cell of the row
        """
        style = "font-weight: bold" if row["row_type"] in _BOLD_ROW_TYPES else ""
        return [style] * len(row)

    hidden = ["location", "row_type"]
    if not comments:
        hidden.append("comments")
    headers = [_COLUMN_HEADERS[name] for name in report.columns if name not in hidden]

    return (
        report.style.format(_REPORT_FORMATS, na_rep="")
        .apply(_bold_summary, axis=1)
        .hide(axis="index")
        .hide(hidden, axis="columns")
        .relabel_index(headers, axis="columns")
    )


def _with_margin(frame: pd.DataFrame) -> pd.Series:
    """
    Margined mass per row, for the hardware rows of the report.

    Parameters
    ----------
    frame : pd.DataFrame
        Equipment rows to margin

    Returns
    -------
    mass : pd.Series
        Total mass with the per-item margin applied, aligned with `frame`
    """
    return frame["eqpt_total_mass"] * (1.0 + frame["eqpt_margin"] / 100.0)
