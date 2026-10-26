# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
Self-shadowing: the parts of the 3D model that shade the solar panels.

Sample points on each panel cast rays toward the sun, and a point is shaded when another
part's triangle blocks its ray. Each step projects the model once along the sun's
direction. Turning parts turn first. Cell strings are not modelled.
`docs/power/power_generation_ref.ipynb`, under "Self-shadowing", explains the method and
its tolerances.

"""

from collections.abc import Iterable

import numpy as np
from astropy.units import Quantity

from quicksat import u
from quicksat.orbit.attitude import axis_vector
from quicksat.scenario.config import SpacecraftModel
from quicksat.scenario.spacecraft import ModelGeometry, node_index, read_glb_json

RAY_OFFSET = 1e-6
"""How far off the cells each ray starts, along their normal, in m, against self-hits."""

EDGE = 1e-9
"""The barycentric test's tolerance, so no ray slips through the seam of two triangles."""

SHADED_LIMIT = 0.01
"""The share of a panel that must be shaded for it to count as shaded, so a shadow's
first touch is not timed late."""

_EDGE_ON = 1e-14
"""The projected area, doubled, below which a triangle is edge-on to the sun and casts
none."""


def sample_points(triangles: np.ndarray, points: int) -> tuple[np.ndarray, np.ndarray]:
    """
    Points on the triangles, each for an equal share of its triangle, about `points` in
    all.

    Parameters
    ----------
    triangles : ndarray
        The corners, shape (m, 3, 3)
    points : int
        About how many points to place

    Returns
    -------
    positions : ndarray
        The points, shape (k, 3)
    areas : ndarray
        The area each stands for, shape (k,)
    """
    edges = np.cross(
        triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0]
    )
    areas = np.linalg.norm(edges, axis=1) / 2
    cuts = np.maximum(1, np.round(np.sqrt(points * areas / areas.sum()))).astype(int)
    positions, weights = [], []
    for triangle, area, n in zip(triangles, areas, cuts, strict=True):
        if area == 0:
            continue
        # the centres of the n² smaller triangles, in the triangle's own
        # coordinates: n(n+1)/2 upright and n(n-1)/2 upside down
        uv = []
        for i in range(n):
            for j in range(n - i):
                uv.append(((i + 1 / 3) / n, (j + 1 / 3) / n))
                if i + j <= n - 2:
                    uv.append(((i + 2 / 3) / n, (j + 2 / 3) / n))
        uv = np.array(uv)
        a, b, c = triangle
        positions.append(a + uv[:, :1] * (b - a) + uv[:, 1:] * (c - a))
        weights.append(np.full(len(uv), area / n**2))
    return np.concatenate(positions), np.concatenate(weights)


def _basis(direction: np.ndarray) -> np.ndarray:
    """Two unit vectors across the direction, as the columns of a (3, 2) array."""
    helper = np.array([1.0, 0.0, 0.0])
    if abs(direction[0]) >= 0.9:
        helper = np.array([0.0, 1.0, 0.0])
    first = np.cross(direction, helper)
    first /= np.linalg.norm(first)
    return np.stack([first, np.cross(direction, first)], axis=1)


def lit_fraction(
    points: np.ndarray, weights: np.ndarray, blockers: np.ndarray, sun: np.ndarray
) -> float:
    """
    The share of a panel's area that no blocker shades.

    Parameters
    ----------
    points : ndarray
        The panel's sample points, off its surface, shape (k, 3)
    weights : ndarray
        The area each point stands for, shape (k,)
    blockers : ndarray
        The triangles that may shade it, shape (m, 3, 3)
    sun : ndarray
        The unit vector to the sun, in the same axes, shape (3,)

    Returns
    -------
    lit : float
        From 0 to 1
    """
    flat = _basis(sun)
    projected = points @ flat
    heights = points @ sun
    corners = blockers @ flat
    depths = blockers @ sun

    # a triangle wholly below every point, or outside the points' projected
    # box, cannot block any of their rays
    low, high = projected.min(axis=0), projected.max(axis=0)
    keep = (depths.max(axis=1) > heights.min()) & np.all(
        (corners.max(axis=1) >= low) & (corners.min(axis=1) <= high), axis=1
    )
    if not keep.any():
        return 1.0
    corners, depths = corners[keep], depths[keep]

    origin = corners[:, 0]
    first, second = corners[:, 1] - origin, corners[:, 2] - origin
    det = first[:, 0] * second[:, 1] - first[:, 1] * second[:, 0]
    usable = np.abs(det) > _EDGE_ON
    if not usable.any():
        return 1.0
    origin, first, second = origin[usable], first[usable], second[usable]
    det, depths = det[usable], depths[usable]

    offset = projected[:, None, :] - origin[None]
    s = (offset[..., 0] * second[:, 1] - offset[..., 1] * second[:, 0]) / det
    t = (first[:, 0] * offset[..., 1] - first[:, 1] * offset[..., 0]) / det
    inside = (s >= -EDGE) & (t >= -EDGE) & (s + t <= 1 + EDGE)
    depth = (
        depths[:, 0]
        + s * (depths[:, 1] - depths[:, 0])
        + t * (depths[:, 2] - depths[:, 0])
    )
    blocked = (inside & (depth > heights[:, None])).any(axis=1)
    return float(weights[~blocked].sum() / weights.sum())


