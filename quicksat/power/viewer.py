# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
The power budget for the viewer: `power.js`, beside the page and `scenario.js`.

The page is the scenario viewer's. With `power.js` beside it, the page shows a
Power tab, the net power and the battery's charge. `power.js` carries the `id`
of the `scenario.js` written with it, and the page shows the power only when the
two match. So power writes both files, from one run.

What `power.js` holds, as the page reads it:

- `format`, `version` and `scenario_id`; `power_file` and `power_text`, the power
  system file's name and text;
- `spacecraft`: the body box `body_m`, and each panel's `name`, `normal`, `axis`
  (the index of the body axis nearest the normal), `centre_m` and `size_m`,
  in body axes and metres, as the model draws it. Without a 3D model, the page
  draws the body and the panels as boxes from these.
- `grid`: on the run's grid, `generated_w` at the array's output, `consumed_w`
  with all the margins, `soc` as a share, and for each panel `sun_cos`, its
  cosine to the sun scaled by the light, and `panel_w`, its power;
- `battery`: `max_depth_of_discharge`, the page's limit line, and the capacities;
- `setup`: blocks of text for the Power tab's setup panel;
- `summary` and `checks`, from `budget_summary` and `BudgetRun.checks`.

"""

import dataclasses
import json
from pathlib import Path

import numpy as np

from quicksat import u
from quicksat.power.budget import BudgetRun, budget_summary
from quicksat.power.generation import PanelGeometry
from quicksat.scenario.spacecraft import (
    ModelGeometry,
    node_index,
    read_glb_json,
    read_model,
)
from quicksat.scenario.viewer import (
    scenario_data,
    viewer_page,
    write_scenario_js,
)

FORMAT = "quicksat-power"
"""The `format` of `power.js`, which the page checks."""

VERSION = 1
"""The version of `power.js`. The page reads a version no newer than its own."""

DATA_FILE = "power.js"
"""The name of the power data file, which the page loads from its own folder."""

PAGE_FILE = "power_viewer.html"
"""The name of the page in a power viewer folder."""


def _rounded(values, decimals: int) -> list[float]:
    """Values rounded, as a flat list."""
    return np.round(np.asarray(values, dtype=float), decimals).ravel().tolist()


def _body_box(model: ModelGeometry | None, turning: set[int]) -> list[float]:
    """
    The body box, centred on the origin: the reach of the parts that do not turn.

    Without a model, a 1 m cube, as the page draws one.
    """
    fixed = [
        part for part in (model.parts if model else []) if part.node not in turning
    ]
    if not fixed:
        return [1.0, 1.0, 1.0]
    corners = np.concatenate([part.triangles.reshape(-1, 3) for part in fixed])
    return _rounded(2 * np.abs(corners).max(axis=0), 4)


def _panel_entry(
    panel: PanelGeometry, model: ModelGeometry | None, body: list[float]
) -> dict:
    """One panel as the page draws it: a box on the body axis nearest its normal."""
    axis = int(np.argmax(np.abs(panel.normal)))
    in_plane = [k for k in range(3) if k != axis]
    part = next(
        (p for p in (model.parts if model else []) if p.node == panel.node), None
    )
    if part is not None:
        corners = part.triangles.reshape(-1, 3)
        centre = (corners.min(axis=0) + corners.max(axis=0)) / 2
        size = [float(np.ptp(corners[:, k])) for k in in_plane]
    else:
        # a typed-in panel has no place: put it on the body's face it looks out of
        centre = np.zeros(3)
        centre[axis] = np.sign(panel.normal[axis]) * body[axis] / 2
        side = float(np.sqrt(panel.area.to_value(u.m**2)))
        size = [side, side]
    return {
        "name": panel.name,
        "normal": _rounded(panel.normal, 6),
        "axis": axis,
        "centre_m": _rounded(centre, 4),
        "size_m": _rounded(size, 4),
        "area_m2": round(float(panel.area.to(u.m**2).value), 6),
        "articulation": panel.articulation,
    }


def _setup(budget: BudgetRun) -> list[dict]:
    """The Power tab's setup panel: the panels, generation, battery and loads."""
    system = budget.power_system
    battery, conditioning = budget.battery, system.conditioning
    assert conditioning is not None and system.system_margin is not None

    def percent(value) -> str:
        return f"{100 * float(value.to(u.dimensionless_unscaled).value):.0f}"

    def item(label, value, unit=""):
        return {"label": label, "value": value, "unit": unit}

    panels = budget.generation.panel_table
    margin = 1 + float(system.system_margin.to(u.dimensionless_unscaled).value)
    watts = budget.consumption.mode_watts
    shading = system.self_shadowing
    return [
        {
            "title": "Panels",
            "columns": ["Panel", "Area", "Fill", "Turns with"],
            "rows": [
                [
                    row["panel"],
                    f"{row['area [m2]']:.3f} m²",
                    f"{row['fill ratio [%]']:.0f} %",
                    row["turns with"] or "fixed",
                ]
                for row in panels.to_dict("records")
            ],
        },
        {
            "title": "Generation",
            "items": [
                item("Cell efficiency", percent(system.cell_efficiency), "%"),
                item(
                    "Loss factor",
                    f"{float(system.loss_factor.to(u.dimensionless_unscaled).value):.2f}",
                ),
                item(
                    "Self-shadowing",
                    f"{shading.points} points a panel"
                    if system.shading and shading
                    else "off",
                ),
            ],
        },
        {
            "title": "Battery",
            "items": [
                item("Capacity", f"{battery.capacity.to_value(u.W * u.h):.0f}", "W h"),
                item("Capacity left", percent(battery.capacity_factor), "%"),
                item("Usable", f"{battery.usable.to_value(u.W * u.h):.0f}", "W h"),
                item("Max depth", percent(battery.max_depth_of_discharge), "%"),
                item("Array regulator", percent(conditioning.array_regulator), "%"),
                item("Charge path", percent(conditioning.battery_charge), "%"),
                item("Discharge path", percent(conditioning.battery_discharge), "%"),
                item("Distribution", percent(conditioning.distribution), "%"),
            ],
        },
        {
            "title": "Consumption by mode",
            "columns": ["Mode", "Power"],
            "rows": [
                [mode, f"{watts[mode] * margin:.0f} W"]
                for mode in budget.consumption.consumption.modes
            ],
        },
    ]


