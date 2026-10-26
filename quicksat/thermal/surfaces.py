# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
The heat that the payload's surfaces absorb from the sun, the albedo and the Earth's
infrared, and emit at their design temperatures.

A surface's area, sun angles and shading come from `quicksat.power.generation`, as a
panel's do. `docs/explanations/payload_thermal_model.md`, under "The heat a surface
absorbs", gives the formulas.

"""

from dataclasses import dataclass

import numpy as np
from astropy import constants
from astropy.coordinates import CartesianRepresentation
from astropy.units import Quantity

from quicksat import Q_, R_EARTH, u
from quicksat.power.config import PowerSystem
from quicksat.power.generation import (
    FlatGeometry,
    flat_geometry,
    item_cosines,
    shaded_fractions,
    solar_flux,
)
from quicksat.scenario.run import ScenarioRun
from quicksat.thermal.config import PayloadThermal

# astropy.constants creates its constants at import, so pyright cannot see them
STEFAN_BOLTZMANN = constants.sigma_sb  # pyright: ignore[reportAttributeAccessIssue]
"""The Stefan-Boltzmann constant, σ: astropy's CODATA value, 5.670e-8 W/(m² K⁴)."""

ABSORBED = ("sun", "albedo", "infrared")
"""The heat a surface absorbs, by its source."""


def earth_angular_radius(run: ScenarioRun) -> Quantity:
    """
    The Earth's angular radius seen from the satellite, on the run's grid.

    Parameters
    ----------
    run : ScenarioRun
        The run

    Returns
    -------
    radius : Quantity
        arcsin(R_EARTH / r), in degrees
    """
    cartesian = run.state.cartesian
    assert isinstance(cartesian, CartesianRepresentation)
    distance = Q_(np.linalg.norm(cartesian.xyz.to_value(u.km), axis=0), "km")
    ratio = np.clip((R_EARTH / distance).to_value(u.one), 0, 1)
    return Q_(np.arcsin(ratio), "rad").to(u.deg)


def view_factor(cosines: np.ndarray, angular_radius: Quantity) -> np.ndarray:
    """
    The view factor of a flat plate to a sphere, such as a surface to the Earth, in
    closed form.

    The full, partial and no-view cases follow J. R. Howell's catalog of radiation
    configuration factors, in ρ rather than H = 1 / sin ρ.
    `docs/power/payload_thermal_ref.ipynb`, under "The view factor", gives them and
    checks them.

    Parameters
    ----------
    cosines : ndarray
        cos λ, between the normal and the sphere's centre, at each time
    angular_radius : Quantity
        ρ, the sphere's angular radius, above 0 and below 90 degrees

    Returns
    -------
    factor : ndarray
        From 0 to sin² ρ
    """
    cos_l = np.clip(np.asarray(cosines, dtype=float), -1, 1)
    rho = np.broadcast_to(np.asarray(angular_radius.to_value(u.rad)), cos_l.shape)
    sin_r, cos_r = np.sin(rho), np.cos(rho)
    sin_l = np.sqrt(1 - cos_l**2)
    full = cos_l >= sin_r
    none = cos_l <= -sin_r
    partial = ~(full | none)
    factor = np.where(full, cos_l * sin_r**2, 0.0)
    if partial.any():
        c, s = cos_l[partial], sin_l[partial]
        sr, cr = sin_r[partial], cos_r[partial]
        cut = np.arccos(np.clip(-cr / sr * c / s, -1, 1))
        factor[partial] = (
            0.5
            - np.arcsin(np.clip(cr / s, -1, 1)) / np.pi
            + (sr**2 * c * cut - cr * np.sqrt(np.clip(sr**2 - c**2, 0, None))) / np.pi
        )
    return np.clip(factor, 0, None)


@dataclass(frozen=True)
class SurfacePowers:
    """
    The heat each surface absorbs and emits over a run, which the editor's server keeps
    between requests.

    Parameters
    ----------
    run : ScenarioRun
        The run
    surfaces : dict of str to FlatGeometry
        Each surface's area and normal
    sun_cosines : dict of str to ndarray
        Each surface's cosine to the sun on the grid
    lit : dict of str to ndarray
        Each surface's lit share on the grid
    view_factors : dict of str to ndarray
        Each surface's view factor to the Earth on the grid
    absorbed : dict of str to dict of str to ndarray
        The heat absorbed on the grid in W, by source, then by surface
    emitted : dict of str to float
        Each surface's emission in W, negative
    notes : list of str
        Notes for the reader
    """

    run: ScenarioRun
    surfaces: dict[str, FlatGeometry]
    sun_cosines: dict[str, np.ndarray]
    lit: dict[str, np.ndarray]
    view_factors: dict[str, np.ndarray]
    absorbed: dict[str, dict[str, np.ndarray]]
    emitted: dict[str, float]
    notes: list[str]


def surface_powers(
    thermal: PayloadThermal, power_system: PowerSystem, run: ScenarioRun
) -> SurfacePowers:
    """
    Work out the heat each surface absorbs and emits over a run.

    Parameters
    ----------
    thermal : PayloadThermal
        The thermal file
    power_system : PowerSystem
        The power system file, for the self-shadowing
    run : ScenarioRun
        The run

    Returns
    -------
    powers : SurfacePowers
        The heat absorbed and emitted

    Raises
    ------
    ValueError
        If a surface's part does not suit, as `flat_geometry` checks
    """
    surfaces, model = flat_geometry(thermal.surfaces, run.scenario)
    cosines = item_cosines(surfaces, run, run.sun_body)
    lit = shaded_fractions(surfaces, model, power_system, run, cosines)
    nadirs = item_cosines(surfaces, run, run.nadir_body)
    radius = earth_angular_radius(run)
    flux = np.asarray(solar_flux(run).to_value(u.W / u.m**2))
    albedo = float(thermal.earth.albedo.to_value(u.one))
    infrared = float(thermal.earth.infrared.to_value(u.W / u.m**2))
    zenith = np.clip(run.sun_zenith_cosine, 0, None)

    factors = {}
    absorbed: dict[str, dict[str, np.ndarray]] = {source: {} for source in ABSORBED}
    emitted = {}
    for name, geometry in surfaces.items():
        entry = thermal.surfaces[name]
        area = float(geometry.area.to(u.m**2).value)
        alpha = float(entry.absorptance.to_value(u.one))
        epsilon = float(entry.emissivity.to_value(u.one))
        factors[name] = view_factor(nadirs[name], radius)
        absorbed["sun"][name] = (
            flux
            * alpha
            * area
            * np.clip(cosines[name], 0, None)
            * run.light
            * lit[name]
        )
        absorbed["albedo"][name] = flux * albedo * factors[name] * alpha * area * zenith
        absorbed["infrared"][name] = infrared * factors[name] * epsilon * area
        emitted[name] = -float(
            (
                epsilon * STEFAN_BOLTZMANN * geometry.area * entry.temperature**4
            ).to_value(u.W)
        )
    return SurfacePowers(
        run, surfaces, cosines, lit, factors, absorbed, emitted, _surface_notes(thermal)
    )


def _surface_notes(thermal: PayloadThermal) -> list[str]:
    """Notes on the surfaces typed in, which nothing shades."""
    typed = [name for name, surface in thermal.surfaces.items() if surface.part is None]
    if not typed:
        return []
    return [
        f"Some surfaces are typed in, not taken from the 3D model: {', '.join(typed)}. "
        "They stay fixed in body axes, and nothing shades them."
    ]