def rotation_matrices(axis: np.ndarray, angles: Quantity) -> np.ndarray:
    """
    Right-handed turns about one axis, by each of a series of angles, from Rodrigues'
    formula.

    Parameters
    ----------
    axis : ndarray
        A unit vector, shape (3,)
    angles : Quantity
        The angles, shape (n,)

    Returns
    -------
    rotations : ndarray
        Shape (n, 3, 3)
    """
    angle = np.asarray(angles.to_value(u.rad))
    cross = np.array(
        [[0, -axis[2], axis[1]], [axis[2], 0, -axis[0]], [-axis[1], axis[0], 0]]
    )
    sine, cosine = np.sin(angle)[:, None, None], np.cos(angle)[:, None, None]
    return np.eye(3) + sine * cross + (1 - cosine) * (cross @ cross)


class _Turning:
    """The model's triangles, grouped by the articulations that turn them."""

    def __init__(
        self,
        model: ModelGeometry,
        spacecraft: SpacecraftModel,
        angles: dict[str, Quantity],
    ):
        gltf = read_glb_json(spacecraft.file)
        nodes = {
            name: node_index(gltf, articulation.part)
            for name, articulation in spacecraft.articulations.items()
        }
        # for each part, the articulations above it, from the highest down
        self.joints: dict[int, list[str]] = {}
        for part in model.parts:
            path = [*part.ancestors, part.node]
            above = [name for name, node in nodes.items() if node in path]
            self.joints[part.node] = sorted(
                above, key=lambda name: path.index(nodes[name])
            )
        self.origins = {name: model.origins[node] for name, node in nodes.items()}
        self.rotations = {
            name: rotation_matrices(
                axis_vector(spacecraft.articulations[name].axis), angles[name]
            )
            for name in nodes
        }

    def place(self, triangles: np.ndarray, node: int, step: int) -> np.ndarray:
        """
        A part's triangles or points, turned at a step by its articulations, the lowest
        first.
        """
        for joint in reversed(self.joints[node]):
            origin = self.origins[joint]
            triangles = (triangles - origin) @ self.rotations[joint][step].T + origin
        return triangles


def lit_fractions(
    model: ModelGeometry,
    spacecraft: SpacecraftModel,
    panels: Iterable[tuple[str, int, np.ndarray]],
    points: int,
    suns: np.ndarray,
    cosines: dict[str, np.ndarray],
    light: np.ndarray,
    angles: dict[str, Quantity],
) -> dict[str, np.ndarray]:
    """
    The lit fraction of each panel from the model, at each step.

    Parameters
    ----------
    model : ModelGeometry
        The model's triangles
    spacecraft : SpacecraftModel
        The scenario's model entry, for its articulations
    panels : iterable of tuple
        Each panel's name, its part's node and its normal
    points : int
        About how many sample points on each panel
    suns : ndarray
        The unit vector to the sun in body axes at each step, shape (n, 3)
    cosines : dict of str to ndarray
        Each panel's cosine to the sun, by name
    light : ndarray
        The share of the sun's disk seen at each step
    angles : dict of str to Quantity
        Each articulation's angles

    Returns
    -------
    lit : dict of str to ndarray
        Each panel's lit fraction, from 0 to 1, by name
    """
    turning = _Turning(model, spacecraft, angles)
    lit = {}
    for name, node, normal in panels:
        own = next(part for part in model.parts if part.node == node)
        positions, weights = sample_points(own.triangles, points)
        positions = positions + RAY_OFFSET * normal
        others = [part for part in model.parts if part.node != node]
        fraction = np.ones(len(suns))
        for step in np.flatnonzero((cosines[name] > 0) & (light > 0)).tolist():
            blockers = np.concatenate(
                [turning.place(part.triangles, part.node, step) for part in others]
            )
            fraction[step] = lit_fraction(
                turning.place(positions, node, step), weights, blockers, suns[step]
            )
        lit[name] = fraction
    return lit
