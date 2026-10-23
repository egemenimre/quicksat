# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
The sizing budgets' results, as the Sizing Editor's Budgets tab shows them.

`budget_results` reads a folder of sizing files with quicksat's loaders, works
out each budget whose files are there, and gives the page its figures, its
tables and its checks. The tables are the ones the notebooks show, from the same
methods, with the same headings and decimals. Every figure and every cell
reaches the page as text, so the page formats no number of its own. A number
also comes in full, for the page's Excel export.

A budget whose files are missing has no results. A budget that quicksat cannot
work out has an error in place of its results, and the others are still worked
out.

"""

import math
import numbers
from collections.abc import Callable
from pathlib import Path

import pandas as pd

from quicksat.agility import report as agility_report
from quicksat.agility.budget import AgilityBudget, AgilityConfig, Axis
from quicksat.dataflow import report as data_report
from quicksat.dataflow.budget import DataBudget, DataFlowModel
from quicksat.delta_v import report as delta_v_report
from quicksat.delta_v.budget import DeltaVBudget
from quicksat.editor.sizing import NAMES
from quicksat.mass import report as mass_report
from quicksat.mass.budget import MassBudget
from quicksat.utils.checks import Check
from quicksat.utils.checks import tabulate as tabulate_checks
from quicksat.utils.mission import Mission
from quicksat.utils.requirements import Requirements

_MARGINS = (
    ("No margin [kg]", {"eqpt_margin": False, "sys_margin": False}),
    ("With eqpt margin [kg]", {"sys_margin": False}),
    ("With sys margin [kg]", {}),
)
"""The three margin levels of the mass budget's grouped views, as the mass
notebook compares them."""


def _text(value, spec: str | None = None) -> str:
    """A cell as the page shows it: formatted when it is a number, and blank when empty."""
    if value is None or (isinstance(value, float) and value != value):
        return ""
    if spec and isinstance(value, numbers.Number) and not isinstance(value, bool):
        return spec.format(value)
    return str(value)


def _value(value) -> float | None:
    """A cell's number in full, for the export. None for text, and for an empty or infinite number."""
    if isinstance(value, numbers.Real) and not isinstance(value, bool):
        value = float(value)
        return value if math.isfinite(value) else None
    return None


def _q(quantity, unit: str, spec: str = "{:,.2f}") -> str:
    """A quantity's value in `unit`, as text, without the unit."""
    return spec.format(quantity.to_value(unit))


def _v(quantity, unit: str, spec: str = "{:,.2f}") -> tuple[float, str]:
    """A quantity's value in `unit`, with the format the page shows it in."""
    return quantity.to_value(unit), spec


def _figure(
    label: str,
    value: tuple[float, str],
    unit: str = "",
    note: str = "",
    bad=False,
    headline=False,
) -> dict:
    """
    One of the figures above a budget's tables, from its number and its format.
    A headline figure also goes on the overview.
    """
    number, spec = value
    return {
        "label": label,
        "value": _text(number, spec),
        "number": _value(number),
        "unit": unit,
        "note": note,
        "bad": bool(bad),
        "headline": headline,
    }


def _report(frame: pd.DataFrame, headers: dict, formats: dict) -> dict:
    """
    A budget's report table, as its notebook shows it.

    Parameters
    ----------
    frame : pd.DataFrame
        The report's frame, as its Styler's `.data` holds it
    headers : dict
        The heading of each column to show, by the column's name
    formats : dict
        The format of each column of numbers, by the column's name

    Returns
    -------
    table : dict
        `columns`, each with its `key`, `title` and whether it holds numbers,
        and `rows`, each with its `type`, its `cells` as text, and its `values`:
        the number of each cell in a column of numbers, and None for the others
    """
    keys = [key for key in frame.columns if key in headers]
    return {
        "columns": [
            {"key": key, "title": headers[key], "number": key in formats}
            for key in keys
        ],
        "rows": [
            {
                # a slew that does not fit is marked, as the notebook marks it
                "type": record.get("row_type")
                or ("fails" if record.get("verdict") == "FAILS" else ""),
                "cells": [_text(record[key], formats.get(key)) for key in keys],
                "values": [
                    _value(record[key]) if key in formats else None for key in keys
                ],
            }
            for record in frame.to_dict("records")
        ],
    }


