# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
The payload's heat account as the viewer's and the editor's Thermal tabs show it.

Power does not import thermal, so the thermal command and the editor pass this block to
`write_power_viewer`, which puts it in `power.js` as `thermal`.

"""

import numpy as np

from quicksat import u
from quicksat.power.orbits import run_seconds
from quicksat.thermal.account import ThermalRun


def _records(table) -> list[dict]:
    """A table's rows for the page, with None where a value is missing."""
    return table.astype(object).where(table.notna(), None).to_dict("records")


def thermal_data(account: ThermalRun) -> dict:
    """
    The payload's heat account, as the Thermal tabs show it.

    Parameters
    ----------
    account : ThermalRun
        The heat account

    Returns
    -------
    data : dict
        The thermal file's name and text, the four tables as rows, the notes, the run's
        start, the net heat's curve in W h against min, and the payload's mode bands
    """
    run = account.run
    thermal = account.thermal
    return {
        "file": None if thermal.source_file is None else thermal.source_file.name,
        "text": thermal.source_text,
        "activities": _records(account.activity_table),
        "modes": _records(account.mode_table),
        "orbits": _records(account.orbit_table),
        "surfaces": _records(account.surface_table),
        "notes": account.notes,
        "start": run.times[0].utc.isot,
        "t_min": [round(float(t) / 60, 4) for t in run_seconds(run)],
        "energy_wh": [
            round(float(e), 4)
            for e in np.asarray(account.running_energy.to(u.W * u.h).value)
        ],
        "bands": [
            {"mode": mode, "start_min": start / 60, "end_min": end / 60}
            for start, end, mode in account.pieces
        ],
    }
