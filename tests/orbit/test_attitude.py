# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
Tests for the rotations that point body axes along directions.

The directions are placed by hand, so each expected rotation follows from the
geometry alone.
"""

import numpy as np
import pytest

from quicksat.orbit.attitude import (
    align,
    axis_vector,
    quaternions,
    rotation_angles,
    slew_duration,
    slew_progress,
    turn_between,
)


def matrices_of(q):
    """Rotation matrices from quaternions `[x, y, z, w]`, by the textbook formula."""
    x, y, z, w = np.asarray(q).T
    return np.stack(
        [
            np.column_stack(
                [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)]
            ),
            np.column_stack(
                [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)]
            ),
            np.column_stack(
                [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]
            ),
        ],
        axis=1,
    )


def about_z(angles):
    """Rotations about the z axis by each angle, in radians."""
    cos, sin = np.cos(angles), np.sin(angles)
    zero, one = np.zeros_like(angles), np.ones_like(angles)
    return np.stack(
        [
            np.column_stack([cos, -sin, zero]),
            np.column_stack([sin, cos, zero]),
            np.column_stack([zero, zero, one]),
        ],
        axis=1,
    )


@pytest.mark.parametrize(
    ("axis", "vector"), [("+x", [1, 0, 0]), ("-y", [0, -1, 0]), ("+z", [0, 0, 1])]
)
def test_axis_vector(axis, vector):
    assert np.array_equal(axis_vector(axis), vector)


# ---------------------------------------------------------------- align


@pytest.fixture
def directions():
    """Two directions at a few times, neither of unit length, and not perpendicular."""
    rng = np.random.default_rng(7)
    first = rng.normal(size=(20, 3)) * 7000
    second = rng.normal(size=(20, 3)) * 3
    return first, second


def test_align_points_the_first_axis_along_the_first_direction(directions):
    first, second = directions
    rotations = align(axis_vector("-z"), axis_vector("+y"), first, second)
    pointed = rotations @ axis_vector("-z")
    unit = first / np.linalg.norm(first, axis=1, keepdims=True)
    assert np.allclose(pointed, unit, atol=1e-14)


def test_align_brings_the_second_axis_as_close_as_it_can(directions):
    first, second = directions
    rotations = align(axis_vector("-z"), axis_vector("+y"), first, second)
    unit = first / np.linalg.norm(first, axis=1, keepdims=True)
    across = second - np.sum(second * unit, axis=1, keepdims=True) * unit
    across /= np.linalg.norm(across, axis=1, keepdims=True)
    assert np.allclose(rotations @ axis_vector("+y"), across, atol=1e-14)


def test_align_gives_proper_rotations(directions):
    rotations = align(axis_vector("+x"), axis_vector("-z"), *directions)
    identity = rotations @ np.transpose(rotations, (0, 2, 1))
    assert np.allclose(identity, np.eye(3), atol=1e-14)
    assert np.allclose(np.linalg.det(rotations), 1.0, atol=1e-14)


def test_align_turns_to_the_fallback_where_the_two_directions_are_parallel():
    first = np.array([[1.0, 0, 0], [1.0, 0, 0]])
    second = np.array([[2.0, 0, 0], [0, 0, 5.0]])
    fallback = np.array([[0, 3.0, 0], [0, 3.0, 0]])
    rotations = align(axis_vector("-z"), axis_vector("+y"), first, second, fallback)
    assert np.allclose(rotations[0] @ axis_vector("+y"), [0, 1, 0])
    assert np.allclose(rotations[1] @ axis_vector("+y"), [0, 0, 1])


def test_align_refuses_parallel_directions_without_a_fallback():
    first = np.array([[1.0, 0, 0]])
    with pytest.raises(ValueError, match="parallel"):
        align(axis_vector("-z"), axis_vector("+y"), first, -first)
    with pytest.raises(ValueError, match="fallback"):
        align(axis_vector("-z"), axis_vector("+y"), first, first, 2 * first)


# ---------------------------------------------------------------- quaternions


def test_quaternion_of_a_quarter_turn_about_z():
    q = quaternions(about_z(np.array([np.pi / 2])))
    assert np.allclose(q, [[0, 0, np.sqrt(0.5), np.sqrt(0.5)]])


def test_quaternions_give_back_the_matrices():
    rng = np.random.default_rng(1)
    rotations, _ = np.linalg.qr(rng.normal(size=(2000, 3, 3)))
    rotations[np.linalg.det(rotations) < 0, :, 0] *= -1
    # half turns about each axis, where the scalar part is zero
    half_turns = np.array(
        [np.diag([1.0, -1, -1]), np.diag([-1.0, 1, -1]), np.diag([-1.0, -1, 1])]
    )
    rotations = np.concatenate([rotations, half_turns, [np.eye(3)]])
    q = quaternions(rotations)
    assert np.allclose(np.linalg.norm(q, axis=1), 1.0, atol=1e-14)
    assert np.allclose(matrices_of(q), rotations, atol=1e-14)


def test_quaternions_keep_neighbours_on_the_same_side():
    # a full turn and more in small steps passes where scipy's sign would flip
    q = quaternions(about_z(np.linspace(0, 3 * np.pi, 200)))
    assert np.all(np.sum(q[1:] * q[:-1], axis=1) > 0)


# ---------------------------------------------------------------- Turns and slews


def test_rotation_angles():
    turns = about_z(np.radians([0.0, 30.0, 90.0, 180.0]))
    angles = rotation_angles(np.eye(3), turns)
    assert np.degrees(angles) == pytest.approx([0, 30, 90, 180])


def test_rotation_angles_resolve_tiny_turns():
    # the cosine of a nanoradian rounds to 1, so the angle must come another way
    assert rotation_angles(np.eye(3), about_z(np.array([1e-9]))) == pytest.approx(
        [1e-9], rel=1e-6
    )


def test_turn_between_starts_and_ends_where_it_should():
    start, ends = np.eye(3), about_z(np.radians([90.0, 90.0, 90.0]))
    rotations = turn_between(start, ends, np.array([0.0, 0.5, 1.0]))
    assert np.degrees(rotation_angles(start, rotations)) == pytest.approx([0, 45, 90])


def test_a_reference_keeps_the_turn_going_one_way():
    # targets just either side of a half turn: alone, each turn goes the shorter
    # way, so the two halfway points lie on opposite sides
    ends = about_z(np.radians([179.0, 181.0]))
    free = turn_between(np.eye(3), ends, np.array([0.5, 0.5]))
    held = turn_between(np.eye(3), ends, np.array([0.5, 0.5]), reference=ends[0])
    assert np.degrees(rotation_angles(free[0], free[1])[0]) > 170
    assert np.degrees(rotation_angles(held[0], held[1])[0]) == pytest.approx(1.0)


RATE, ACCELERATION = np.radians(0.7), np.radians(0.08)
"""The sizing sample's rate and acceleration, in rad/s and rad/s2."""


