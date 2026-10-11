# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
The power that the solar panels generate over a scenario run.

At each time of the run's grid, the power of a panel is

    flux × area × fill ratio × cell efficiency × loss factor × cos θ × light

- The flux is the sun's luminosity spread over a sphere through the satellite:
  L_sun / (4π d²), with d the distance from the satellite to the sun. It is
  about 1361 W/m² at 1 au, and changes by ±3.3% over a year.
- θ is the angle between the panel's normal and the sun. The cells face one
  way, so a panel generates nothing while the sun is behind it.
- The light is the fraction of the sun's disk that the Earth does not hide,
  from the run: 1 in sunlight, 0 in the umbra, and in between in the penumbra.

A panel from the 3D model takes its area and its normal from its part. If the
part sits under an articulation, such as a solar wing, the normal turns with the
articulation's angle at each step. A typed-in panel keeps its normal fixed in
body axes.

Light reflected by the Earth and the Earth's infrared are left out.

"""

from dataclasses import dataclass
from functools import cached_property

import numpy as np
import pandas as pd
from astropy import constants
from astropy.coordinates import CartesianRepresentation
from astropy.units import Quantity

from quicksat import Q_, u
from quicksat.orbit.attitude import axis_vector
from quicksat.power.config import PowerGeneration
from quicksat.power.shadowing import SHADED_LIMIT, lit_fractions
from quicksat.scenario.config import Scenario
from quicksat.scenario.run import ScenarioRun
from quicksat.scenario.spacecraft import (
    ModelGeometry,
    node_index,
    read_glb_json,
    read_model,
)
from quicksat.utils.intervals import TIME_GRID

# astropy.constants creates its constants at import, so pyright cannot see them
SOLAR_LUMINOSITY = constants.L_sun  # pyright: ignore[reportAttributeAccessIssue]
"""The sun's luminosity: astropy's default, the IAU 2015 nominal 3.828e26 W. It
gives 1361 W/m² at 1 au."""

FLAT_LIMIT = Q_(1, "deg")
"""The largest angle between one triangle of a panel's part and the part's mean
normal. A part with a triangle turned further is not a flat panel, and is
refused. A thin box modelled as a wing is one such part: name its cell face as a
part of its own."""

_NO_AREA = 1e-12
"""Below this share of a part's largest triangle, a triangle counts as having
no area, and its normal is not checked."""


@dataclass(frozen=True)
class PanelGeometry:
    """
    A panel's area and normal, in body axes, worked out from the file and model.

    Parameters
    ----------
    name : str
        The panel's name in the power generation file
    area : Quantity
        The panel's area, before the fill ratio
    normal : ndarray
        The direction the cells face in body axes, a unit vector of shape (3,).
        For a panel that turns, this is its direction where the model draws it,
        at an angle of zero.
    articulation : str or None
        The name of the articulation that turns the panel, or None if it is fixed
    node : int or None
        The index of the panel's part in the model's nodes. None for a typed-in
        panel.
    """

    name: str
    area: Quantity
    normal: np.ndarray
    articulation: str | None = None
    node: int | None = None


def flat_panel(triangles: np.ndarray) -> tuple[float, np.ndarray]:
    """
    The area and the normal of a flat set of triangles.

    Parameters
    ----------
    triangles : ndarray
        The corners of the triangles, shape (m, 3, 3), counter-clockwise seen
        from the side the normal points to

    Returns
    -------
    area : float
        The sum of the triangle areas, in the units of the corners squared
    normal : ndarray
        The area-weighted mean of the triangle normals, a unit vector

    Raises
    ------
    ValueError
        If the triangles have no area, or do not all face the same way within
        `FLAT_LIMIT`
    """
    doubled = np.cross(
        triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0]
    )
    lengths = np.linalg.norm(doubled, axis=1)
    if not len(lengths) or lengths.max() == 0:
        raise ValueError("has no area")
    mean = doubled.sum(axis=0)
    if np.linalg.norm(mean) <= 1e-9 * lengths.sum():
        raise ValueError(
            "faces no one way, like a closed box: it is not a flat panel. Name "
            "the face that holds the cells as a part of its own."
        )
    normal = mean / np.linalg.norm(mean)
    used = lengths > _NO_AREA * lengths.max()
    cosines = (doubled[used] / lengths[used, None]) @ normal
    widest = np.degrees(np.arccos(np.clip(cosines.min(), -1, 1)))
    if widest > FLAT_LIMIT.to_value(u.deg):
        raise ValueError(
            f"is not flat: a triangle turns {widest:.1f} deg from its mean "
            f"normal, more than {FLAT_LIMIT}. Name the face that holds the cells "
            "as a part of its own."
        )
    return float(lengths.sum() / 2), normal


def panel_geometry(
    generation: PowerGeneration, scenario: Scenario
) -> tuple[dict[str, PanelGeometry], ModelGeometry | None]:
    """
    The area and normal of each panel, with the scenario's 3D model.

    Parameters
    ----------
    generation : PowerGeneration
        The power generation file
    scenario : Scenario
        The scenario, for its 3D model and its articulations

    Returns
    -------
    panels : dict of str to PanelGeometry
        Each panel, by its name
    model : ModelGeometry or None
        The model's triangles, or None if the scenario has no model

    Raises
    ------
    ValueError
        If a panel names a part and the scenario has no model, or the model has
        no single node of that name, or the part has no triangles, is not flat,
        or sits under more than one articulation
    """
    spacecraft = scenario.spacecraft_model
    model = gltf = None
    turning: dict[str, int] = {}
    if spacecraft is not None:
        model = read_model(spacecraft.file)
        gltf = read_glb_json(spacecraft.file)
        turning = {
            name: node_index(gltf, articulation.part)
            for name, articulation in spacecraft.articulations.items()
        }

    panels, problems = {}, []
    for name, panel in generation.panels.items():
        if panel.part is None:
            assert panel.normal is not None and panel.area is not None
            panels[name] = PanelGeometry(
                name, panel.area.to(u.m**2), np.array(panel.normal)
            )
            continue
        if model is None or gltf is None:
            problems.append(
                f"panel '{name}' names the part '{panel.part}', but the scenario "
                "has no 3D model"
            )
            continue
        try:
            index = node_index(gltf, panel.part, "a panel")
        except ValueError as exc:
            problems.append(f"panel '{name}': {exc}")
            continue
        part = next((part for part in model.parts if part.node == index), None)
        if part is None:
            problems.append(
                f"panel '{name}': the part '{panel.part}' has no triangles in the model"
            )
            continue
        try:
            area, normal = flat_panel(part.triangles)
        except ValueError as exc:
            problems.append(f"panel '{name}': the part '{panel.part}' {exc}")
            continue
        above = {*part.ancestors, part.node}
        moving = [joint for joint, node in turning.items() if node in above]
        if len(moving) > 1:
            problems.append(
                f"panel '{name}': the part '{panel.part}' sits under "
                f"{len(moving)} articulations, {moving}, and a panel can turn with "
                "one only"
            )
            continue
        panels[name] = PanelGeometry(
            name, Q_(area, "m2"), normal, moving[0] if moving else None, part.node
        )
    if problems:
        raise ValueError("\n".join(problems))
    return panels, model


def panel_notes(generation: PowerGeneration, has_model: bool) -> list[str]:
    """
    Notes on the panels for the reader, such as which are typed in.

    Typed-in panels have no triangles, so the self-shadowing cannot cover them.
    The notes say so whenever there is one. They are text for the output, not
    Python warnings.

    Parameters
    ----------
    generation : PowerGeneration
        The power generation file
    has_model : bool
        Whether the scenario has a 3D model

    Returns
    -------
    notes : list of str
        One sentence or two for each note. Empty when every panel comes from the
        model.
    """
    typed = [name for name, panel in generation.panels.items() if panel.part is None]
    notes = []
    if typed and len(typed) == len(generation.panels):
        if has_model:
            notes.append(
                "All panels are typed in, not taken from the 3D model. They stay "
                "fixed in body axes, and the model does not shade them."
            )
        else:
            notes.append(
                "The scenario has no 3D model, so all panels are typed in. They "
                "stay fixed in body axes, and nothing shades them."
            )
    elif typed:
        notes.append(
            f"Some panels are typed in, not taken from the 3D model: "
            f"{', '.join(typed)}. They stay fixed in body axes, are never shaded, "
            "and shade nothing. The others come from the model."
        )
    if generation.shading and len(typed) == len(generation.panels):
        notes.append(
            "Self-shadowing is on, but no panel comes from the 3D model, so "
            "nothing is shaded."
        )
    return notes


def turned_normals(
    normal: np.ndarray, axis: np.ndarray, angles: Quantity
) -> np.ndarray:
    """
    A normal turned about an axis, by each of a series of angles.

    Parameters
    ----------
    normal, axis : ndarray
        Unit vectors, shape (3,). The turn is right-handed about the axis.
    angles : Quantity
        The angles, shape (n,)

    Returns
    -------
    normals : ndarray
        Unit vectors, shape (n, 3)
    """
    angle = np.asarray(angles.to_value(u.rad))[:, None]
    # Rodrigues' rotation formula
    return (
        normal * np.cos(angle)
        + np.cross(axis, normal) * np.sin(angle)
        + axis * (axis @ normal) * (1 - np.cos(angle))
    )


def solar_flux(run: ScenarioRun) -> Quantity:
    """
    The sun's flux at the satellite, on the run's grid.

    Parameters
    ----------
    run : ScenarioRun
        The run

    Returns
    -------
    flux : Quantity
        L_sun / (4π d²), with d the distance from the satellite to the sun, in
        W/m², one for each time of the grid
    """
    cartesian = run.state.cartesian
    assert isinstance(cartesian, CartesianRepresentation)
    distance = Q_(
        np.linalg.norm(
            run.sun.xyz.to_value(u.km).T - cartesian.xyz.to_value(u.km).T, axis=1
        ),
        "km",
    )
    return (SOLAR_LUMINOSITY / (4 * np.pi * distance**2)).to(u.W / u.m**2)


def _energy_until(seconds: np.ndarray, power: np.ndarray, at: np.ndarray):
    """
    The energy from the start of the grid up to each given time, in joules.

    The power is taken to change linearly between the times of the grid, so the
    energy is exact for it, also between those times.

    Parameters
    ----------
    seconds : ndarray
        The times of the grid, in seconds from its start, rising
    power : ndarray
        The power at each time of the grid, in watts
    at : ndarray
        The times to give the energy at, in seconds, inside the grid

    Returns
    -------
    energy : ndarray
        In joules, one for each time in `at`
    """
    steps = np.diff(seconds)
    gained = np.concatenate([[0.0], np.cumsum((power[1:] + power[:-1]) / 2 * steps)])
    index = np.clip(np.searchsorted(seconds, at, side="right") - 1, 0, len(steps) - 1)
    into = at - seconds[index]
    slope = (power[index + 1] - power[index]) / steps[index]
    return gained[index] + power[index] * into + slope * into**2 / 2


@dataclass(frozen=True)
class GenerationRun:
    """
    The power that the panels generate over a scenario run.

    Parameters
    ----------
    generation : PowerGeneration
        The power generation file
    run : ScenarioRun
        The scenario run
    panels : dict of str to PanelGeometry
        Each panel's area and normal
    flux : Quantity
        The sun's flux at the satellite, on the grid, in W/m²
    cosines : dict of str to ndarray
        For each panel, the cosine of the sun's angle to its normal, on the grid.
        Negative while the sun is behind the panel.
    lit : dict of str to ndarray
        For each panel, the share of its area that no part of the model shades,
        on the grid, from 0 to 1. All 1 without the self-shadowing, and for a
        typed-in panel.
    unshaded : dict of str to Quantity
        For each panel, the power it would generate with no self-shadowing, on
        the grid, in W
    power : dict of str to Quantity
        For each panel, the power it generates, on the grid, in W: the unshaded
        power times the lit fraction
    notes : list of str
        Notes for the reader, from `panel_notes`
    """

    generation: PowerGeneration
    run: ScenarioRun
    panels: dict[str, PanelGeometry]
    flux: Quantity
    cosines: dict[str, np.ndarray]
    lit: dict[str, np.ndarray]
    unshaded: dict[str, Quantity]
    power: dict[str, Quantity]
    notes: list[str]

    @property
    def total(self) -> Quantity:
        """
        The power of all the panels together, on the grid.

        Returns
        -------
        total : Quantity
            In W
        """
        return sum(self.power.values(), Q_(np.zeros(len(self.run.times)), "W"))

    @cached_property
    def orbits(self) -> list[tuple[float, float]]:
        """
        The whole orbits in the run, counted from its start, one period each.

        A cut orbit at the end of the run is left out. So is every orbit of a run
        shorter than one period.

        Returns
        -------
        orbits : list of tuple of float
            The start and the end of each orbit, in seconds from the run's start
        """
        period = float(self.run.orbit.period.to(u.s).value)
        length = float((self.run.times[-1] - self.run.times[0]).to_value(u.s))
        # the end of the run sits on the 1 ms grid, so it may fall short of a
        # whole number of periods by up to 1 ms
        count = int((length + float(TIME_GRID.to(u.s).value)) // period)
        return [
            (number * period, min((number + 1) * period, length))
            for number in range(count)
        ]

    def _seconds(self) -> np.ndarray:
        """The grid, in seconds from the run's start."""
        return np.asarray((self.run.times - self.run.times[0]).to_value(u.s))

    def _pieces(self, intervals) -> list[tuple[float, float]]:
        """The pieces of an interval of the run, in seconds from its start."""
        start = self.run.times[0]
        return [
            (
                float((piece.lower - start).to_value(u.s)),
                float((piece.upper - start).to_value(u.s)),
            )
            for piece in intervals
            if not piece.empty
        ]

    def energy(self, power: Quantity) -> list[Quantity]:
        """
        The energy generated over each whole orbit, from a power on the grid.

        Parameters
        ----------
        power : Quantity
            A power on the run's grid, such as `total` or one panel's

        Returns
        -------
        energy : list of Quantity
            In W h, one for each of `orbits`
        """
        bounds = np.array(self.orbits).reshape(-1)
        joules = _energy_until(self._seconds(), np.asarray(power.to_value(u.W)), bounds)
        return [
            Q_(end - start, "J").to(u.W * u.h) for start, end in joules.reshape(-1, 2)
        ]

    @cached_property
    def panel_table(self) -> pd.DataFrame:
        """
        The panels as the file and the model give them, one row each.

        Returns
        -------
        table : pd.DataFrame
            The columns are the panel's name, its part in the model (blank for a
            typed-in panel), its area in m², its fill ratio in percent, its normal
            in body axes where the model draws it, and the articulation it turns
            with (blank for a fixed panel)
        """
        rows = []
        for name, panel in self.panels.items():
            entry = self.generation.panels[name]
            rows.append(
                {
                    "panel": name,
                    "part": entry.part or "",
                    "area [m2]": panel.area.to_value(u.m**2),
                    "fill ratio [%]": entry.fill_ratio.to_value(u.percent),
                    "normal": "["
                    + ", ".join(f"{round(c, 3) + 0.0:+.3f}" for c in panel.normal)
                    + "]",
                    "turns with": panel.articulation or "",
                }
            )
        return pd.DataFrame(rows)

    @cached_property
    def orbit_table(self) -> pd.DataFrame:
        """
        The power of all the panels together, one row for each whole orbit.

        The sunlit mean is the energy generated outside the eclipse, over the
        time outside it. The penumbra counts as eclipse, as in the scenario, but
        what the panels generate in it counts in the orbit's energy.

        Returns
        -------
        table : pd.DataFrame
            The columns are the orbit number, its start as UTC text, the time in
            eclipse in minutes, the mean power over the whole orbit and over its
            sunlit time in W, and the energy generated in W h. Empty for a run
            shorter than one orbit.
        """
        seconds = self._seconds()
        total = np.asarray(self.total.to_value(u.W))
        eclipses = self._pieces(self.run.eclipses)
        sunlit = self._pieces(self.run.sunlit)
        rows = []
        for number, (start, end) in enumerate(self.orbits, start=1):
            clipped = [
                (max(lower, start), min(upper, end))
                for lower, upper in sunlit
                if upper > start and lower < end
            ]
            sunlit_time = sum(upper - lower for lower, upper in clipped)
            eclipse_time = sum(
                max(0.0, min(upper, end) - max(lower, start))
                for lower, upper in eclipses
            )
            ends = np.array([start, end, *[t for piece in clipped for t in piece]])
            joules = _energy_until(seconds, total, ends)
            in_sun = float(np.sum(joules[3::2] - joules[2::2]))
            whole = float(joules[1] - joules[0])
            rows.append(
                {
                    "orbit": number,
                    "start [UTC]": (self.run.times[0] + Q_(start, "s")).utc.isot,
                    "eclipse [min]": eclipse_time / 60,
                    "mean power [W]": whole / (end - start),
                    "sunlit mean power [W]": (
                        in_sun / sunlit_time if sunlit_time > 0 else np.nan
                    ),
                    "energy [Wh]": whole / 3600,
                }
            )
        return pd.DataFrame(rows)

    @cached_property
    def panel_energy_table(self) -> pd.DataFrame:
        """
        The energy each panel generates, one row for each whole orbit.

        Returns
        -------
        table : pd.DataFrame
            The orbit number, then one column for each panel and one for the
            total, in W h. Empty for a run shorter than one orbit.
        """
        columns = {
            f"{name} [Wh]": [e.to_value(u.W * u.h) for e in self.energy(power)]
            for name, power in self.power.items()
        }
        columns["total [Wh]"] = [e.to_value(u.W * u.h) for e in self.energy(self.total)]
        return pd.DataFrame({"orbit": list(range(1, len(self.orbits) + 1)), **columns})

    @cached_property
    def shading_table(self) -> pd.DataFrame:
        """
        How much the self-shadowing costs each panel from the model, over the run.

        A panel counts as shaded while more than `SHADED_LIMIT` of it is shaded,
        so that a shadow that only touches a corner does not count.

        Returns
        -------
        table : pd.DataFrame
            One row for each panel from the model: its lowest lit fraction while
            it faces the sun outside the umbra, the time it is shaded in minutes,
            the energy the shading costs in W h, and that energy as a share of
            what the panel would generate unshaded, in percent. Empty without the
            self-shadowing.
        """
        if not self.generation.shading:
            return pd.DataFrame()
        seconds = self._seconds()
        steps = np.diff(seconds)
        rows = []
        for name, panel in self.panels.items():
            if panel.node is None:
                continue
            lit = self.lit[name]
            unshaded = np.asarray(self.unshaded[name].to_value(u.W))
            power = np.asarray(self.power[name].to_value(u.W))
            ends = np.array([seconds[0], seconds[-1]])
            full = np.diff(_energy_until(seconds, unshaded, ends))[0]
            lost = full - np.diff(_energy_until(seconds, power, ends))[0]
            rows.append(
                {
                    "panel": name,
                    "lowest lit fraction": float(lit.min()),
                    "shaded [min]": float(
                        steps[lit[:-1] < 1 - SHADED_LIMIT].sum() / 60
                    ),
                    "energy lost [Wh]": lost / 3600,
                    "energy lost [%]": 100 * lost / full if full > 0 else 0.0,
                }
            )
        return pd.DataFrame(rows)