def _rows(titles: list[str], rows: list[tuple[str, list]], spec="{:,.2f}") -> dict:
    """
    A small table, from rows of cells. A cell is text, a number in the table's
    format `spec`, or a number with its own format, as `(number, format)`.
    A column holds numbers when one of its cells does.
    """
    table = []
    for kind, cells in rows:
        pairs = [cell if isinstance(cell, tuple) else (cell, spec) for cell in cells]
        table.append(
            {
                "type": kind,
                "cells": [_text(value, form) for value, form in pairs],
                "values": [_value(value) for value, _ in pairs],
            }
        )
    return {
        "columns": [
            {
                "key": f"c{i}",
                "title": title,
                "number": any(row["values"][i] is not None for row in table),
            }
            for i, title in enumerate(titles)
        ],
        "rows": table,
    }


def _mass(mass: MassBudget) -> dict:
    """The mass budget's figures and tables."""
    budget = {}
    for in_orbit in (True, False):
        for subtotals in (False, True):
            frame = mass.tabulated_mass(in_orbit, subtotals, comments=True).data
            budget[f"{int(in_orbit)}{int(subtotals)}"] = _report(
                frame, mass_report._COLUMN_HEADERS, mass_report._REPORT_FORMATS
            )

    def grouped(view: Callable[..., pd.DataFrame], heading: str) -> dict:
        frames = [view(**flags)["mass"] for _, flags in _MARGINS]
        rows = [
            ("item", [str(name), *[f[name] for f in frames]])
            for name in frames[0].index
        ]
        rows.append(("total", ["Total", *[f.sum() for f in frames]]))
        return _rows([heading, *[title for title, _ in _MARGINS]], rows)

    points = [
        ("At launch, wet", mass.on_ground_mass()),
        ("At launch, dry", mass.on_ground_mass(propellant=0)),
        *[
            (f"In orbit, {share} % propellant", mass.in_orbit_mass(propellant=share))
            for share in (100, 75, 50, 25, 0)
        ],
    ]
    return {
        "figures": [
            _figure(
                "Launch mass",
                _v(mass.on_ground_mass(), "kg"),
                "kg",
                "on the ground, wet",
                headline=True,
            ),
            _figure(
                "In orbit, wet",
                _v(mass.in_orbit_mass(), "kg"),
                "kg",
                f"{_q(mass.in_orbit_mass(propellant=0), 'kg')} kg dry",
                headline=True,
            ),
            _figure(
                "In orbit, dry",
                _v(mass.in_orbit_mass(propellant=0), "kg"),
                "kg",
                "the delta-V budget's dry mass",
            ),
            _figure("Propellant", _v(mass.propellant_mass(), "kg"), "kg", "loaded"),
            _figure(
                "Platform", _v(mass.platform_mass(), "kg"), "kg", "by location, wet"
            ),
            _figure("Payload", _v(mass.payload_mass(), "kg"), "kg", "by location"),
        ],
        "tables": {
            "budget": budget,
            "by_location": grouped(mass.by_location, "Location"),
            "by_subsystem": grouped(mass.by_subsystem, "Subsystem"),
            "points": _rows(
                ["Point of the mission", "Mass [kg]"],
                [("item", [label, _v(value, "kg")]) for label, value in points],
            ),
        },
    }


