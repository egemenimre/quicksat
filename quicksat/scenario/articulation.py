# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
The articulations: the parts of the 3D model that turn to face the sun.

An articulation, such as a solar wing, turns about one body axis. At each time
of the run's grid, its angle is one of two:

- In a mode that its `park` names, the park angle.
- Otherwise the tracking angle. The sun's direction in body axes loses its part
  along the drive axis, and the part's sun axis turns onto what is left. The
  angle is then clamped to the range.

The angle is zero where the model draws the part, and turns right-handed about
the drive axis. It is set at each step from the geometry, with no drive and no
rate limit. It follows the body through its slews. It keeps tracking in eclipse,
so the part faces the sun when the sun rises. While it tracks inside its range,
the cosine between its sun axis and the sun is the length of what is left: the
square root of 1 - (sun . axis)**2.

Where the sun lies along the drive axis, the tracking angle is undefined. The
part then keeps the last angle it had. Before the first defined angle, it takes
that first one. If the sun never leaves the axis, the angle is zero.

"""

from typing import TYPE_CHECKING

import numpy as np
from astropy.coordinates import CartesianRepresentation
from astropy.units import Quantity

from quicksat import Q_, u
from quicksat.orbit.attitude import axis_vector
from quicksat.scenario.attitude import body_rotations
from quicksat.utils.intervals import labels_at

if TYPE_CHECKING:  # a type annotation only, as run.py imports this module
    from quicksat.scenario.run import ScenarioRun

GAP = 1e-6
"""Below this length, the sun's part across the drive axis counts as none: the
sun lies along the axis, within 0.2 arcseconds, and the angle is undefined. The
attitudes use the same limit."""


def tracking_angles(
    axis: np.ndarray, sun_axis: np.ndarray, suns: np.ndarray
) -> np.ndarray:
    """
    The angles that turn `sun_axis` about `axis` as close to the sun as it goes.

    Parameters
    ----------
    axis, sun_axis : ndarray
        Perpendicular unit vectors in body axes, shape (3,)
    suns : ndarray
        Unit vectors to the sun in body axes, shape (n, 3)

    Returns
    -------
    angles : ndarray
        In radians, from -pi to pi. NaN where the sun lies along the axis.
    """
    across = suns - np.outer(suns @ axis, axis)
    side = np.cross(axis, sun_axis)
    angles = np.arctan2(across @ side, across @ sun_axis)
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
    """
    model = run.scenario.spacecraft_model
    if model is None or not model.articulations:
        return {}
    cartesian = run.state.cartesian
    assert isinstance(cartesian, CartesianRepresentation)
    position = cartesian.xyz.to_value(u.km).T
    sun = run.sun.xyz.to_value(u.km).T - position
    sun /= np.linalg.norm(sun, axis=1, keepdims=True)
    # the rotations turn body vectors into GCRS, so their transposes turn back
    suns = np.einsum("nji,nj->ni", body_rotations(run), sun)
    modes = labels_at(run.mode, run.times)
    # the run is open at its end, so the last time takes the last activity's mode
    modes[-1] = run.occurrences[-1].activity.mode

    angles = {}
    for name, articulation in model.articulations.items():
        tracking = tracking_angles(
            axis_vector(articulation.axis), axis_vector(articulation.sun_axis), suns
        )
        # in degrees from here, so that the range ends and the park angles come
        # out exactly as the file writes them
        low, high = (end.to_value(u.deg) for end in articulation.range)
        angle = clamp_to_range(np.degrees(hold_last(tracking)), low, high)
        for mode, park in articulation.park.items():
            angle[modes == mode] = park.to_value(u.deg)
        angles[name] = Q_(angle, "deg")
    return angles
