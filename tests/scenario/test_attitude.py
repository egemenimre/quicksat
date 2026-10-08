# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
Tests for the body's orientation over a run.

The fixture's attitudes are nadir with `+z` at the nadir and `-y` along the orbit
normal, and sun pointing with `-z` at the sun and `-y` kept along the orbit
normal. Each step is checked against the directions worked out from the state.
"""

import numpy as np
import pytest

from quicksat import u
from quicksat.orbit.attitude import axis_vector
from quicksat.scenario.attitude import body_rotations
from quicksat.utils.intervals import labels_at


def unit(vectors):
    """Vectors scaled to unit length."""
    return vectors / np.linalg.norm(vectors, axis=1, keepdims=True)


@pytest.fixture(scope="module")
def pointing(run):
    """The rotations, the attitude at each step, and the reference directions."""
    rotations = body_rotations(run)
    attitude = labels_at(run.attitude, run.times)
    attitude[-1] = run.occurrences[-1].activity.attitude
    cartesian = run.state.cartesian
    position = cartesian.xyz.to_value(u.km).T
    velocity = cartesian.differentials["s"].d_xyz.to_value(u.km / u.s).T
    directions = {
        "nadir": unit(-position),
        "normal": unit(np.cross(position, velocity)),
        "sun": unit(run.sun.xyz.to_value(u.km).T - position),
        "velocity": unit(velocity),
    }
    return rotations, attitude, directions


def axis_in_gcrs(rotations, axis):
    """Where a body axis points, in GCRS, at each step."""
    return rotations @ axis_vector(axis)


def test_every_step_has_a_proper_rotation(pointing):
    rotations, attitude, _ = pointing
    assert set(attitude) == {"nadir", "sun pointing"}
    assert np.allclose(
        rotations @ np.transpose(rotations, (0, 2, 1)), np.eye(3), atol=1e-12
    )
    assert np.allclose(np.linalg.det(rotations), 1.0, atol=1e-12)


def test_nadir_points_its_axes_as_set(pointing):
    rotations, attitude, directions = pointing
    rows = attitude == "nadir"
    assert np.allclose(
        axis_in_gcrs(rotations[rows], "+z"), directions["nadir"][rows], atol=1e-12
    )
    assert np.allclose(
        axis_in_gcrs(rotations[rows], "-y"), directions["normal"][rows], atol=1e-12
    )


def test_nadir_with_these_axes_is_lvlh(pointing):
    # x then runs along the track, within the small angle of a near-circular orbit
    rotations, attitude, directions = pointing
    rows = attitude == "nadir"
    cosine = np.sum(
        axis_in_gcrs(rotations[rows], "+x") * directions["velocity"][rows], axis=1
    )
    assert np.degrees(np.arccos(np.clip(cosine, -1, 1))).max() < 0.1


def test_sun_pointing_points_its_axes_as_set(pointing):
    rotations, attitude, directions = pointing
    rows = attitude == "sun pointing"
    sun, normal = directions["sun"][rows], directions["normal"][rows]
    across = unit(normal - np.sum(normal * sun, axis=1, keepdims=True) * sun)
    assert np.allclose(axis_in_gcrs(rotations[rows], "-z"), sun, atol=1e-12)
    assert np.allclose(axis_in_gcrs(rotations[rows], "-y"), across, atol=1e-12)