def _delta_v(delta_v: DeltaVBudget) -> dict:
    """The delta-V budget's figures and tables."""
    margin = delta_v.config.margin

    def grouped(frame: pd.DataFrame, heading: str) -> dict:
        values = frame["deltav"]
        rows = [("item", [str(name), values[name]]) for name in frame.index]
        rows.append(("total", ["Total", values.sum()]))
        return _rows([heading, "ΔV with margin [m/s]"], rows)

    figures = [
        _figure(
            "Delta-V",
            _v(delta_v.total_deltav(), "m/s"),
            "m/s",
            f"with the {margin:g} % margin",
            headline=True,
        ),
        _figure(
            "Before margin",
            _v(delta_v.total_deltav(margin=False), "m/s"),
            "m/s",
            f"{len(delta_v.resolve())} manoeuvres",
        ),
    ]
    tables = {
        "budget": _report(
            delta_v.tabulated_deltav(comments=True).data,
            delta_v_report._HEADERS,
            delta_v_report._FORMATS,
        ),
        "by_phase": grouped(delta_v.by_phase(), "Phase"),
        "by_type": grouped(delta_v.by_type(), "Type"),
    }
    if delta_v.mass_budget is not None:
        required = delta_v.propellant_mass()
        loaded = delta_v.mass_budget.propellant_mass()
        spare = loaded - required
        figures += [
            _figure(
                "Propellant needed",
                _v(required, "kg"),
                "kg",
                f"Isp {delta_v.config.propulsion.isp:g}",
            ),
            _figure(
                "Propellant loaded",
                _v(loaded, "kg"),
                "kg",
                f"{_q(required, 'kg')} kg needed: "
                f"{'short by' if spare.value < 0 else 'spare'} {abs(spare.value):,.2f} kg",
                bad=spare.value < 0,
                headline=True,
            ),
        ]
        dry = delta_v.mass_budget.in_orbit_mass(propellant=0)
        isp = delta_v.config.propulsion.isp
        tables["propellant"] = _rows(
            ["", "Value", "Unit"],
            [
                ("item", ["In-orbit dry mass", _v(dry, "kg"), "kg"]),
                (
                    "item",
                    ["Delta-V, with margin", _v(delta_v.total_deltav(), "m/s"), "m/s"],
                ),
                ("item", ["Specific impulse", _v(isp, "s", "{:g}"), "s"]),
                ("total", ["Propellant required", _v(required, "kg"), "kg"]),
                ("item", ["Propellant loaded", _v(loaded, "kg"), "kg"]),
            ],
        )
    return {"figures": figures, "tables": tables}


def _data(data: DataBudget) -> dict:
    """The data budget's figures and tables."""
    margin = data.margin.to_value("percent")
    capacity = data.model.storage.capacity
    orbits = data.required_orbits
    figures = [
        _figure(
            "Downlink margin",
            (margin, "{:+.1f}"),
            "%",
            "closes" if margin >= 0 else "does not close",
            bad=margin < 0,
            headline=True,
        ),
        _figure(
            "Generated",
            _v(data.generated_per_day, "GB"),
            "GB/day",
            f"{_q(data.generated_per_orbit, 'GB')} GB per orbit",
        ),
        _figure(
            "Downlinked",
            _v(data.downlinked_per_day, "GB"),
            "GB/day",
            f"{_q(data.contact_per_day, 'min', '{:,.0f}')} min of contact a day",
        ),
    ]
    runs = [("item", ["1 orbit", _v(data.storage_required(1), "GB")])]
    if orbits is not None:
        needed = data.storage_required()
        figures.append(
            _figure(
                "Storage needed",
                _v(needed, "GB"),
                "GB",
                f"{orbits:g} orbits without downlink, of {_q(capacity, 'GB', '{:,.0f}')} GB",
                bad=needed > capacity,
                headline=True,
            )
        )
        runs.append(
            ("total", [f"{orbits:g} orbits, the requirement", _v(needed, "GB")])
        )
    else:
        figures.append(
            _figure(
                "Mass memory",
                _v(capacity, "GB", "{:,.0f}"),
                "GB",
                "usable capacity",
                headline=True,
            )
        )
    runs += [
        (
            "item",
            [
                "A full day",
                _v(data.storage_required(data.mission.orbits_per_day.value), "GB"),
            ],
        ),
        ("item", ["Mass memory, usable capacity", _v(capacity, "GB")]),
    ]
    return {
        "figures": figures,
        "tables": {
            "budget": _report(
                data.tabulated_data().data, data_report._HEADERS, {"value": "{:,.2f}"}
            ),
            "storage": _rows(["Duration without image downlink", "Storage [GB]"], runs),
        },
    }


