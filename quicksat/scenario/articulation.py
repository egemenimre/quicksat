# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
The articulations: the parts of the 3D model that turn about one axis.

An articulation, such as a solar wing, turns about one body axis to point one of
its own axes toward a direction: the sun for a wing, or a ground station for an
antenna. The direction is one an attitude can use. At each time of the run's
grid, its angle is one of two:

- In a platform mode that its `park` names, the park angle. The drives are
  platform equipment, so the payload's mode does not park them.
- Otherwise the tracking angle. The direction, in body axes, loses its part
  along the drive axis, and the part's pointing axis turns onto what is left.
  The angle is then clamped to the range.

The angle is zero where the model draws the part, and turns right-handed about
the drive axis. It is set at each step from the geometry, with no drive and no
rate limit. It follows the body through its slews. A wing keeps tracking the sun
in eclipse, so it faces the sun when the sun rises. While the part tracks inside
its range, the cosine between its pointing axis and the direction is the length
of what is left: the square root of 1 - (direction . axis)**2.

Where the direction lies along the drive axis, the tracking angle is undefined.
The part then keeps the last angle it had. Before the first defined angle, it
takes that first one. If the direction never leaves the axis, the angle is zero.

"""

from typing import TYPE_CHECKING

import numpy as np
from astropy.units import Quantity

from quicksat import Q_, u
from quicksat.orbit.attitude import axis_vector
from quicksat.scenario.attitude import body_rotations, directions
from quicksat.scenario.config import PLATFORM, SUN
from quicksat.utils.intervals import labels_at

if TYPE_CHECKING:  # a type annotation only, as run.py imports this module
    from quicksat.scenario.run import ScenarioRun

GAP = 1e-6
"""Below this length, the direction's part across the drive axis counts as none:
the direction lies along the axis, within 0.2 arcseconds, and the angle is
undefined. The attitudes use the same limit."""


def tracking_angles(
    axis: np.ndarray, pointing_axis: np.ndarray, targets: np.ndarray
) -> np.ndarray:
    """
    The angles that turn `pointing_axis` about `axis` as close to each target
    direction as it goes.

    Parameters
    ----------
    axis, pointing_axis : ndarray
        Perpendicular unit vectors in body axes, shape (3,)
    targets : ndarray
        Unit vectors toward the direction, such as the sun, in body axes, shape
        (n, 3)

    Returns
    -------
    angles : ndarray
        In radians, from -pi to pi. NaN where the direction lies along the axis.
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
        No NaN left. The undefined angles before the first defined one take that
        first one. All zero if none is defined.
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
    The angles held inside a range, each one outside it moved to the nearer end.

    Parameters
    ----------
    angles : ndarray
        In degrees, from -180 to 180
    low, high : float
        The ends of the range, in degrees, with -180 <= low < high <= 180

    Returns
    -------
    angles : ndarray
        In degrees. The nearer end is the one the angle reaches by the smaller
        turn, going round through 180 if that is shorter. A tie goes to `low`.
    """
    outside = (angles < low) | (angles > high)
    up_to_low = np.mod(low - angles, 360)
    down_to_high = np.mod(angles - high, 360)
    nearer = np.where(up_to_low <= down_to_high, low, high)
    return np.where(outside, nearer, angles)


def grid_modes(run: "ScenarioRun", group: str) -> np.ndarray:
    """
    The payload's or the platform's mode at each time of the run's grid, the
    platform's `slew` included.

    Parameters
    ----------
    run : ScenarioRun
        The run
    group : str
        `payload` or `platform`

    Returns
    -------
    modes : ndarray
        The mode names, as an array of objects

    Raises
    ------
    ValueError
        If part of the run is unplanned: see `ScenarioRun.unplanned`
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
        For each articulation, by its name in the scenario file, its angles in
        degrees, from -180 to 180, one for each time of the grid. Empty without
        a model or without articulations.

    Raises
    ------
    ValueError
        If there are articulations and part of the run is unplanned: see
        `ScenarioRun.unplanned`
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
    Directions in body axes, as unit vectors on the run's grid.

    The sun comes from `ScenarioRun.sun_body`, which the run keeps. The other
    directions are worked out in GCRS and turned into body axes.

    Parameters
    ----------
    run : ScenarioRun
        The run
    names : set of str
        The directions: built-in ones and target names

    Returns
    -------
    directions : dict of str to ndarray
        Each direction, shape (n, 3), of unit length
    """
    found = {SUN: run.sun_body} if SUN in names else {}
    others = names - {SUN}
    if others:
        # the rotations turn body vectors into GCRS, so their transposes turn back
        rotations = body_rotations(run)
        for name, vectors in directions(
            run.scenario, others, run.state, run.sun, run.sat_orbits
        ).items():
            unit = vectors / np.linalg.norm(vectors, axis=1, keepdims=True)
            found[name] = np.einsum("nji,nj->ni", rotations, unit)
    return found
