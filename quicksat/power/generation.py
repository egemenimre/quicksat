# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
The power that the solar panels generate over a scenario run.

A panel's power is flux × area × fill ratio × cell efficiency × loss factor × cos θ ×
light, at each step. A panel under an articulation turns with it. The thermal surfaces
share the geometry, through `flat_geometry` and `item_cosines`.
`docs/power/power_generation_ref.ipynb` explains the model and its check against Orekit.

"""

from collections.abc import Mapping
from dataclasses import dataclass
from functools import cached_property

import numpy as np
import pandas as pd
from astropy import constants
from astropy.coordinates import CartesianRepresentation
from astropy.units import Quantity

from quicksat import Q_, u
from quicksat.orbit.attitude import axis_vector
from quicksat.power.config import FlatItem, PowerSystem
from quicksat.power.orbits import (
    energy_until,
    interval_pieces,
    overlap,
    run_seconds,
    whole_orbits,
)
from quicksat.power.shadowing import SHADED_LIMIT, lit_fractions
from quicksat.scenario.config import Scenario
from quicksat.scenario.run import ScenarioRun
from quicksat.scenario.spacecraft import (
    ModelGeometry,
    node_index,
    read_glb_json,
    read_model,
)

# astropy.constants creates its constants at import, so pyright cannot see them
SOLAR_LUMINOSITY = constants.L_sun  # pyright: ignore[reportAttributeAccessIssue]
"""The sun's luminosity: astropy's default, the IAU 2015 nominal, 1361 W/m² at 1 au."""

FLAT_LIMIT = Q_(1, "deg")
"""The largest angle between a part's triangle and its mean normal before the part is
refused as not flat."""

_NO_AREA = 1e-12
"""The share of a part's largest triangle below which a triangle has no area, and its
normal is not checked."""


@dataclass(frozen=True)
class FlatGeometry:
    """
    A flat item's area and normal in body axes, from its file and the model: a solar
    panel or a thermal surface.

    Parameters
    ----------
    name : str
        The item's name
    area : Quantity
        Its area, before a panel's fill ratio
    normal : ndarray
        The unit direction it faces, at an articulation angle of zero, shape (3,)
    articulation : str or None
        The articulation that turns it, or None
    node : int or None
        Its part's node index, or None for a typed-in item
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
        The corners, counter-clockwise from the normal's side, shape (m, 3, 3)

    Returns
    -------
    area : float
        The triangles' total area, in the corners' units squared
    normal : ndarray
        The area-weighted mean normal, of unit length

    Raises
    ------
    ValueError
        If the triangles have no area, or do not face one way within `FLAT_LIMIT`
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


def flat_geometry(
    items: Mapping[str, FlatItem], scenario: Scenario
) -> tuple[dict[str, FlatGeometry], ModelGeometry | None]:
    """
    The area and normal of each flat item, such as a panel, with the scenario's 3D
    model.

    Parameters
    ----------
    items : mapping of str to FlatItem
        The items, by name
    scenario : Scenario
        The scenario, for its model and articulations

    Returns
    -------
    items : dict of str to FlatGeometry
        Each item, by name
    model : ModelGeometry or None
        The model's triangles, or None

    Raises
    ------
    ValueError
        If a part is missing, empty, not flat, or under two articulations, or there is
        no model
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

    flats, problems = {}, []
    for name, item in items.items():
        kind = item.kind
        if item.part is None:
            assert item.normal is not None and item.area is not None
            flats[name] = FlatGeometry(
                name, item.area.to(u.m**2), np.array(item.normal)
            )
            continue
        if model is None or gltf is None:
            problems.append(
                f"{kind} '{name}' names the part '{item.part}', but the scenario "
                "has no 3D model"
            )
            continue
        try:
            index = node_index(gltf, item.part, f"a {kind}")
        except ValueError as exc:
            problems.append(f"{kind} '{name}': {exc}")
            continue
        part = next((part for part in model.parts if part.node == index), None)
        if part is None:
            problems.append(
                f"{kind} '{name}': the part '{item.part}' has no triangles in the model"
            )
            continue
        try:
            area, normal = flat_panel(part.triangles)
        except ValueError as exc:
            problems.append(f"{kind} '{name}': the part '{item.part}' {exc}")
            continue
        above = {*part.ancestors, part.node}
        moving = [joint for joint, node in turning.items() if node in above]
        if len(moving) > 1:
            problems.append(
                f"{kind} '{name}': the part '{item.part}' sits under "
                f"{len(moving)} articulations, {moving}, and a {kind} can turn "
                "with one only"
            )
            continue
        flats[name] = FlatGeometry(
            name, Q_(area, "m2"), normal, moving[0] if moving else None, part.node
        )
    if problems:
        raise ValueError("\n".join(problems))
    return flats, model


def panel_notes(power_system: PowerSystem, has_model: bool) -> list[str]:
    """
    Notes on the panels for the reader, such as which are typed in and so never shaded.

    Parameters
    ----------
    power_system : PowerSystem
        The power system file
    has_model : bool
        Whether the scenario has a 3D model

    Returns
    -------
    notes : list of str
        The notes, empty when every panel comes from the model
    """
    typed = [name for name, panel in power_system.panels.items() if panel.part is None]
    notes = []
    if typed and len(typed) == len(power_system.panels):
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
    if power_system.shading and len(typed) == len(power_system.panels):
        notes.append(
            "Self-shadowing is on, but no panel comes from the 3D model, so "
            "nothing is shaded."
        )
    return notes


def turned_normals(
    normal: np.ndarray, axis: np.ndarray, angles: Quantity
) -> np.ndarray:
    """
    A normal turned right-handed about an axis, by each of a series of angles.

    Parameters
    ----------
    normal, axis : ndarray
        Unit vectors, shape (3,)
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


