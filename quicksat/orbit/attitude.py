# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
Rotations that point body axes along directions in space, and rest-to-rest slews between
them.

An attitude is a TRIAD construction: the first body axis points along the first
direction, and the second comes as close to the second direction as it can. A rotation
is a 3x3 matrix whose column i is body axis i in the directions' frame. A quaternion is
`[x, y, z, w]`, scalar last. `docs/scenario/scenario_ref.ipynb`, under "The attitudes",
explains the attitudes and the slews.

"""

import numpy as np
from scipy.spatial.transform import Rotation

_DEGENERATE = 1e-6
"""The sine of the angle below which two directions count as parallel."""


class ParallelDirections(ValueError):
    """
    Two directions of an attitude are parallel, so they do not fix the turn.

    Parameters
    ----------
    message : str
        What is parallel
    row : int
        The first row where it happens
    """

    def __init__(self, message: str, row: int):
        super().__init__(message)
        self.row = row


def axis_vector(axis: str) -> np.ndarray:
    """
    The unit vector of a signed body axis.

    Parameters
    ----------
    axis : str
        A signed body axis, such as `+z`

    Returns
    -------
    vector : ndarray
        Shape (3,)
    """
    vector = np.zeros(3)
    vector["xyz".index(axis[1])] = -1.0 if axis[0] == "-" else 1.0
    return vector


def _unit(vectors: np.ndarray) -> np.ndarray:
    """Vectors scaled to unit length along the last axis."""
    return vectors / np.linalg.norm(vectors, axis=-1, keepdims=True)


def align(
    body_first: np.ndarray,
    body_second: np.ndarray,
    first: np.ndarray,
    second: np.ndarray,
    fallback: np.ndarray | None = None,
) -> np.ndarray:
    """
    Rotations that point one body axis along a direction, and turn a second as close as
    it can to a second direction.

    Where the second direction is parallel to the first, the fallback takes its place.

    Parameters
    ----------
    body_first, body_second : ndarray
        Two perpendicular unit vectors in body axes, shape (3,)
    first : ndarray
        The direction for `body_first`, shape (n, 3), of any length
    second : ndarray
        The direction for `body_second` to come close to, shape (n, 3)
    fallback : ndarray, optional
        The direction that replaces a parallel `second`, shape (n, 3)

    Returns
    -------
    rotations : ndarray
        From body axes into the directions' frame, shape (n, 3, 3)

    Raises
    ------
    ParallelDirections
        A `ValueError`, if `second` and any fallback are parallel to `first`, giving the
        first such row
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
            raise ParallelDirections(
                "the second direction is parallel to the first",
                int(np.flatnonzero(parallel)[0]),
            )
        replacement, still_parallel = perpendicular(fallback)
        if (parallel & still_parallel).any():
            raise ParallelDirections(
                "the fallback direction is parallel to the first too",
                int(np.flatnonzero(parallel & still_parallel)[0]),
            )
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
    The quaternions of a sequence of rotations, each signed nearest the one before, so
    the viewer can interpolate.

    Parameters
    ----------
    rotations : ndarray
        Rotation matrices, shape (n, 3, 3)

    Returns
    -------
    quaternions : ndarray
        `[x, y, z, w]`, scalar last, shape (n, 4)
    """
    q = Rotation.from_matrix(rotations).as_quat()
    flips = np.where(np.sum(q[1:] * q[:-1], axis=1) < 0, -1.0, 1.0)
    return q * np.cumprod(np.concatenate([[1.0], flips]))[:, None]


def rotation_angles(first: np.ndarray, second: np.ndarray) -> np.ndarray:
    """
    The angle of the single turn from each rotation to the other.

    Parameters
    ----------
    first, second : ndarray
        Rotation matrices, shape (n, 3, 3) or (3, 3)

    Returns
    -------
    angles : ndarray
        In rad, from 0 to pi, shape (n,)
    """
    relative = Rotation.from_matrix(first).inv() * Rotation.from_matrix(second)
    return np.atleast_1d(relative.magnitude())


def body_rates(
    rotations: np.ndarray, seconds: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """
    The body's turn rate over each step, and its angular acceleration between steps, as
    averages.

    A change of the turn's axis counts, as well as one of its rate. A peak shorter than
    a step reads low.

    Parameters
    ----------
    rotations : ndarray
        From body axes into an inertial frame, shape (n, 3, 3), NaN where there is no
        orientation
    seconds : ndarray
        The times, rising, in s, shape (n,)

    Returns
    -------
    rates : ndarray
        In rad/s, shape (n - 1,), NaN next to a missing orientation
    accelerations : ndarray
        In rad/s2, shape (n - 2,), NaN next to a missing rate
    """
    known = np.isfinite(rotations).all(axis=(1, 2))
    both = known[:-1] & known[1:]
    steps = np.diff(seconds)
    omega = np.full((len(steps), 3), np.nan)
    if both.any():
        turns = Rotation.from_matrix(rotations[:-1][both]).inv() * Rotation.from_matrix(
            rotations[1:][both]
        )
        omega[both] = turns.as_rotvec() / steps[both, None]
    middles = (seconds[:-1] + seconds[1:]) / 2
    accelerations = np.linalg.norm(np.diff(omega, axis=0), axis=1) / np.diff(middles)
    return np.linalg.norm(omega, axis=1), accelerations


def lvlh_rotations(position: np.ndarray, velocity: np.ndarray) -> np.ndarray:
    """
    The local vertical, local horizontal frame (LVLH) at each state: x along the track,
    y minus the orbit normal, z nadir.

    Parameters
    ----------
    position, velocity : ndarray
        The states in an inertial frame, shape (n, 3)

    Returns
    -------
    rotations : ndarray
        From LVLH into the states' frame, shape (n, 3, 3)
    """
    z = _unit(-position)
    y = _unit(-np.cross(position, velocity))
    return np.stack([np.cross(y, z), y, z], axis=-1)


def roll_pitch_yaw(rotations: np.ndarray, frames: np.ndarray) -> np.ndarray:
    """
    The body's roll, pitch and yaw against a reference frame, such as LVLH, in the 3-2-1
    sequence.

    Pitch is within ±90 degrees, and roll and yaw within ±180. Near a pitch of ±90
    degrees, roll and yaw are not well defined.

    Parameters
    ----------
    rotations : ndarray
        From body axes into an inertial frame, shape (n, 3, 3)
    frames : ndarray
        From the reference frame into the same inertial frame, shape (n, 3, 3)

    Returns
    -------
    angles : ndarray
        Roll, pitch and yaw, in rad, shape (n, 3)
    """
    relative = Rotation.from_matrix(frames).inv() * Rotation.from_matrix(rotations)
    yaw, pitch, roll = relative.as_euler("ZYX").T
    return np.column_stack([roll, pitch, yaw])


def turn_between(
    start: np.ndarray,
    ends: np.ndarray,
    fractions: np.ndarray,
    toward: np.ndarray | None = None,
) -> np.ndarray:
    """
    Rotations part of the way from one rotation to others, by spherical interpolation.

    Each turn goes the shorter way, unless `toward` fixes its direction, which keeps a
    slew's direction while its target moves.

    Parameters
    ----------
    start : ndarray
        The rotation turned from, shape (3, 3)
    ends : ndarray
        The rotations turned to, shape (n, 3, 3)
    fractions : ndarray
        How far along each turn, from 0 to 1, shape (n,)
    toward : ndarray, optional
        Quaternions near each end, `[x, y, z, w]`, shape (n, 4)

    Returns
    -------
    rotations : ndarray
        Shape (n, 3, 3)
    """
    q0 = Rotation.from_matrix(start).as_quat()
    q1 = Rotation.from_matrix(ends).as_quat()
    signs = q1 @ q0 if toward is None else np.sum(q1 * toward, axis=1)
    q1 = np.where(signs[:, None] < 0, -q1, q1)
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
    How long a rest-to-rest slew takes, settling excluded, with the agility budget's
    profile.

    Parameters
    ----------
    angle : ndarray
        The angles to turn through, in rad
    max_rate : float or None
        The fastest turn, in rad/s, None for no limit
    max_acceleration : float or None
        The fastest change of rate, in rad/s2, None to start and stop at once

    Returns
    -------
    duration : ndarray
        In s

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
    How far through a rest-to-rest slew the body has turned, from 0 to 1.

    Parameters
    ----------
    angle : float
        The slew's whole angle, in rad
    elapsed : ndarray
        The time since the slew started, in s
    max_rate, max_acceleration : float or None
        The limits, as for `slew_duration`

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