def _slew_tables(frame: pd.DataFrame, targets: dict) -> dict:
    """A slew table with no slew to check against, and one against each target."""
    headers, formats = agility_report._HEADERS, agility_report._FORMATS
    tables = {
        name: _report(
            agility_report.tabulate(frame, slew.duration).data, headers, formats
        )
        for name, slew in targets.items()
    }
    tables[""] = _report(agility_report.tabulate(frame).data, headers, formats)
    return tables


def _axis_figures(budget: AgilityBudget, degraded: bool) -> list[dict]:
    """What the wheels give about the budget's axis, for one inertia case."""
    axis, shape = budget.axis.value, budget.case
    momentum = _q(budget.axis_momentum(degraded), "N m s", "{:,.2f}")
    torque = _q(budget.axis_torque(degraded), "N m", "{:,.3f}")
    return [
        _figure(
            "Inertia",
            _v(budget.inertia, "kg m2", "{:,.1f}"),
            "kg m²",
            f"from the mass budget at {shape.propellant.to_value('percent'):g} % propellant"
            if shape.is_envelope
            else "stated",
        ),
        _figure(
            "Max rate",
            _v(budget.max_rate(degraded), "deg/s", "{:,.3f}"),
            "deg/s",
            f"{momentum} N m s about {axis}",
        ),
        _figure(
            "Max acceleration",
            _v(budget.max_acceleration(degraded), "deg/s2", "{:,.4f}"),
            "deg/s²",
            f"{torque} N m about {axis}",
        ),
        _figure(
            "Crossover",
            _v(budget.crossover_angle(degraded), "deg", "{:,.1f}"),
            "deg",
            "torque limited below it",
        ),
    ]


