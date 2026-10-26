# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
The articulations: the parts of the 3D model that turn about one axis, such as a solar
wing.

At each step, a part takes its park angle in a platform mode that `park` names, or else
turns its pointing axis as close to its direction as the drive axis allows, clamped to
its range. There is no rate limit. Where the direction lies along the drive axis, the
part keeps its last angle. `docs/scenario/scenario_ref.ipynb`, under "Articulations",
explains them.

"""

from typing import TYPE_CHECKING

import numpy as np
from astropy.units import Quantity

from quicksat import Q_, u
from quicksat.orbit.attitude import axis_vector
from quicksat.scenario.attitude import body_rotations, directions
from quicksat.scenario.names import PLATFORM, SUN
from quicksat.utils.intervals import labels_at

if TYPE_CHECKING:  # a type annotation only, as run.py imports this module
    from quicksat.scenario.run import ScenarioRun

GAP = 1e-6
"""The length below which the direction's part across the drive axis counts as none,
within 0.2 arcseconds."""


def tracking_angles(
    axis: np.ndarray, pointing_axis: np.ndarray, targets: np.ndarray
) -> np.ndarray:
    """
    The angles that turn `pointing_axis` about `axis` as close to each target direction
    as it goes.

    Parameters
    ----------
    axis, pointing_axis : ndarray
        Perpendicular unit vectors in body axes, shape (3,)
    targets : ndarray
        Unit vectors toward the direction, in body axes, shape (n, 3)

    Returns
    -------
    angles : ndarray
        In rad, from -pi to pi, NaN where the direction lies along the axis
    """
    across = targets - np.outer(targets @ axis, axis)
    side = np.cross(axis, pointing_axis)
    angles = np.arctan2(across @ side, across @ pointing_axis)
    angles[np.linalg.norm(across, axis=1) < GAP] = np.nan
    return angles


def hold_last(angles: np.ndarray) -> np.ndarray:
    """
    The angles with each undefined one replaced by the last defined one.

    Parameters
    ----------
    angles : ndarray
        Angles in time order, NaN where undefined

    Returns
    -------
    angles : ndarray
        With no NaN: before the first defined angle, that angle, and all zero if none is
        defined
    """
    defined = ~np.isnan(angles)
    if not defined.any():
        return np.zeros_like(angles)
    last = np.where(defined, np.arange(len(angles)), 0)
    np.maximum.accumulate(last, out=last)
    held = angles[last]
    first = int(np.flatnonzero(defined)[0])
    held[:first] = angles[first]
    return held


def clamp_to_range(angles: np.ndarray, low: float, high: float) -> np.ndarray:
    """
    The angles held inside a range, each one outside moved to the end it reaches by the
    smaller turn.

    Parameters
    ----------
    angles : ndarray
        In degrees, from -180 to 180
    low, high : float
        The range's ends, in degrees, with -180 <= low < high <= 180

    Returns
    -------
    angles : ndarray
        In degrees, a tie going to `low`
    """
    outside = (angles < low) | (angles > high)
    up_to_low = np.mod(low - angles, 360)
    down_to_high = np.mod(angles - high, 360)
    nearer = np.where(up_to_low <= down_to_high, low, high)
    return np.where(outside, nearer, angles)


def grid_modes(run: "ScenarioRun", group: str) -> np.ndarray:
    """
    The payload's or the platform's mode at each time of the run's grid, the platform's
    `slew` included.

    Parameters
    ----------
    run : ScenarioRun
        The run
    group : str
        `payload` or `platform`

    Returns
    -------
    modes : ndarray
        The modes, as objects

    Raises
    ------
    ValueError
        If part of the run is `unplanned`
    """
    run.check_planned("the modes on the grid")
    modes = labels_at(run.mode[group], run.times)
    # the run is open at its end, so the last time takes the last activity's mode
    modes[-1] = run.occurrences[-1].activity.mode[group]
    return modes


def articulation_angles(run: "ScenarioRun") -> dict[str, Quantity]:
    """
    The angle of each articulation at each time of the run's grid.

    Parameters
    ----------
    run : ScenarioRun
        The run

    Returns
    -------
    angles : dict of str to Quantity
        Each articulation's angles in degrees, from -180 to 180, by name

    Raises
    ------
    ValueError
        If there are articulations and part of the run is `unplanned`
    """
    model = run.scenario.spacecraft_model
    if model is None or not model.articulations:
        return {}
    run.check_planned("the articulations' angles")
    targets = _body_directions(run, {a.point[1] for a in model.articulations.values()})
    modes = grid_modes(run, PLATFORM)

    angles = {}
    for name, articulation in model.articulations.items():
        axis, direction = articulation.point
        tracking = tracking_angles(
            axis_vector(articulation.axis), axis_vector(axis), targets[direction]
        )
        # in degrees from here, so that the range ends and the park angles come
        # out exactly as the file writes them
        low, high = (end.to_value(u.deg) for end in articulation.range)
        angle = clamp_to_range(np.degrees(hold_last(tracking)), low, high)
        for mode, park in articulation.park.items():
            angle[modes == mode] = park.to_value(u.deg)
        angles[name] = Q_(angle, "deg")
    return angles


def _body_directions(run: "ScenarioRun", names: set[str]) -> dict[str, np.ndarray]:
    """
    Directions as unit vectors in body axes on the grid, the sun from
    `ScenarioRun.sun_body`.
    """
    found = {SUN: run.sun_body} if SUN in names else {}
    others = names - {SUN}
    if others:
        # the rotations turn body vectors into GCRS, so their transposes turn back
        rotations = body_rotations(run)
        for name, vectors in directions(
            run.scenario, others, run.state, run.sun, run.grid.targets, run.grid.earth
        ).items():
            unit = vectors / np.linalg.norm(vectors, axis=1, keepdims=True)
            found[name] = np.einsum("nji,nj->ni", rotations, unit)
    return found
