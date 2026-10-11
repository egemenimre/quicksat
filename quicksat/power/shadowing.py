# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
Self-shadowing: the parts of the 3D model that shade the solar panels.

Each panel from the model gets sample points on its cells, each standing for an
equal share of its area. At each step, a ray goes from each point toward the
sun, in body axes. A point is shaded when a triangle of another part blocks its
ray. A panel's lit fraction is the share of its area whose points are not
shaded.

All rays at one step share the sun's direction. So the model is projected along
that direction onto a plane, once a step. A point is shaded when its projection
falls inside a projected triangle that lies further toward the sun. This is the
Möller-Trumbore test, arranged for one direction.

Parts under an articulation turn with it at each step, so a turning wing both
casts its shadow and catches others' where its angle puts it.

No ray is cast where it cannot change the power: while the panel faces away from
the sun, or in the umbra. The lit fraction is 1 there. A triangle is left out of
the test when it lies wholly behind the panel's points, or when its projection
misses theirs.

Two kinds of noise come from ray tests, and both are handled, as the prototype
found:

- A ray can hit the surface it starts on, through rounding. Each ray starts
  `RAY_OFFSET` off the cells, along their normal.
- A shadow first touches a panel at a corner, and its area grows slowly from
  there, so the first point is covered late. Times of shading are counted only
  where more than `SHADED_LIMIT` of a panel is shaded.

Strings of cells are not modelled. A shaded area costs only its share of the
panel's power, although a real string loses more.

"""

from collections.abc import Iterable

import numpy as np
from astropy.units import Quantity

from quicksat import u
from quicksat.orbit.attitude import axis_vector
from quicksat.scenario.config import SpacecraftModel
from quicksat.scenario.spacecraft import ModelGeometry, node_index, read_glb_json

RAY_OFFSET = 1e-6
"""How far off the cells each ray starts, along their normal, in metres. In the
prototype, 1 nm or more removed every self-hit down to 0.001 deg above the
panel's plane."""

EDGE = 1e-9
"""Tolerance on the barycentric test. A ray through the shared edge of two
triangles counts as a hit, so that no ray slips through a seam."""

SHADED_LIMIT = 0.01
"""A panel counts as shaded while more than this share of it is shaded. Any
shading at all would start late and end early, by up to 7 steps in the prototype
at 512 points."""

_EDGE_ON = 1e-14
"""Below this projected area, twice over, a triangle is edge-on to the sun and
casts no area. Its neighbours cast the shadow."""


def sample_points(triangles: np.ndarray, points: int) -> tuple[np.ndarray, np.ndarray]:
    """
    Points on the triangles, each standing for an equal share of its triangle.

    Each triangle is cut into n² equal smaller ones, with n chosen from the
    triangle's share of the area, so that the total is close to `points`. The
    points are the centres of the smaller triangles.

    Parameters
    ----------
    triangles : ndarray
        The corners, shape (m, 3, 3)
    points : int
        About how many points to place in all

    Returns
    -------
    positions : ndarray
        The points, shape (k, 3)
    areas : ndarray
        The area each point stands for, shape (k,)
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
        The panel's sample points, shape (k, 3), already off its surface
    weights : ndarray
        The area each point stands for, shape (k,)
    blockers : ndarray
        The triangles that may shade it, shape (m, 3, 3)
    sun : ndarray
        The unit vector to the sun, shape (3,), in the same axes

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
    Right-handed turns about one axis, by each of a series of angles.

    Parameters
    ----------
    axis : ndarray
        A unit vector, shape (3,)
    angles : Quantity
        The angles, shape (n,)

    Returns
    -------
    rotations : ndarray
        Shape (n, 3, 3), from Rodrigues' formula
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
        Triangles or points of a part, turned by its articulations at a step.

        The lowest articulation turns first, then each one above it, as the
        viewer draws them.
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
        The model's triangles, as the model draws them
    spacecraft : SpacecraftModel
        The scenario's model entry, for its articulations
    panels : iterable of tuple
        Each panel's name, the index of its part's node, and its normal as the
        model draws it
    points : int
        About how many sample points to place on each panel
    suns : ndarray
        The unit vector to the sun in body axes at each step, shape (n, 3)
    cosines : dict of str to ndarray
        Each panel's cosine to the sun at each step, by its name
    light : ndarray
        The fraction of the sun's disk seen at each step
    angles : dict of str to Quantity
        Each articulation's angle at each step

    Returns
    -------
    lit : dict of str to ndarray
        Each panel's lit fraction at each step, from 0 to 1, by its name
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
