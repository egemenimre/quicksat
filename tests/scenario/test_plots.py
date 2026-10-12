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
from matplotlib.colors import to_rgb

from quicksat.scenario.plots import (
    _label,
    gantt_chart,
    ground_track_map,
    scenario_colours,
)
from quicksat.scenario.run import NEGATIVE_DURATION, OUTSIDE_CONSTRAINT
from quicksat.utils.plot_helpers import ILLUMINATION_COLOURS, MUTED, PALETTE


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


def test_the_illumination_runs_from_light_to_dark_and_leaves_the_palette(run):
    colours = scenario_colours(run.scenario)
    lightness = [sum(to_rgb(colours[state])) for state in ILLUMINATION_COLOURS]
    assert lightness == sorted(lightness, reverse=True)
    # the attitudes then start the palette, so ten values still fit eight colours
    assert colours["nadir"] == PALETTE[0]


def test_the_gantt_chart_has_four_rows_and_no_problem_marks(run):
    ax = gantt_chart(run)
    assert [label.get_text() for label in ax.get_yticklabels()] == [
        "mode",
        "activity",
        "attitude",
        "illumination",
    ]
    labels = legend_labels(ax)
    assert OUTSIDE_CONSTRAINT not in labels
    assert NEGATIVE_DURATION not in labels


def test_the_activity_row_names_each_occurrence_by_its_title(run):
    ax = gantt_chart(run)
    # the activity row is the second from the bottom, at y = 1
    labels = {text.get_text() for text in ax.texts if text.get_position()[1] == 1}
    titles = {occurrence.activity.title for occurrence in run.occurrences}
    assert labels
    # each label is a title, or one shortened with an ellipsis
    for label in labels:
        assert label in titles or any(
            label.endswith("…") and title.startswith(label[:-1]) for title in titles
        )
    # the titles take no colour, so they stay out of the legend, unless they are
    # also the name of a mode or an attitude, such as "downlink" here
    named = set(scenario_colours(run.scenario))
    assert not (titles - named) & set(legend_labels(ax))


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


@pytest.mark.parametrize(
    ("width", "label"),
    [
        (100.0, "power generation"),  # fits whole
        (12.0, "power genera…"),  # shortened, ellipsis included
        (5.0, None),  # fewer than six letters fit
    ],
)
def test_a_long_title_is_shortened_to_fit_its_bar(width, label):
    assert _label("power generation", width, span=100.0, size=7) == label
