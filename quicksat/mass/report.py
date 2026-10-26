# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
The document view of the mass budget.

It takes the equipment frame and the config, not the budget, so the dependency runs one
way.

"""

from typing import TYPE_CHECKING, Any

import pandas as pd
from pandas.io.formats.style import Styler

from quicksat.mass.equipment import MassClass
from quicksat.utils.report_helpers import bold_rows, styled_report

if TYPE_CHECKING:
    from quicksat.mass.budget import MassBudgetConfig


def tabulate(
    frame: pd.DataFrame,
    config: "MassBudgetConfig",
    in_orbit: bool = True,
    subsystem_subtotals: bool = False,
    comments: bool = False,
) -> Styler:
    """
    The mass budget laid out as a document.

    Parameters
    ----------
    frame : pd.DataFrame
        The equipment table, harness rows included
    config : MassBudgetConfig
        The margins, by location
    in_orbit : bool
        Leave out the launcher's hardware, for the in-orbit masses
    subsystem_subtotals : bool
        Add a subtotal after each subsystem
    comments : bool
        Show the comments column

    Returns
    -------
    report : Styler
        One row per item and per subtotal
    """
    report = _assemble(frame, config, in_orbit, subsystem_subtotals)
    # the subtotal and total rows name the location they close, so the
    # location column would only repeat the row above it
    hidden = ["location", "row_type"] + ([] if comments else ["comments"])
    return styled_report(report, FORMATS, HEADERS, bold_rows(_BOLD_ROW_TYPES), hidden)


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


FORMATS = {
    "units": "{:.0f}",
    "mass": "{:,.2f}",
    "total_mass": "{:,.2f}",
    "margin_pct": "{:.0f}",
    "total_mass_with_margin": "{:,.2f}",
}
"""The format of each column of numbers, by the column's name."""


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


HEADERS = {
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
"""The header of each column shown, by the column's name."""


def _row(name: str, row_type: str, **values) -> dict[str, Any]:
    """
    One report row, with the columns not given left blank. A subtotal's caption sits one
    column right of the items.
    """
    row: dict[str, Any] = dict.fromkeys(_REPORT_COLUMNS, NAN)
    row.update(equipment_id="", location="", subsystem="", comments="")
    row.update(name=name, row_type=row_type)
    row.update(values)
    return row


def _assemble(
    frame: pd.DataFrame,
    config: "MassBudgetConfig",
    in_orbit: bool,
    subsystem_subtotals: bool,
) -> pd.DataFrame:
    """
    The report's rows, in the file's order of locations and subsystems, each tagged by
    `row_type`.
    """
    is_propellant = frame["mass_class"] == MassClass.PROPELLANT.value
    hardware = frame[~is_propellant]
    if in_orbit:
        retained = hardware["location"].map(  # pyright: ignore[reportAttributeAccessIssue]
            lambda name: config.for_location(name).retained_in_orbit
        )
        hardware = hardware[retained]

    rows = []
    totals = []

    for location in hardware["location"].drop_duplicates():  # pyright: ignore[reportAttributeAccessIssue]
        block = hardware[hardware["location"] == location]

        for subsystem in block["subsystem"].drop_duplicates():  # pyright: ignore[reportAttributeAccessIssue]
            items = block[block["subsystem"] == subsystem]
            item_margined = _with_margin(items)  # pyright: ignore[reportArgumentType]
            item: Any  # itertuples() fields are columns, invisible to a checker
            for item in items.itertuples():  # pyright: ignore[reportAttributeAccessIssue]
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
        block_margined = _with_margin(block).sum()  # pyright: ignore[reportArgumentType]
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


def _with_margin(frame: pd.DataFrame) -> pd.Series:
    """Each hardware row's mass with its equipment margin."""
    return frame["eqpt_total_mass"] * (1.0 + frame["eqpt_margin"] / 100.0)