def run_generation(generation: PowerGeneration, run: ScenarioRun) -> GenerationRun:
    """
    Work out the power that each panel generates over a scenario run.

    Parameters
    ----------
    generation : PowerGeneration
        The power generation file
    run : ScenarioRun
        The scenario run, with its 3D model if any panel names a part

    Returns
    -------
    generation_run : GenerationRun
        The power of each panel on the run's grid, and the notes

    Raises
    ------
    ValueError
        If a panel's part does not suit, as `panel_geometry` checks
    """
    panels, model = panel_geometry(generation, run.scenario)
    spacecraft = run.scenario.spacecraft_model
    flux = solar_flux(run)
    suns = run.sun_body
    efficiency = float(generation.cell_efficiency.to_value("")) * float(
        generation.loss_factor.to_value("")
    )

    cosines = {}
    for name, panel in panels.items():
        if panel.articulation is None:
            cosines[name] = suns @ panel.normal
        else:
            assert spacecraft is not None
            axis = axis_vector(spacecraft.articulations[panel.articulation].axis)
            normals = turned_normals(
                panel.normal, axis, run.articulations[panel.articulation]
            )
            cosines[name] = np.einsum("ni,ni->n", normals, suns)

    lit = {name: np.ones(len(suns)) for name in panels}
    from_model = [
        (name, panel.node, panel.normal)
        for name, panel in panels.items()
        if panel.node is not None
    ]
    if generation.self_shadowing and generation.shading and from_model:
        assert model is not None and spacecraft is not None
        lit |= lit_fractions(
            model,
            spacecraft,
            from_model,
            generation.self_shadowing.points,
            suns,
            cosines,
            run.light,
            run.articulations,
        )

    unshaded, power = {}, {}
    for name, panel in panels.items():
        fill = float(generation.panels[name].fill_ratio.to_value(""))
        unshaded[name] = (
            flux
            * panel.area
            * (fill * efficiency)
            * np.clip(cosines[name], 0, None)
            * run.light
        ).to(u.W)
        power[name] = unshaded[name] * lit[name]

    return GenerationRun(
        generation,
        run,
        panels,
        flux,
        cosines,
        lit,
        unshaded,
        power,
        panel_notes(generation, spacecraft is not None),
    )
