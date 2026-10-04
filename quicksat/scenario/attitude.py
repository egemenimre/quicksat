# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
The body's orientation over a run, from the attitudes the activities name.

Each attitude points one body axis along a direction, and turns a second body
axis as close as it can get to another direction:

- `nadir` points `nadir_axis` at the centre of the Earth, and puts
  `orbit_normal` along the orbit normal. The orbit normal is the position
  crossed with the velocity. It is always across the nadir, so this attitude is
  never undefined.
- `sun pointing` points `sun_axis` at the sun, as seen from the satellite. Its
  second axis comes as close as it can to the orbit normal, or to the nadir.

Sun pointing is undefined where the sun lies along that second direction: along
the orbit normal at a beta of +-90 degrees, or along the nadir line, deep in an
eclipse. At such a time the other of the two directions takes its place.

Attitude changes are instant. At each time of the grid, the body takes the
attitude of the activity under way then.

"""

import numpy as np
from astropy.coordinates import CartesianDifferential, CartesianRepresentation

from quicksat import u
from quicksat.orbit.attitude import align, axis_vector
from quicksat.scenario.config import NADIR, SUN_POINTING
from quicksat.scenario.run import ScenarioRun
from quicksat.utils.intervals import labels_at


def body_rotations(run: ScenarioRun) -> np.ndarray:
    """
    The body's orientation at each time of the run's grid.

    Parameters
    ----------
    run : ScenarioRun
        The run

    Returns
    -------
    rotations : ndarray
        Matrices that turn body vectors into GCRS, shape (n, 3, 3), one for each
        time of the grid. Column i is body axis i, seen in GCRS.
    """
    attitude = labels_at(run.attitude, run.times)
    # the run is open at its end, so the last time takes the last activity's attitude
    attitude[-1] = run.occurrences[-1].activity.attitude

    cartesian = run.state.cartesian
    assert isinstance(cartesian, CartesianRepresentation)
    velocity = cartesian.differentials["s"]
    assert isinstance(velocity, CartesianDifferential)
    position = cartesian.xyz.to_value(u.km).T
    nadir = -position
    normal = np.cross(position, velocity.d_xyz.to_value(u.km / u.s).T)
    sun = run.sun.xyz.to_value(u.km).T - position

    rotations = np.full((len(position), 3, 3), np.nan)
    attitudes = run.scenario.attitudes
    if attitudes.nadir is not None:
        rows = attitude == NADIR
        rotations[rows] = align(
            axis_vector(attitudes.nadir.nadir_axis),
            axis_vector(attitudes.nadir.orbit_normal),
            nadir[rows],
            normal[rows],
        )
    pointing = attitudes.sun_pointing
    if pointing is not None:
        rows = attitude == SUN_POINTING
        if pointing.constrain_to_nadir is not None:
            second_axis, second, fallback = pointing.constrain_to_nadir, nadir, normal
        else:
            assert pointing.constrain_to_orbit_normal is not None  # exactly one is
            second_axis, second, fallback = (
                pointing.constrain_to_orbit_normal,
                normal,
                nadir,
            )
        rotations[rows] = align(
            axis_vector(pointing.sun_axis),
            axis_vector(second_axis),
            sun[rows],
            second[rows],
            fallback[rows],
        )
    return rotations