class _Agility:
    """
    The agility budget for each axis and inertia case, with the mass read once
    for each case: the budget would read the mass budget again at each step.
    """

    def __init__(
        self,
        config: AgilityConfig,
        mission: Mission,
        mass: MassBudget | None,
        requirements: Requirements | None,
    ):
        self.config, self.mission = config, mission
        self.mass, self.requirements = mass, requirements
        agility = requirements.agility if requirements is not None else None
        self.slews = agility.slews if agility is not None else {}

    def budget(self, axis: Axis, case: str) -> AgilityBudget:
        """The budget about an axis, for an inertia case."""
        shape = self.config.for_case(case)
        mass = (
            self.mass.in_orbit_mass(propellant=shape.propellant.to_value("percent"))
            if shape.is_envelope and self.mass is not None
            else None
        )
        return AgilityBudget(
            self.config,
            self.mission,
            axis,
            case,
            self.mass,
            mass,
            requirements=self.requirements,
        )

    def variants(self) -> dict:
        """
        The selected case's figures and slew tables, about each axis, with every
        wheel and with one failed, by `axis|degraded`. An error in their place
        when quicksat cannot work out the case. The other cases are compared in
        the table of cases only.
        """
        variants = {}
        for axis in (Axis.ROLL, Axis.PITCH):
            targets = {n: s for n, s in self.slews.items() if s.axis == axis}
            for degraded in (False, True):
                key = f"{axis.value}|{int(degraded)}"
                # the page shows any failure, whatever its kind
                try:
                    budget = self.budget(axis, self.config.selected_case)
                    frame = budget.slew_table(degraded=degraded)
                    variants[key] = {
                        "figures": _axis_figures(budget, degraded),
                        "tables": _slew_tables(frame, targets),
                    }
                except Exception as error:
                    variants[key] = {"error": str(error)}
        return variants

    def checks(self, case: str) -> list[Check]:
        """A case's checks, about both axes. None when quicksat cannot work it out."""
        try:
            return [
                check
                for axis in (Axis.ROLL, Axis.PITCH)
                for check in self.budget(axis, case).checks()
            ]
        except Exception:  # the case's error shows on its own table
            return []

    def case_row(self, case: str) -> tuple[str, list]:
        """A case's line in the table of cases: its inertia, and its time for each slew."""
        shape = self.config.for_case(case)
        selected = case == self.config.selected_case
        cells: list = [
            case + (" (selected)" if selected else ""),
            "from the mass budget" if shape.is_envelope else "stated",
        ]
        for axis in (Axis.ROLL, Axis.PITCH):
            try:
                cells.append(_v(self.budget(axis, case).inertia, "kg m2", "{:,.1f}"))
            except Exception:  # the case's error shows on its own table
                cells.append("—")
        checks = {check.name: check for check in self.checks(case)}
        for name in self.slews:
            check = checks.get(name)
            cells += (
                [
                    _v(check.design, "s", "{:,.1f}"),
                    _v(check.margin, "percent", "{:+.1f}"),
                ]
                if check
                else ["—", "—"]
            )
        return ("selected" if selected else "item", cells)

    def results(self) -> dict:
        """The figures and tables of the agility budget, and the selected case's checks."""
        selected = self.config.selected_case
        checks = self.checks(selected)
        titles = ["Case", "Inertia", "Roll [kg m²]", "Pitch [kg m²]"]
        for name in self.slews:
            titles += [f"{name} [s]", f"{name} margin [%]"]
        return {
            "figures": [
                _figure(
                    check.name,
                    _v(check.design, "s", "{:,.1f}"),
                    "s",
                    f"of {_q(check.limit, 's', '{:g}')} s allowed, for the inertia "
                    f"case {selected}",
                    bad=not check.passes,
                    headline=True,
                )
                for check in checks
            ],
            "selected": selected,
            "cases": list(self.config.inertia_cases),
            "slews": [
                {
                    "name": name,
                    "axis": slew.axis.value,
                    "text": f"{slew.angle.to_value('deg'):g}° in {slew.duration.to_value('s'):g} s",
                }
                for name, slew in self.slews.items()
            ],
            "variants": self.variants(),
            "tables": {
                "cases": _rows(
                    titles, [self.case_row(case) for case in self.config.inertia_cases]
                )
            },
            "checks": checks,
        }


def _check_numbers(check: Check) -> dict:
    """
    A check's figures in full, for the export: the design, the limit and the
    spare in the design's unit, and the margin as a share, so 0.12 is 12 %.
    """
    unit = check.design.unit
    return {
        "design": _value(check.design.value),
        "limit": _value(check.limit.to_value(unit)),
        "spare": _value(check.spare.value),
        "margin": _value(check.margin.value),
        # GB, as the check's own text writes a data volume
        "unit": str(unit).replace("byte", "B"),
        "at_most": check.at_most,
    }


def _checks(budget: str, checks: list[Check], files: list[str]) -> list[dict]:
    """A budget's checks, as the page lists them."""
    if not checks:
        return []
    rows = tabulate_checks(checks).data.to_dict("records")
    return [
        {
            "budget": budget,
            **row,
            "passes": check.passes,
            "files": files,
            "numbers": _check_numbers(check),
        }
        for check, row in zip(checks, rows, strict=True)
    ]