def item_cosines(
    items: dict[str, FlatGeometry], run: ScenarioRun, directions: np.ndarray
) -> dict[str, np.ndarray]:
    """
    The cosine between each item's normal, turned by any articulation, and a direction,
    on the run's grid.

    Parameters
    ----------
    items : dict of str to FlatGeometry
        The items
    run : ScenarioRun
        The run
    directions : ndarray
        Unit vectors in body axes on the grid, shape (n, 3), such as `run.sun_body`

    Returns
    -------
    cosines : dict of str to ndarray
        Each item's cosine, by name, negative while the direction is behind it
    """
    spacecraft = run.scenario.spacecraft_model
    cosines = {}
    for name, item in items.items():
        if item.articulation is None:
            cosines[name] = directions @ item.normal
        else:
            assert spacecraft is not None
            axis = axis_vector(spacecraft.articulations[item.articulation].axis)
            normals = turned_normals(
                item.normal, axis, run.articulations[item.articulation]
            )
            cosines[name] = np.einsum("ni,ni->n", normals, directions)
    return cosines


def shaded_fractions(
    items: dict[str, FlatGeometry],
    model: ModelGeometry | None,
    power_system: PowerSystem,
    run: ScenarioRun,
    cosines: dict[str, np.ndarray],
) -> dict[str, np.ndarray]:
    """
    The share of each item that the rest of the model leaves in the sun, on the run's
    grid.

    Parameters
    ----------
    items : dict of str to FlatGeometry
        The items
    model : ModelGeometry or None
        The model's triangles
    power_system : PowerSystem
        The power system file, for the self-shadowing
    run : ScenarioRun
        The run
    cosines : dict of str to ndarray
        Each item's cosine to the sun

    Returns
    -------
    lit : dict of str to ndarray
        Each item's lit fraction, by name, all 1 without the self-shadowing or for a
        typed-in item
    """
    suns = run.sun_body
    lit = {name: np.ones(len(suns)) for name in items}
    from_model = [
        (name, item.node, item.normal)
        for name, item in items.items()
        if item.node is not None
    ]
    spacecraft = run.scenario.spacecraft_model
    if power_system.self_shadowing and power_system.shading and from_model:
        assert model is not None and spacecraft is not None
        lit |= lit_fractions(
            model,
            spacecraft,
            from_model,
            power_system.self_shadowing.points,
            suns,
            cosines,
            run.light,
            run.articulations,
        )
    return lit


