# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
The Thermal tab's side of the editor's server: the key of the run and the surfaces' heat
that the server keeps, and the heat account as the tab shows it, for
`actions.thermal_files`.
"""

import hashlib
import json

import numpy as np

from quicksat import u
from quicksat.power.config import PowerSystem
from quicksat.power.orbits import run_seconds
from quicksat.thermal.account import ThermalRun
from quicksat.thermal.config import PayloadThermal

_ACCOUNT_KINDS = (
    "power",
    "payload_consumption",
    "platform_consumption",
    "payload_thermal",
)
"""The files whose changes leave the run and the surfaces' heat as they are, apart from
the parts that go into the hash on their own."""


def _without_comments(value):
    """A dumped block with every `comments` key taken out, at every depth."""
    if isinstance(value, dict):
        return {
            key: _without_comments(item)
            for key, item in value.items()
            if key != "comments"
        }
    return value


def surfaces_key(
    files: list[dict], power_system: PowerSystem, thermal: PayloadThermal
) -> str:
    """
    The hash of what the run and the surfaces' heat depend on: the scenario and its
    files, the self-shadowing and the surfaces, comments left out.

    Parameters
    ----------
    files : list of dict
        The page's files
    power_system : PowerSystem
        The power system file, for its self-shadowing
    thermal : PayloadThermal
        The thermal file, for its surfaces and the Earth

    Returns
    -------
    sha256 : str
        64 hex digits
    """
    digest = hashlib.sha256()
    kept = [file for file in files if file.get("kind") not in _ACCOUNT_KINDS]
    for file in sorted(kept, key=lambda f: (str(f.get("kind")), str(f.get("name")))):
        fields = [file.get(key) for key in ("kind", "name", "text", "base64")]
        digest.update(json.dumps(fields).encode("utf-8"))
    shadowing = power_system.self_shadowing
    digest.update(
        json.dumps(
            {
                "shading": power_system.shading,
                "self_shadowing": None
                if shadowing is None
                else _without_comments(shadowing.model_dump(mode="json")),
                "surfaces": {
                    name: _without_comments(surface.model_dump(mode="json"))
                    for name, surface in thermal.surfaces.items()
                },
                "earth": _without_comments(thermal.earth.model_dump(mode="json")),
            },
            sort_keys=True,
        ).encode("utf-8")
    )
    return digest.hexdigest()


def _records(table) -> list[dict]:
    """A table's rows for the page, with None where a value is missing."""
    return table.astype(object).where(table.notna(), None).to_dict("records")


def thermal_results(account: ThermalRun) -> dict:
    """
    The payload's heat account, as the Thermal tab shows it.

    Parameters
    ----------
    account : ThermalRun
        The heat account

    Returns
    -------
    results : dict
        The four tables as rows, the notes, the run's start, the net heat's curve in W h
        against min, and the payload's mode bands
    """
    run = account.run
    return {
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
