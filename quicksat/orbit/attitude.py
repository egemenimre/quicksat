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

"""

import numpy as np

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
    Shepperd's method gives it.

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
    m = rotations
    # Four times each product of two components, read off the matrix
    product = {
        "xw": m[:, 2, 1] - m[:, 1, 2],
        "yw": m[:, 0, 2] - m[:, 2, 0],
        "zw": m[:, 1, 0] - m[:, 0, 1],
        "xy": m[:, 0, 1] + m[:, 1, 0],
        "xz": m[:, 0, 2] + m[:, 2, 0],
        "yz": m[:, 1, 2] + m[:, 2, 1],
    }
    # Four times the square of each component, from the diagonal
    square = {
        "w": 1 + m[:, 0, 0] + m[:, 1, 1] + m[:, 2, 2],
        "x": 1 + m[:, 0, 0] - m[:, 1, 1] - m[:, 2, 2],
        "y": 1 - m[:, 0, 0] + m[:, 1, 1] - m[:, 2, 2],
        "z": 1 - m[:, 0, 0] - m[:, 1, 1] + m[:, 2, 2],
    }
    # Shepperd's method: take the largest component from its square, and the
    # others from their products with it, so that nothing divides by a small number
    names = list(square)
    largest = np.argmax(np.stack([square[name] for name in names], axis=-1), axis=-1)
    q = np.empty((len(m), 4))
    for index, known in enumerate(names):
        rows = largest == index
        size = 0.5 * np.sqrt(square[known][rows])
        values = {known: size}
        for other in "xyzw".replace(known, ""):
            pair = "".join(sorted(known + other, key="xyzw".index))
            values[other] = product[pair][rows] / (4 * size)
        q[rows] = np.column_stack([values[name] for name in "xyzw"])

    flips = np.where(np.sum(q[1:] * q[:-1], axis=1) < 0, -1.0, 1.0)
    return q * np.cumprod(np.concatenate([[1.0], flips]))[:, None]
