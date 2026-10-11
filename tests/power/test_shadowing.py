# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
Tests for the self-shadowing: the sample points, the ray test against shadows of
known size, the two kinds of noise, and the shading over a run.
"""

import numpy as np
import pytest

from quicksat import Q_, u
from quicksat.power.config import PowerGeneration
from quicksat.power.generation import run_generation, turned_normals
from quicksat.power.shadowing import (
    RAY_OFFSET,
    SHADED_LIMIT,
    lit_fraction,
    rotation_matrices,
    sample_points,
)


def square(x0: float, x1: float, y0: float, y1: float, z: float) -> np.ndarray:
    """A rectangle in a plane of constant z, as two triangles facing +z."""
    a, b, c, d = (x0, y0, z), (x1, y0, z), (x1, y1, z), (x0, y1, z)
    return np.array([[a, b, c], [a, c, d]], dtype=float)


PANEL = square(0, 1, 0, 1, 0)
"""A 1 m2 panel in the x-y plane, facing +z."""


@pytest.fixture(scope="module")
def panel_points():
    """512 points on the panel, just above it."""
    points, weights = sample_points(PANEL, 512)
    return points + RAY_OFFSET * np.array([0, 0, 1]), weights


def sun_towards(shift: float) -> np.ndarray:
    """The sun above the x-z plane, so that a height of 1 moves a shadow by `shift`
    along +x."""
    sun = np.array([-shift, 0.0, 1.0])
    return sun / np.linalg.norm(sun)


def test_the_points_share_the_area_evenly():
    points, weights = sample_points(PANEL, 512)
    assert len(points) == 512
    assert weights.sum() == pytest.approx(1.0)
    np.testing.assert_allclose(weights, 1 / 512)
    assert points[:, :2].min() > 0 and points[:, :2].max() < 1
    # a triangle with a larger share of the area gets more points
    uneven = np.array(
        [[[0, 0, 0], [3, 0, 0], [0, 3, 0]], [[0, 0, 0], [1, 0, 0], [0, 1, 0]]]
    )
    points, weights = sample_points(uneven.astype(float), 200)
    assert weights.sum() == pytest.approx(5.0)
    assert 150 < len(points) < 250


@pytest.mark.parametrize(
    ("shift", "lit"),
    [
        (0.0, 0.5),  # straight overhead: the blocker covers x from 0 to 0.5
        (0.5, 0.5),  # the shadow moves to x from 0.5 to 1
        (0.75, 0.75),  # a quarter of the shadow falls off the panel
        (1.25, 1.0),  # the whole shadow falls off the panel
        (-0.25, 0.75),  # the other way, a quarter falls off at x = 0
    ],
)
def test_a_shadow_covers_the_area_it_should(panel_points, shift, lit):
    blocker = square(0, 0.5, -1, 2, 1.0)
    points, weights = panel_points
    found = lit_fraction(points, weights, blocker, sun_towards(shift))
    # 512 points place an edge to within about 1/sqrt(512) of the panel's side
    assert found == pytest.approx(lit, abs=0.03)


def test_a_blocker_behind_the_panel_casts_no_shadow(panel_points):
    points, weights = panel_points
    below = square(-1, 2, -1, 2, -0.1)
    assert lit_fraction(points, weights, below, sun_towards(0.3)) == 1.0


def test_a_panel_flush_on_a_box_does_not_shade_itself(panel_points):
    # the box's top face lies in the panel's plane, as cells on a wing do. A ray
    # from the panel's surface would hit it through rounding, at low sun.
    box_top = square(-0.5, 1.5, -0.5, 1.5, 0.0)
    points, weights = panel_points
    for elevation in (30.0, 1.0, 0.01, 0.001):
        sun = np.array(
            [np.cos(np.radians(elevation)), 0.0, np.sin(np.radians(elevation))]
        )
        assert lit_fraction(points, weights, box_top, sun) == 1.0


def test_the_turns_match_the_turned_normals():
    axis = np.array([0.0, 1.0, 0.0])
    normal = np.array([0.0, 0.0, -1.0])
    angles = Q_([-170, -30, 0, 45, 120], "deg")
    np.testing.assert_allclose(
        rotation_matrices(axis, angles) @ normal,
        turned_normals(normal, axis, angles),
        atol=1e-15,
    )


# -------------------------------------------------------------------- the run


@pytest.fixture(scope="module")
def shaded_run(data_dir, model_run):
    """`power_generation.yaml` with the self-shadowing on, over `model_run`."""
    text = (data_dir / "power_generation.yaml").read_text()
    generation = PowerGeneration.from_yaml_text(
        text + "self_shadowing: {enabled: true, points: 128}\n"
    )
    return run_generation(generation, model_run)


def test_the_housing_shades_the_deck_cells(shaded_run, model_run):
    deck = shaded_run.lit["deck"]
    assert deck.min() < 0.5
    facing = (shaded_run.cosines["deck"] > 0) & (model_run.light > 0)
    # no ray is cast where it cannot change the power
    assert np.all(deck[~facing] == 1)
    assert np.all(shaded_run.lit["side +x"] == 1)
    np.testing.assert_allclose(
        shaded_run.power["deck"].to_value(u.W),
        shaded_run.unshaded["deck"].to_value(u.W) * deck,
    )


def test_the_shading_table_lists_the_panels_from_the_model(shaded_run, generation_run):
    table = shaded_run.shading_table
    assert list(table["panel"]) == [
        "wing +y inner",
        "wing +y outer",
        "wing -y inner",
        "wing -y outer",
        "deck",
    ]
    deck = table.set_index("panel").loc["deck"]
    assert deck["lowest lit fraction"] == pytest.approx(shaded_run.lit["deck"].min())
    assert deck["shaded [min]"] > 0
    assert 0 < deck["energy lost [%]"] < 100
    # the loss is the energy between the unshaded and the shaded power
    seconds = np.asarray((shaded_run.run.times - shaded_run.run.times[0]).to_value(u.s))
    lost = np.trapezoid(
        (shaded_run.unshaded["deck"] - shaded_run.power["deck"]).to_value(u.W), seconds
    )
    assert deck["energy lost [Wh]"] == pytest.approx(lost / 3600, rel=1e-9)
    # a panel counts as shaded only past the limit
    lit = shaded_run.lit["deck"][:-1]
    steps = np.diff(seconds)
    assert deck["shaded [min]"] == pytest.approx(
        steps[lit < 1 - SHADED_LIMIT].sum() / 60
    )
    assert generation_run.shading_table.empty
