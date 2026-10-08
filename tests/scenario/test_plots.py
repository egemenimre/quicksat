# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
Tests for the plots of a run: that they draw, with the rows, the problem marks
and the legends expected. They do not check how the plots look.
"""

import matplotlib.pyplot as plt
import pytest

from quicksat.scenario.plots import gantt_chart, ground_track_map, scenario_colours
from quicksat.scenario.run import NEGATIVE_DURATION, OUTSIDE_CONSTRAINT
from quicksat.utils.plot_helpers import MUTED


@pytest.fixture(autouse=True)  # noqa: V103
def close_figures():
    """Close every figure after each test."""
    yield
    plt.close("all")


def legend_labels(ax):
    """The labels in the axes' legend."""
    legend = ax.get_legend()
    return [text.get_text() for text in legend.get_texts()] if legend else []


def test_each_value_has_one_colour(run):
    colours = scenario_colours(run.scenario)
    assert list(colours)[:6] == [
        "sunlit",
        "penumbra",
        "umbra",
        "nadir",
        "sun pointing",
        "slew",
    ]
    # the slew is grey, outside the palette, so the modes keep their colours
    assert colours["slew"] == MUTED
    assert {"idle", "imaging", "downlink"} <= set(colours)
    assert len(set(colours.values())) == len(colours)


def test_the_gantt_chart_has_three_rows_and_no_problem_marks(run):
    ax = gantt_chart(run)
    assert [label.get_text() for label in ax.get_yticklabels()] == [
        "mode",
        "attitude",
        "illumination",
    ]
    labels = legend_labels(ax)
    assert OUTSIDE_CONSTRAINT not in labels
    assert NEGATIVE_DURATION not in labels


def test_the_gantt_chart_marks_each_kind_of_problem(problem_run):
    labels = legend_labels(gantt_chart(problem_run))
    assert OUTSIDE_CONSTRAINT in labels
    assert NEGATIVE_DURATION in labels


def test_the_ground_track_map_spans_the_earth(run):
    ax = ground_track_map(run, run.mode, "By mode")
    assert ax.get_xlim() == (-180, 180)
    assert ax.get_ylim() == (-90, 90)
    labels = legend_labels(ax)
    assert {"idle", "imaging", "downlink", "start", "end"} <= set(labels)