class _Folder:
    """
    A folder of sizing files, worked out one budget at a time. The mission and
    the requirements are read once, and so is the mass budget, which delta-V and
    agility read too.
    """

    def __init__(self, folder: Path):
        self.path = {kind: folder / name for kind, name in NAMES.items()}
        self.notes: list[str] = []
        self.checks: list[dict] = []
        self.mission = self.read("mission", Mission.from_yaml_file)
        self.requirements = self.read("requirements", Requirements.from_yaml_file)
        self.mass: MassBudget | None = None

    def has(self, *kinds: str) -> bool:
        """Whether the folder holds the files of these kinds."""
        return all(self.path[kind].is_file() for kind in kinds)

    def read(self, kind: str, loader: Callable):
        """A shared file, read; None when it is missing or quicksat refuses it."""
        if not self.has(kind):
            return None
        try:
            return loader(self.path[kind])
        except Exception as error:  # the page shows any failure, whatever its kind
            self.notes.append(f"{NAMES[kind]}: {error}")
            return None

    def attempt(self, needs: tuple[str, ...], work: Callable[[], dict]) -> dict | None:
        """One budget's results, if its files are there, or its error."""
        if not self.has(*needs):
            return None
        if "mission" in needs and self.mission is None:
            return {"error": f"{NAMES['mission']} cannot be read."}
        try:
            return work()
        except Exception as error:  # the page shows any failure, whatever its kind
            return {"error": str(error)}

    def mass_budget(self) -> dict:
        self.mass = MassBudget.from_csv(self.path["equipment"], self.path["mass"])
        return _mass(self.mass)

    def delta_v_budget(self) -> dict:
        path = self.path
        delta_v = DeltaVBudget.from_csv(
            path["manoeuvres"], path["deltav"], path["mission"], mass_budget=self.mass
        )
        files = [NAMES["manoeuvres"], NAMES["equipment"]]
        self.checks += _checks("deltav", delta_v.checks(), files)
        return _delta_v(delta_v)

    def data_budget(self) -> dict:
        assert self.mission is not None
        model = DataFlowModel.from_yaml_file(self.path["data"])
        data = DataBudget(model, self.mission, self.requirements)
        for check in data.checks():
            files = [NAMES["data"]]
            if check.name == "storage":
                files.insert(0, NAMES["requirements"])
            self.checks += _checks("data", [check], files)
        return _data(data)

    def agility_budget(self) -> dict:
        assert self.mission is not None
        config = AgilityConfig.from_yaml_file(self.path["agility"])
        agility = _Agility(config, self.mission, self.mass, self.requirements)
        results = agility.results()
        files = [NAMES["requirements"], NAMES["agility"]]
        self.checks += _checks("agility", results.pop("checks"), files)
        return results


def budget_results(folder: str | Path) -> dict:
    """
    Work out every sizing budget whose files the folder holds.

    Parameters
    ----------
    folder : str | Path
        A folder of sizing files, with their usual names

    Returns
    -------
    results : dict
        `budgets`: `mass`, `deltav`, `data` and `agility`, each None when the
        folder lacks its files, `{"error": ...}` when quicksat cannot work it
        out, and otherwise its `figures` and `tables`. `overview`: the budgets'
        headline figures. `checks`: every check, as the page lists them, with
        its budget and the files it compares. `notes`: what stopped a shared
        file from being read.
    """
    files = _Folder(Path(folder))
    # in this order: delta-V and agility read the mass budget
    budgets = {
        "mass": files.attempt(("mass", "equipment"), files.mass_budget),
        "deltav": files.attempt(
            ("mission", "deltav", "manoeuvres"), files.delta_v_budget
        ),
        "data": files.attempt(("mission", "data"), files.data_budget),
        "agility": files.attempt(("mission", "agility"), files.agility_budget),
    }
    overview = [
        figure
        for budget in budgets.values()
        if budget is not None
        for figure in budget.get("figures", [])
        if figure["headline"]
    ]
    return {
        "budgets": budgets,
        "overview": overview,
        "checks": files.checks,
        "notes": files.notes,
    }
