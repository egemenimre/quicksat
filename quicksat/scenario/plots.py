# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
Plots of a scenario run: the Gantt chart and the ground track maps.

Each returns the matplotlib axes without showing the figure, and each value keeps one
colour from `scenario_colours`.

"""

import matplotlib.pyplot as plt
import numpy as np
import portion as P
from matplotlib.axes import Axes
from matplotlib.collections import LineCollection
from matplotlib.lines import Line2D
from matplotlib.patches import Patch

from quicksat import u
from quicksat.scenario.config import Scenario
from quicksat.scenario.events import NEGATIVE_DURATION, OUTSIDE_CONSTRAINT
from quicksat.scenario.names import GROUPS, PAYLOAD, PLATFORM, SLEW, UNPLANNED
from quicksat.scenario.run import ScenarioRun
from quicksat.utils.intervals import TimeArray, labels_at
from quicksat.utils.plot_helpers import (
    AXIS,
    CRITICAL,
    DIM,
    ILLUMINATION_COLOURS,
    INK,
    MUTED,
    legend_below,
    load_coastlines,
    text_colour,
    value_colours,
)

BAR_HEIGHT = 0.62
"""Height of a Gantt bar, as a fraction of the distance between rows."""

MIN_LETTERS = 6
"""The fewest letters an activity's title is shortened to, ellipsis included."""

TITLE_FILLS = ("#e9e8e2", "#d6d5cd")
"""The two greys that the activity row's bars take in turn."""

LETTER_WIDTH = 0.009
"""The width of one letter of a bar label, as a share of the run's span."""


def scenario_colours(scenario: Scenario) -> dict[str, str]:
    """
    The colour of every value the plots show.

    The illumination has its own slate hues. The attitudes, then the modes, take the
    palette in order. `slew` and `unplanned` are greys.

    Parameters
    ----------
    scenario : Scenario
        The scenario

    Returns
    -------
    colours : dict
        Each value's colour, as a hex string
    """
    attitudes = list(scenario.attitudes)
    modes = [
        activity.mode[group] for group in GROUPS for activity in scenario.activities
    ]
    colours = value_colours([*attitudes, *modes])
    # the slew and the unplanned time sit after the attitudes, in the order the
    # legends show the values
    ordered = dict(ILLUMINATION_COLOURS) | {
        value: colours[value] for value in attitudes
    }
    ordered[SLEW] = MUTED
    ordered[UNPLANNED] = DIM
    return ordered | {value: colours[value] for value in modes}


def _label(value: str, width: float, span: float, size: float) -> str | None:
    """
    A bar's label, whole, shortened with an ellipsis to at least `MIN_LETTERS`, or None
    if it does not fit.
    """
    letters = int((width / span - 0.01) / (LETTER_WIDTH * size / 8))
    if letters >= len(value):
        return value
    if letters >= MIN_LETTERS:
        return value[: letters - 1].rstrip() + "…"
    return None


def _draw_row(
    ax: Axes,
    y: float,
    pieces: list[tuple[float, float, str]],
    fills: list[str],
    span: float,
    shorten: bool = False,
) -> None:
    """One row of the Gantt chart: its bars, and their labels where they fit."""
    ax.broken_barh(
        [(left, right - left) for left, right, _ in pieces],
        (y - BAR_HEIGHT / 2, BAR_HEIGHT),
        facecolors=fills,
        edgecolor="white",
    )
    size = 7 if shorten else 8
    for (left, right, value), fill in zip(pieces, fills, strict=True):
        label = _label(value, right - left, span, size)
        if label is None or (label != value and not shorten):
            continue
        ax.text(
            (left + right) / 2,
            y,
            label,
            ha="center",
            va="center",
            fontsize=size,
            color=text_colour(fill),
        )