def power_data(budget: BudgetRun, scenario_id: str) -> dict:
    """
    The contents of `power.js`, for a budget and the `scenario.js` written with it.

    Parameters
    ----------
    budget : BudgetRun
        The budget
    scenario_id : str
        The `id` of the run's `scenario.js`

    Returns
    -------
    data : dict
        The data, ready for JSON
    """
    generation = budget.generation
    run = generation.run
    spacecraft = run.scenario.spacecraft_model
    model = read_model(spacecraft.file) if spacecraft is not None else None
    turning = set()
    if model is not None and spacecraft is not None:
        gltf = read_glb_json(spacecraft.file)
        joints = {
            node_index(gltf, articulation.part)
            for articulation in spacecraft.articulations.values()
        }
        turning = {
            part.node for part in model.parts if joints & {*part.ancestors, part.node}
        }
    body = _body_box(model, turning)
    system = budget.power_system
    return {
        "format": FORMAT,
        "version": VERSION,
        "scenario_id": scenario_id,
        "power_file": system.source_file.name if system.source_file else "power system",
        "power_text": system.source_text or "",
        "spacecraft": {
            "body_m": body,
            "panels": [
                _panel_entry(panel, model, body) for panel in generation.panels.values()
            ],
        },
        "grid": {
            "generated_w": _rounded(generation.total.to_value(u.W), 2),
            "consumed_w": _rounded(budget.load.to_value(u.W), 2),
            "soc": _rounded(budget.charge, 5),
            "sun_cos": [
                _rounded(np.clip(cosine, 0, None) * run.light, 4)
                for cosine in generation.cosines.values()
            ],
            "panel_w": [
                _rounded(power.to_value(u.W), 2) for power in generation.power.values()
            ],
        },
        "battery": {
            "max_depth_of_discharge": float(
                budget.battery.max_depth_of_discharge.to(u.dimensionless_unscaled).value
            ),
            "capacity_wh": float(budget.battery.capacity.to(u.W * u.h).value),
            "usable_wh": float(budget.battery.usable.to(u.W * u.h).value),
        },
        "setup": _setup(budget),
        "summary": budget_summary(budget),
        "checks": [dataclasses.asdict(check) for check in budget.checks],
    }


def write_power_viewer(budget: BudgetRun, folder: str | Path) -> Path:  # noqa: V103
    """
    Write the viewer for a budget: the page, `scenario.js` and `power.js`.

    The page is the scenario viewer's, as `power_viewer.html`. The folder is made
    if it does not exist, and older files are replaced. Write each scenario's
    budget to a folder of its own.

    Parameters
    ----------
    budget : BudgetRun
        The budget
    folder : str | Path
        The folder to write to

    Returns
    -------
    page : Path
        The page written. Double-click it to open the viewer.
    """
    run = budget.generation.run
    scenario = scenario_data(run)
    write_scenario_js(run, folder, scenario)
    data = power_data(budget, scenario["id"])
    source = data["power_file"]
    text = (
        f"// Written by quicksat from {source}. Rerun the notebook instead of "
        "editing this file.\n"
        "window.quicksat = window.quicksat || {};\n"
        "window.quicksat.power = "
        + json.dumps(data, allow_nan=False, separators=(",", ":"))
        + ";\n"
    )
    (Path(folder) / DATA_FILE).write_text(text)
    page = Path(folder) / PAGE_FILE
    page.write_text(viewer_page(), encoding="utf-8")
    return page