@pytest.mark.parametrize("degrees", [3.0, 45.0, 90.0, 180.0])
def test_slew_duration_matches_the_rest_to_rest_profile(degrees):
    angle = np.radians(degrees)
    crossover = RATE**2 / ACCELERATION
    if angle <= crossover:
        expected = 2 * np.sqrt(angle / ACCELERATION)
    else:
        expected = angle / RATE + RATE / ACCELERATION
    assert float(slew_duration(np.array(angle), RATE, ACCELERATION)) == pytest.approx(
        expected
    )


def test_slew_duration_with_one_limit():
    angle = np.array(np.pi / 2)
    assert float(slew_duration(angle, RATE, None)) == pytest.approx(np.pi / 2 / RATE)
    assert float(slew_duration(angle, None, ACCELERATION)) == pytest.approx(
        2 * np.sqrt(np.pi / 2 / ACCELERATION)
    )
    with pytest.raises(ValueError, match="maximum rate"):
        slew_duration(angle, None, None)


@pytest.mark.parametrize("degrees", [3.0, 90.0])
@pytest.mark.parametrize(
    "limits", [(RATE, ACCELERATION), (RATE, None), (None, ACCELERATION)]
)
def test_slew_progress_runs_from_zero_to_one_within_the_rate(degrees, limits):
    angle = np.radians(degrees)
    duration = float(slew_duration(np.array(angle), *limits))
    times = np.linspace(0, duration, 1001)
    progress = slew_progress(angle, times, *limits)
    assert progress[0] == 0
    assert progress[-1] == pytest.approx(1)
    assert progress[500] == pytest.approx(0.5, abs=1e-3)
    assert np.all(np.diff(progress) >= 0)
    rates = np.diff(progress) * angle / np.diff(times)
    if limits[0] is not None:
        assert rates.max() <= limits[0] * (1 + 1e-9)
    assert slew_progress(angle, np.array([duration + 10]), *limits)[0] == 1