def gantt_chart(  # noqa: V103
    run: ScenarioRun, colours: dict[str, str] | None = None, ax: Axes | None = None
) -> Axes:
    """
    The illumination, the attitude, the activity, and the modes against time, as a Gantt
    chart.

    A red box marks an occurrence outside its constraint, and a dashed red line one with
    a negative duration.

    Parameters
    ----------
    run : ScenarioRun
        The run
    colours : dict, optional
        Each value's colour, by default `scenario_colours`
    ax : Axes, optional
        The axes to draw on, by default a new figure

    Returns
    -------
    ax : Axes
        The axes drawn on
    """
    colours = colours or scenario_colours(run.scenario)
    if ax is None:
        _, ax = plt.subplots(figsize=(10, 5))
    start: TimeArray = run.times[0]

    def minutes(time: TimeArray) -> float:
        return float((time - start).to_value(u.min))

    def pieces_of(row: P.IntervalDict) -> list[tuple[float, float, str]]:
        return [
            (minutes(piece.lower), minutes(piece.upper), value)
            for interval, value in row.items()
            for piece in interval
        ]

    span = minutes(run.times[-1])
    # each occurrence is a bar of its own, so that two in a row with the same
    # title stay apart; they take two greys in turn, since titles have no colour
    titles = [
        (minutes(occurrence.start), minutes(occurrence.end), occurrence.activity.title)
        for occurrence in run.occurrences
        if occurrence.end > occurrence.start
    ]
    # from the bottom up, so that the illumination is the top row
    rows = {
        "platform mode": pieces_of(run.mode[PLATFORM]),
        "payload mode": pieces_of(run.mode[PAYLOAD]),
        "activity": titles,
        "attitude": pieces_of(run.attitude),
        "illumination": pieces_of(run.illumination),
    }
    for y, (name, pieces) in enumerate(rows.items()):
        fills = (
            [TITLE_FILLS[k % 2] for k in range(len(pieces))]
            if name == "activity"
            else [colours[value] for _, _, value in pieces]
        )
        _draw_row(ax, y, pieces, fills, span, shorten=name == "activity")

    failed = [occurrence for occurrence in run.occurrences if occurrence.failed]
    if failed:
        ax.broken_barh(
            [(minutes(o.start), minutes(o.end) - minutes(o.start)) for o in failed],
            (-0.45, len(rows) - 0.1),
            facecolors="none",
            edgecolors=CRITICAL,
            linewidth=2,
        )

    early = [
        occurrence for occurrence in run.occurrences if occurrence.negative_duration
    ]
    if early:
        # The next activity starts at the same time, so the line runs past any
        # red box drawn there, and a triangle on top keeps it visible
        starts = [minutes(occurrence.start) for occurrence in early]
        ax.vlines(
            starts,
            -0.6,
            len(rows) - 0.4,
            colors=CRITICAL,
            linestyles="dashed",
            linewidth=2,
            zorder=4,
        )
        ax.plot(
            starts,
            [len(rows) - 0.4] * len(starts),
            linestyle="none",
            marker="v",
            markersize=9,
            color=CRITICAL,
            clip_on=False,
            zorder=4,
        )

    ax.set_yticks(range(len(rows)), labels=list(rows))
    ax.grid(axis="y", visible=False)
    ax.set(
        xlim=(0, span),
        ylim=(-0.6, len(rows) - 0.4),
        xlabel="Minutes from the start of the run",
        title="Illumination, attitude, activity and modes",
    )
    shown = {
        value
        for name, pieces in rows.items()
        if name != "activity"
        for _, _, value in pieces
    }
    problems = []
    if failed:
        problems.append(
            Patch(fill=False, edgecolor=CRITICAL, linewidth=2, label=OUTSIDE_CONSTRAINT)
        )
    if early:
        problems.append(
            Line2D(
                [],
                [],
                color=CRITICAL,
                linestyle="--",
                linewidth=2,
                marker="v",
                label=NEGATIVE_DURATION,
            )
        )
    legend_below(
        ax,
        {value: colour for value, colour in colours.items() if value in shown},
        problems,
    )
    return ax


def ground_track_map(  # noqa: V103
    run: ScenarioRun,
    row: P.IntervalDict,
    title: str,
    colours: dict[str, str] | None = None,
    ax: Axes | None = None,
) -> Axes:
    """
    The ground track over the coastlines, coloured by a Gantt row, from a circle at the
    start to a square at the end.

    Parameters
    ----------
    run : ScenarioRun
        The run
    row : portion.IntervalDict
        The row that colours the track, such as `run.mode["payload"]`
    title : str
        The map's title
    colours : dict, optional
        Each value's colour, by default `scenario_colours`
    ax : Axes, optional
        The axes to draw on, by default a new figure

    Returns
    -------
    ax : Axes
        The axes drawn on
    """
    colours = colours or scenario_colours(run.scenario)
    if ax is None:
        _, ax = plt.subplots(figsize=(10, 5.6))
    ax.add_collection(LineCollection(load_coastlines(), colors=AXIS, linewidths=0.8))

    track = np.column_stack(
        [run.longitude.to_value(u.deg), run.latitude.to_value(u.deg)]
    )
    keep = np.abs(np.diff(track[:, 0])) < 180
    values = labels_at(row, run.times)[:-1][keep]
    segments = np.stack([track[:-1], track[1:]], axis=1)[keep]
    ax.add_collection(
        LineCollection(
            list(segments), colors=[colours[value] for value in values], linewidths=2.2
        )
    )
    for (longitude, latitude), marker, label in (
        (track[0], "o", "start"),
        (track[-1], "s", "end"),
    ):
        ax.scatter(
            longitude,
            latitude,
            s=60,
            marker=marker,
            color=INK,
            edgecolor="white",
            linewidth=1.5,
            zorder=3,
            label=label,
        )

    ax.set(
        xlim=(-180, 180),
        ylim=(-90, 90),
        aspect="equal",
        xticks=range(-180, 181, 60),
        yticks=range(-90, 91, 30),
        xlabel="Longitude [deg]",
        ylabel="Latitude [deg]",
        title=title,
    )
    markers, _ = ax.get_legend_handles_labels()
    shown = set(values)
    legend_below(
        ax,
        {value: colour for value, colour in colours.items() if value in shown},
        markers,
    )
    return ax
