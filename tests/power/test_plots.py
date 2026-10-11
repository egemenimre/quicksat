# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
Tests for the power plots: that they draw, with the lines, the shaded eclipses
and the legends expected. They do not check how the plots look.
"""

import matplotlib.pyplot as plt
import numpy as np
import pytest
from matplotlib.collections import LineCollection
from matplotlib.colors import to_hex

from quicksat import u
from quicksat.power.plots import (
    ECLIPSE,
    MODEL,
    panel_colours,
    panel_drawing,
    panel_power_plot,
    total_power_plot,
)
from quicksat.utils.plot_helpers import PALETTE


@pytest.fixture(autouse=True)  # noqa: V103
def close_figures():
    """Close every figure after each test."""
    yield
    plt.close("all")


def legend_labels(ax):
    """The labels in the axes' legend."""
    return [text.get_text() for text in ax.get_legend().get_texts()]


def test_each_panel_keeps_its_colour(generation_run):
    colours = panel_colours(generation_run)
    assert list(colours) == list(generation_run.power)
    assert list(colours.values()) == list(PALETTE[: len(colours)])


def test_the_panel_plot_draws_a_line_for_each_panel(generation_run):
    ax = panel_power_plot(generation_run)
    lines = ax.get_lines()
    assert [line.get_label() for line in lines] == list(generation_run.power)
    colours = panel_colours(generation_run)
    for line in lines:
        assert to_hex(line.get_color()) == colours[str(line.get_label())]
    np.testing.assert_allclose(
        np.asarray(lines[0].get_ydata()),
        generation_run.power["wing +y inner"].to_value(u.W),
    )
    assert legend_labels(ax) == [*generation_run.power, ECLIPSE]
    # one shaded span for each eclipse in the run
    eclipses = [piece for piece in generation_run.run.eclipses if not piece.empty]
    assert len(ax.patches) == len(eclipses) > 0


def test_the_total_plot_marks_each_orbit_mean(generation_run):
    ax = total_power_plot(generation_run)
    (line,) = ax.get_lines()
    np.testing.assert_allclose(
        np.asarray(line.get_ydata()), generation_run.total.to_value(u.W)
    )
    (means,) = [c for c in ax.collections if isinstance(c, LineCollection)]
    (segment,) = means.get_segments()
    mean = generation_run.orbit_table["mean power [W]"].iloc[0]
    np.testing.assert_allclose(segment[:, 1], [mean, mean])
    assert legend_labels(ax) == ["total", "orbit mean", ECLIPSE]


def test_a_run_shorter_than_an_orbit_has_no_means(short_run):
    ax = total_power_plot(short_run)
    assert legend_labels(ax) == ["total", ECLIPSE]


def test_the_drawing_shows_each_panel_and_the_body_axes(generation_run):
    ax = panel_drawing(generation_run, elev=-30)
    labels = legend_labels(ax)
    assert labels == [*generation_run.power, MODEL]
    # one surface for each part of the model, and an arrow for each panel's
    # normal and each body axis
    assert len(ax.collections) == 16 + len(generation_run.panels) + 3
    assert [text.get_text() for text in ax.texts] == ["x", "y", "z"]


def test_without_a_model_the_drawing_shows_the_typed_in_normals(six_faces_run):
    ax = panel_drawing(six_faces_run)
    assert legend_labels(ax) == list(six_faces_run.panels)
    assert len(ax.collections) == len(six_faces_run.panels) + 3
