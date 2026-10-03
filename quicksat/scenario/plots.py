# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
Plots of a scenario run: the Gantt chart and the ground track maps.

Each plot draws from a `ScenarioRun` and returns the matplotlib axes, without
showing the figure. So a notebook can add to a plot before showing it. Apply
`quicksat.utils.plot_helpers.STYLE` first for quicksat's look.

Each value keeps one colour in every plot, from `scenario_colours`.

"""

import matplotlib.pyplot as plt
import numpy as np
import portion as P
from matplotlib.axes import Axes
from matplotlib.collections import LineCollection
from matplotlib.patches import Patch

from quicksat import u
from quicksat.scenario.config import Scenario
from quicksat.scenario.run import OUTSIDE_CONSTRAINT, ScenarioRun
from quicksat.utils.intervals import TimeArray, labels_at
from quicksat.utils.plot_helpers import (
    AXIS,
    CRITICAL,
    INK,
    legend_below,
    load_coastlines,
    text_colour,
    value_colours,
)

BAR_HEIGHT = 0.62
"""Height of a Gantt bar, as a fraction of the distance between rows."""

LETTER_WIDTH = 0.009
"""Width of one letter of a bar label, as a fraction of the run's span. A label
goes in only where its bar is wide enough to hold it."""


def scenario_colours(scenario: Scenario) -> dict[str, str]:
    """
    The colour of every value the plots show.

    The values take the colours in a fixed order: the illumination first, then
    the attitudes, then the modes in the order the activities name them.

    Parameters
    ----------
    scenario : Scenario
        The scenario

    Returns
    -------
    colours : dict
        The colour of each value, as a hex string
    """
    return value_colours(
        [
            "sunlit",
            "eclipse",
            *scenario.attitudes.names,
            *(activity.mode for activity in scenario.activities),
        ]
    )


def gantt_chart(  # noqa: V103
    run: ScenarioRun, colours: dict[str, str] | None = None, ax: Axes | None = None
) -> Axes:
    """
    The illumination, the attitude and the mode against time, as a Gantt chart.

    Each row is drawn in one call to `broken_barh`. A bar carries its value as a
    label when it is wide enough. A red box marks every occurrence that spends
    time outside its constraint.

    Parameters
    ----------
    run : ScenarioRun
        The run to draw
    colours : dict, optional
        The colour of each value. `scenario_colours` by default.
    ax : Axes, optional
        The axes to draw on. A new figure by default.

    Returns
    -------
    ax : Axes
        The axes drawn on
    """
    colours = colours or scenario_colours(run.scenario)
    if ax is None:
        _, ax = plt.subplots(figsize=(10, 3.4))
    start: TimeArray = run.times[0]

    def minutes(time: TimeArray) -> float:
        return float((time - start).to_value(u.min))

    span = minutes(run.times[-1])
    # from the bottom up, so that the illumination is the top row
    rows = {
        "mode": run.mode,
        "attitude": run.attitude,
        "illumination": run.illumination,
    }
    for y, row in enumerate(rows.values()):
        pieces = [
            (minutes(piece.lower), minutes(piece.upper), value)
            for interval, value in row.items()
            for piece in interval
        ]
        ax.broken_barh(
            [(left, right - left) for left, right, _ in pieces],
            (y - BAR_HEIGHT / 2, BAR_HEIGHT),
            facecolors=[colours[value] for _, _, value in pieces],
            edgecolor="white",
        )
        for left, right, value in pieces:
            if right - left > (LETTER_WIDTH * len(value) + 0.01) * span:
                ax.text(
                    (left + right) / 2,
                    y,
                    value,
                    ha="center",
                    va="center",
                    fontsize=8,
                    color=text_colour(colours[value]),
                )

    failed = [occurrence for occurrence in run.occurrences if occurrence.failed]
    if failed:
        ax.broken_barh(
            [(minutes(o.start), minutes(o.end) - minutes(o.start)) for o in failed],
            (-0.45, len(rows) - 0.1),
            facecolors="none",
            edgecolors=CRITICAL,
            linewidth=2,
        )

    ax.set_yticks(range(len(rows)), labels=list(rows))
    ax.grid(axis="y", visible=False)
    ax.set(
        xlim=(0, span),
        ylim=(-0.6, len(rows) - 0.4),
        xlabel="Minutes from the start of the run",
        title="Illumination, attitude and mode",
    )
    shown = {value for row in rows.values() for value in row.values()}
    outside = Patch(
        fill=False, edgecolor=CRITICAL, linewidth=2, label=OUTSIDE_CONSTRAINT
    )
    legend_below(
        ax,
        {value: colour for value, colour in colours.items() if value in shown},
        [outside] if failed else [],
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
    The ground track over the coastlines, coloured by the value of a Gantt row.

    The track is drawn as segments between the grid steps. Each segment takes
    the value at its first step. The segment that jumps where the longitude wraps
    at +-180 degrees is left out. A circle marks the start of the run, and a
    square its end.

    Parameters
    ----------
    run : ScenarioRun
        The run to draw
    row : portion.IntervalDict
        The Gantt row that colours the track, such as `run.mode`
    title : str
        Title of the map
    colours : dict, optional
        The colour of each value. `scenario_colours` by default.
    ax : Axes, optional
        The axes to draw on. A new figure by default.

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
