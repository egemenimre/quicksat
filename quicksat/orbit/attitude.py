# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
Rotations that point body axes along directions in space.

An attitude names two body axes and two directions. The first axis points
exactly along the first direction. The second axis comes as close to the second
direction as the first allows. This is the TRIAD construction: each pair is
completed to a right-handed set of three axes, and the rotation takes one set
onto the other.

A rotation is held as a 3x3 matrix that turns body vectors into the frame of the
directions: column i is body axis i, seen in that frame. A quaternion is
`[x, y, z, w]`, with the scalar last, which is the order three.js and scipy use.
scipy's `Rotation` converts between the two, and composes rotations. The TRIAD
construction stays here, because scipy's `align_vectors` takes one time per call.

A slew turns the body from one attitude to another, from rest to rest, about one
axis. It speeds up at the maximum acceleration, coasts at the maximum rate if it
reaches it, and slows down at the maximum acceleration. A slew too short to
reach the maximum rate speeds up to its midpoint and slows down from there. This
is the same profile as the agility budget's, with one rate and one acceleration
for every axis.

"""

import numpy as np
from scipy.spatial.transform import Rotation

_DEGENERATE = 1e-6
"""Sine of the angle below which two directions count as parallel. The second
direction then no longer fixes the turn about the first."""


def axis_vector(axis: str) -> np.ndarray:
    """
    The unit vector of a signed body axis.

    Parameters
    ----------
    axis : str
        A body axis with its sign, such as `+z` or `-y`

    Returns
    -------
    vector : ndarray
        The unit vector, shape (3,)
    """
    vector = np.zeros(3)
    vector["xyz".index(axis[1])] = -1.0 if axis[0] == "-" else 1.0
    return vector


def _unit(vectors: np.ndarray) -> np.ndarray:
    """
    Vectors scaled to unit length, along the last axis.

    Parameters
    ----------
    vectors : ndarray
        Vectors, shape (..., 3)

    Returns
    -------
    unit : ndarray
        The unit vectors, same shape
    """
    return vectors / np.linalg.norm(vectors, axis=-1, keepdims=True)


def align(
    body_first: np.ndarray,
    body_second: np.ndarray,
    first: np.ndarray,
    second: np.ndarray,
    fallback: np.ndarray | None = None,
) -> np.ndarray:
    """
    Rotations that point one body axis along a direction, and turn a second
    body axis as close as it can get to a second direction.

    Where the second direction is parallel to the first, it no longer fixes the
    turn about the first. The fallback direction takes its place there.

    Parameters
    ----------
    body_first, body_second : ndarray
        Two perpendicular unit vectors in body axes, shape (3,), such as from
        `axis_vector`
    first : ndarray
        The direction for `body_first` at each time, shape (n, 3). It need not be
        of unit length.
    second : ndarray
        The direction for `body_second` to come close to, shape (n, 3)
    fallback : ndarray, optional
        The direction that replaces `second` where `second` is parallel to
        `first`, shape (n, 3)

    Returns
    -------
    rotations : ndarray
        Matrices that turn body vectors into the frame of the directions, shape
        (n, 3, 3)

    Raises
    ------
    ValueError
        If `second` is parallel to `first` somewhere, and there is no fallback,
        or the fallback is parallel too
    """
    target_first = _unit(first)

    def perpendicular(direction: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        # the part of the unit direction across the first direction, and where
        # that part is too small to fix the turn
        unit = _unit(direction)
        across = (
            unit - np.sum(unit * target_first, axis=-1, keepdims=True) * target_first
        )
        return across, np.linalg.norm(across, axis=-1) < _DEGENERATE

    target_second, parallel = perpendicular(second)
    if parallel.any():
        if fallback is None:
            raise ValueError("the second direction is parallel to the first")
        replacement, still_parallel = perpendicular(fallback)
        if (parallel & still_parallel).any():
            raise ValueError("the fallback direction is parallel to the first too")
        target_second = np.where(parallel[:, None], replacement, target_second)
    target_second = _unit(target_second)

    targets = np.stack(
        [target_first, target_second, np.cross(target_first, target_second)], axis=-1
    )
    body = np.stack(
        [body_first, body_second, np.cross(body_first, body_second)], axis=-1
    )
    return targets @ body.T


def quaternions(rotations: np.ndarray) -> np.ndarray:
    """
    The quaternions of a sequence of rotation matrices, as a smooth sequence.

    A quaternion and its negative give the same rotation. Each quaternion here
    takes the sign that keeps it closest to the one before it, so that the
    viewer can interpolate between neighbours. The first takes the sign that
    scipy gives it.

    Parameters
    ----------
    rotations : ndarray
        Rotation matrices, shape (n, 3, 3), each turning vectors from one frame
        into another

    Returns
    -------
    quaternions : ndarray
        The quaternions `[x, y, z, w]`, scalar last, shape (n, 4)
    """
    q = Rotation.from_matrix(rotations).as_quat()
    flips = np.where(np.sum(q[1:] * q[:-1], axis=1) < 0, -1.0, 1.0)
    return q * np.cumprod(np.concatenate([[1.0], flips]))[:, None]


def rotation_angles(first: np.ndarray, second: np.ndarray) -> np.ndarray:
    """
    The angle of the single turn that takes each rotation to the other.

    Parameters
    ----------
    first, second : ndarray
        Rotation matrices, shape (n, 3, 3) or (3, 3)

    Returns
    -------
    angles : ndarray
        The angles, from 0 to pi [rad], shape (n,)
    """
    relative = Rotation.from_matrix(first).inv() * Rotation.from_matrix(second)
    return np.atleast_1d(relative.magnitude())


def turn_between(
    start: np.ndarray,
    ends: np.ndarray,
    fractions: np.ndarray,
    reference: np.ndarray | None = None,
) -> np.ndarray:
    """
    Rotations part of the way from one rotation to others.

    This is spherical linear interpolation of the quaternions. By default each
    turn goes the shorter way round. With a reference, every turn goes the way
    that is shorter to the reference. That keeps the direction of a slew fixed
    while its target moves, even where the target drifts past a half turn away.

    Parameters
    ----------
    start : ndarray
        The rotation turned from, shape (3, 3)
    ends : ndarray
        The rotations turned to, shape (n, 3, 3)
    fractions : ndarray
        How far along each turn, from 0 at `start` to 1 at the end, shape (n,)
    reference : ndarray, optional
        A rotation close to all the ends, shape (3, 3), that fixes the direction

    Returns
    -------
    rotations : ndarray
        Shape (n, 3, 3)
    """
    q0 = Rotation.from_matrix(start).as_quat()
    q1 = Rotation.from_matrix(ends).as_quat()
    # q and -q are the same rotation, and the sign of q1 sets which way the turn
    # goes: the sign nearer q0 is the shorter way round
    toward = q0
    if reference is not None:
        toward = Rotation.from_matrix(reference).as_quat()
        toward = toward if toward @ q0 >= 0 else -toward
    q1 = np.where((q1 @ toward)[:, None] < 0, -q1, q1)
    angle = np.arccos(np.clip(q1 @ q0, -1.0, 1.0))
    fractions = np.asarray(fractions, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        sine = np.sin(angle)
        small = angle < 1e-9
        weight0 = np.where(small, 1 - fractions, np.sin((1 - fractions) * angle) / sine)
        weight1 = np.where(small, fractions, np.sin(fractions * angle) / sine)
    q = weight0[:, None] * q0 + weight1[:, None] * q1
    return Rotation.from_quat(q).as_matrix()


def slew_duration(
    angle: np.ndarray, max_rate: float | None, max_acceleration: float | None
) -> np.ndarray:
    """
    How long a rest-to-rest slew takes, settling excluded.

    Parameters
    ----------
    angle : ndarray
        The angles to turn through [rad]
    max_rate : float or None
        The fastest the body turns [rad/s]. None for no limit.
    max_acceleration : float or None
        The fastest the turn speeds up or slows down [rad/s^2]. None for no
        limit, which starts and stops the turn at once.

    Returns
    -------
    duration : ndarray
        The slew times [s]

    Raises
    ------
    ValueError
        If neither limit is given
    """
    angle = np.asarray(angle, dtype=float)
    if max_rate is None and max_acceleration is None:
        raise ValueError("a slew needs a maximum rate, a maximum acceleration, or both")
    if max_acceleration is None:
        assert max_rate is not None
        return angle / max_rate
    triangular = 2 * np.sqrt(angle / max_acceleration)
    if max_rate is None:
        return triangular
    coasting = angle / max_rate + max_rate / max_acceleration
    return np.where(angle <= max_rate**2 / max_acceleration, triangular, coasting)


def slew_progress(
    angle: float,
    elapsed: np.ndarray,
    max_rate: float | None,
    max_acceleration: float | None,
) -> np.ndarray:
    """
    How far through a rest-to-rest slew the body has turned, as a fraction.

    Parameters
    ----------
    angle : float
        The whole angle of the slew [rad]
    elapsed : ndarray
        Time since the slew started [s]
    max_rate, max_acceleration : float or None
        The limits of the turn, as for `slew_duration`

    Returns
    -------
    fraction : ndarray
        0 at the start, 1 once the slew is over
    """
    elapsed = np.asarray(elapsed, dtype=float)
    duration = float(slew_duration(np.array(angle), max_rate, max_acceleration))
    if angle <= 0 or duration <= 0:
        return np.ones_like(elapsed)
    tau = np.clip(elapsed, 0.0, duration)
    if max_acceleration is None:
        turned = angle * tau / duration
    else:
        # the time spent speeding up, and again slowing down, from
        # angle = acceleration * ramp * (duration - ramp)
        root = duration**2 / 4 - angle / max_acceleration
        ramp = duration / 2 - np.sqrt(max(root, 0.0))
        peak = max_acceleration * ramp
        speeding = 0.5 * max_acceleration * tau**2
        coasting = 0.5 * peak * ramp + peak * (tau - ramp)
        slowing = angle - 0.5 * max_acceleration * (duration - tau) ** 2
        turned = np.where(
            tau <= ramp, speeding, np.where(tau <= duration - ramp, coasting, slowing)
        )
    return np.clip(turned / angle, 0.0, 1.0)