def solar_flux(run: ScenarioRun) -> Quantity:
    """
    The sun's flux at the satellite, L_sun / (4π d²), on the run's grid.

    Parameters
    ----------
    run : ScenarioRun
        The run

    Returns
    -------
    flux : Quantity
        In W/m²
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


@dataclass(frozen=True)
class GenerationRun:
    """
    The power that the panels generate over a scenario run, on its grid.

    Parameters
    ----------
    power_system : PowerSystem
        The power system file
    run : ScenarioRun
        The scenario run
    panels : dict of str to FlatGeometry
        Each panel's area and normal
    flux : Quantity
        The sun's flux at the satellite, in W/m²
    cosines : dict of str to ndarray
        Each panel's cosine to the sun
    lit : dict of str to ndarray
        Each panel's lit fraction
    unshaded : dict of str to Quantity
        Each panel's power with no self-shadowing, in W
    power : dict of str to Quantity
        Each panel's power, the unshaded times the lit fraction, in W
    notes : list of str
        The notes, from `panel_notes`
    """

    power_system: PowerSystem
    run: ScenarioRun
    panels: dict[str, FlatGeometry]
    flux: Quantity
    cosines: dict[str, np.ndarray]
    lit: dict[str, np.ndarray]
    unshaded: dict[str, Quantity]
    power: dict[str, Quantity]
    notes: list[str]

    @property
    def total(self) -> Quantity:
        """The power of all the panels together on the grid, in W."""
        return sum(self.power.values(), Q_(np.zeros(len(self.run.times)), "W"))

    @cached_property
    def orbits(self) -> list[tuple[float, float]]:
        """The run's whole orbits, each as a start and an end in s."""
        return whole_orbits(self.run)

    def energy(self, power: Quantity) -> list[Quantity]:
        """
        The energy generated over each whole orbit, from a power on the grid.

        Parameters
        ----------
        power : Quantity
            A power on the run's grid, such as `total`

        Returns
        -------
        energy : list of Quantity
            In W h, one per orbit
        """
        bounds = np.array(self.orbits).reshape(-1)
        joules = energy_until(
            run_seconds(self.run), np.asarray(power.to_value(u.W)), bounds
        )
        return [
            Q_(end - start, "J").to(u.W * u.h) for start, end in joules.reshape(-1, 2)
        ]

    @cached_property
    def panel_table(self) -> pd.DataFrame:
        """
        The panels as the file and the model give them: the name, part, area, fill
        ratio, normal and articulation.
        """
        rows = []
        for name, panel in self.panels.items():
            entry = self.power_system.panels[name]
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
        All the panels' power in each whole orbit: the eclipse time, the mean over the
        orbit and over its sunlit time, and the energy.
        """
        seconds = run_seconds(self.run)
        total = np.asarray(self.total.to_value(u.W))
        eclipses = interval_pieces(self.run, self.run.eclipses)
        sunlit = interval_pieces(self.run, self.run.sunlit)
        rows = []
        for number, (start, end) in enumerate(self.orbits, start=1):
            clipped = [
                (max(lower, start), min(upper, end))
                for lower, upper in sunlit
                if upper > start and lower < end
            ]
            sunlit_time = sum(upper - lower for lower, upper in clipped)
            eclipse_time = overlap(eclipses, start, end)
            ends = np.array([start, end, *[t for piece in clipped for t in piece]])
            joules = energy_until(seconds, total, ends)
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
        The energy each panel generates in each whole orbit, with the total, in W h.
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
        What the self-shadowing costs each panel from the model: its lowest lit
        fraction, its time shaded past `SHADED_LIMIT`, and the energy lost.
        """
        if not self.power_system.shading:
            return pd.DataFrame()
        seconds = run_seconds(self.run)
        steps = np.diff(seconds)
        rows = []
        for name, panel in self.panels.items():
            if panel.node is None:
                continue
            lit = self.lit[name]
            unshaded = np.asarray(self.unshaded[name].to_value(u.W))
            power = np.asarray(self.power[name].to_value(u.W))
            ends = np.array([seconds[0], seconds[-1]])
            full = np.diff(energy_until(seconds, unshaded, ends))[0]
            lost = full - np.diff(energy_until(seconds, power, ends))[0]
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


def run_generation(power_system: PowerSystem, run: ScenarioRun) -> GenerationRun:
    """
    Work out the power that each panel generates over a scenario run.

    Parameters
    ----------
    power_system : PowerSystem
        The power system file
    run : ScenarioRun
        The scenario run

    Returns
    -------
    generation_run : GenerationRun
        Each panel's power on the grid, and the notes

    Raises
    ------
    ValueError
        If a panel's part does not suit, as `flat_geometry` checks
    """
    panels, model = flat_geometry(power_system.panels, run.scenario)
    spacecraft = run.scenario.spacecraft_model
    flux = solar_flux(run)
    efficiency = float(
        power_system.cell_efficiency.to(u.dimensionless_unscaled).value
    ) * float(power_system.loss_factor.to(u.dimensionless_unscaled).value)
    cosines = item_cosines(panels, run, run.sun_body)
    lit = shaded_fractions(panels, model, power_system, run, cosines)

    unshaded, power = {}, {}
    for name, panel in panels.items():
        fill = float(
            power_system.panels[name].fill_ratio.to(u.dimensionless_unscaled).value
        )
        unshaded[name] = Q_(
            flux
            * panel.area
            * (fill * efficiency)
            * np.clip(cosines[name], 0, None)
            * run.light
        ).to(u.W)
        power[name] = unshaded[name] * lit[name]

    return GenerationRun(
        power_system,
        run,
        panels,
        flux,
        cosines,
        lit,
        unshaded,
        power,
        panel_notes(power_system, spacecraft is not None),
    )
