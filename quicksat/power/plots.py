# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
Plots of the power generation: the panels in 3D, each panel's power, and the
total.

Each plot draws from a `GenerationRun` and returns the matplotlib axes, without
showing the figure. So a notebook can add to a plot before showing it. Apply
`quicksat.utils.plot_helpers.STYLE` first for quicksat's look.

The power plots shade the eclipses. Each panel keeps one colour in every plot,
from `panel_colours`.

"""

from typing import cast

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.axes import Axes
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
from mpl_toolkits.mplot3d.art3d import Poly3DCollection
from mpl_toolkits.mplot3d.axes3d import Axes3D

from quicksat import u
from quicksat.power.generation import GenerationRun
from quicksat.scenario.spacecraft import read_model
from quicksat.utils.plot_helpers import (
    AXIS,
    ILLUMINATION_COLOURS,
    PALETTE,
    SECONDARY,
    value_colours,
)

MODEL = "rest of the model"
"""The legend's name for the parts of the model that are not panels."""

ECLIPSE = "eclipse"
"""The legend's name for the shaded eclipses."""

ECLIPSE_ALPHA = 0.18
"""How strongly the eclipses are shaded, so that the lines stay on top."""


def panel_colours(generation_run: GenerationRun) -> dict[str, str]:
    """
    The colour of each panel, in the order of the power generation file.

    Parameters
    ----------
    generation_run : GenerationRun
        The generation

    Returns
    -------
    colours : dict
        The colour of each panel, as a hex string
    """
    return value_colours(generation_run.power)


def _minutes(generation_run: GenerationRun) -> np.ndarray:
    """The run's grid, in minutes from its start."""
    run = generation_run.run
    return np.asarray((run.times - run.times[0]).to_value(u.min))


def _shade_eclipses(ax: Axes, generation_run: GenerationRun) -> Patch:
    """Shades each eclipse on the axes, and gives the legend's entry for them."""
    run = generation_run.run
    colour = ILLUMINATION_COLOURS["umbra"]
    for piece in run.eclipses:
        if piece.empty:
            continue
        ax.axvspan(
            float((piece.lower - run.times[0]).to_value(u.min)),
            float((piece.upper - run.times[0]).to_value(u.min)),
            color=colour,
            alpha=ECLIPSE_ALPHA,
            linewidth=0,
        )
    return Patch(color=colour, alpha=ECLIPSE_ALPHA, label=ECLIPSE)


def _finish(ax: Axes, minutes: np.ndarray, title: str, handles: list) -> None:
    """The limits, the labels and the legend below the plot."""
    ax.set(
        xlim=(0, minutes[-1]),
        ylim=(0, None),
        xlabel="Minutes from the start of the run",
        ylabel="Power [W]",
        title=title,
    )
    ax.legend(
        handles=handles,
        loc="upper center",
        bbox_to_anchor=(0.5, -0.18),
        ncol=min(len(handles), 4),
    )


def panel_power_plot(
    generation_run: GenerationRun,
    colours: dict[str, str] | None = None,
    ax: Axes | None = None,
) -> Axes:
    """
    The power of each panel against time.

    Panels that see the sun alike, such as the two panels of a wing, draw one
    line over the other.

    Parameters
    ----------
    generation_run : GenerationRun
        The generation
    colours : dict, optional
        The colour of each panel. `panel_colours` by default.
    ax : Axes, optional
        The axes to draw on. A new figure by default.

    Returns
    -------
    ax : Axes
        The axes drawn on
    """
    colours = colours or panel_colours(generation_run)
    if ax is None:
        _, ax = plt.subplots(figsize=(10, 3.8))
    minutes = _minutes(generation_run)
    handles: list = []
    for name, power in generation_run.power.items():
        (line,) = ax.plot(
            minutes, power.to_value(u.W), color=colours[name], linewidth=2, label=name
        )
        handles.append(line)
    handles.append(_shade_eclipses(ax, generation_run))
    _finish(ax, minutes, "Power of each panel", handles)
    return ax


def total_power_plot(generation_run: GenerationRun, ax: Axes | None = None) -> Axes:
    """
    The power of all the panels together against time, with each orbit's mean.

    The orbits are counted from the start of the run, one period each, as in
    `GenerationRun.orbit_table`. A dashed line spans each whole orbit at its mean
    power.

    Parameters
    ----------
    generation_run : GenerationRun
        The generation
    ax : Axes, optional
        The axes to draw on. A new figure by default.

    Returns
    -------
    ax : Axes
        The axes drawn on
    """
    if ax is None:
        _, ax = plt.subplots(figsize=(10, 3.8))
    minutes = _minutes(generation_run)
    (line,) = ax.plot(
        minutes,
        generation_run.total.to_value(u.W),
        color=PALETTE[0],
        linewidth=2,
        label="total",
    )
    handles: list = [line]
    table = generation_run.orbit_table
    if not table.empty:
        for (start, end), mean in zip(
            generation_run.orbits, table["mean power [W]"], strict=True
        ):
            ax.hlines(
                mean, start / 60, end / 60, colors=SECONDARY, linestyles="--", lw=1.5
            )
        handles.append(
            Line2D([], [], color=SECONDARY, linestyle="--", lw=1.5, label="orbit mean")
        )
    handles.append(_shade_eclipses(ax, generation_run))
    _finish(ax, minutes, "Power of all the panels", handles)
    return ax


def _centre(triangles: np.ndarray) -> np.ndarray:
    """The area-weighted centre of a set of triangles."""
    areas = np.linalg.norm(
        np.cross(triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0]),
        axis=1,
    )
    return (triangles.mean(axis=1) * areas[:, None]).sum(axis=0) / areas.sum()


def panel_drawing(
    generation_run: GenerationRun,
    colours: dict[str, str] | None = None,
    ax: Axes3D | None = None,
    elev: float = 25,
    azim: float = -60,
) -> Axes3D:
    """
    The panels and their normals in body axes, as a still 3D drawing.

    The model is drawn as it is, with each wing at an angle of zero. The panels
    from the model take their colours, and the rest of the model is grey. An
    arrow from the middle of each panel shows its normal. A typed-in panel has
    no shape, so its normal starts at the origin. The body axes are drawn from
    the origin, each half the model's reach long. The viewer shows the
    model turning over the run.

    Parameters
    ----------
    generation_run : GenerationRun
        The generation
    colours : dict, optional
        The colour of each panel. `panel_colours` by default.
    ax : Axes3D, optional
        3D axes to draw on. A new figure by default.
    elev, azim : float, optional
        The view's elevation and azimuth, in degrees, as matplotlib takes them.
        A negative elevation looks from below the x-y plane, from -z.

    Returns
    -------
    ax : Axes3D
        The 3D axes drawn on
    """
    colours = colours or panel_colours(generation_run)
    if ax is None:
        ax = cast(Axes3D, plt.figure(figsize=(8, 5.5)).add_subplot(projection="3d"))
    spacecraft = generation_run.run.scenario.spacecraft_model
    parts = read_model(spacecraft.file).parts if spacecraft is not None else []
    panel_of = {
        panel.node: name
        for name, panel in generation_run.panels.items()
        if panel.node is not None
    }
    corners = np.concatenate(
        [part.triangles.reshape(-1, 3) for part in parts] or [np.zeros((1, 3))]
    )
    reach = max(float(np.abs(corners).max()), 0.5)

    for part in parts:
        name = panel_of.get(part.node)
        ax.add_collection3d(
            Poly3DCollection(
                list(part.triangles),
                facecolor=colours[name] if name else AXIS,
                edgecolor="none",
                alpha=1.0 if name else 0.35,
            )
        )
    # every point drawn, so that the view fits them all at one scale
    drawn = [corners]
    length = 0.25 * reach
    for name, panel in generation_run.panels.items():
        part = next((part for part in parts if part.node == panel.node), None)
        start = _centre(part.triangles) if part is not None else np.zeros(3)
        ax.quiver(
            *start,
            *(panel.normal * length),
            color=colours[name],
            linewidth=2,
            arrow_length_ratio=0.2,
        )
        drawn.append(start + panel.normal * length)
    for index, label in enumerate("xyz"):
        tip = np.zeros(3)
        tip[index] = 0.5 * reach
        ax.quiver(
            0, 0, 0, *tip, color=SECONDARY, linewidth=1.2, arrow_length_ratio=0.15
        )
        x, y, z = tip * 1.1
        ax.text(x, y, z, label, color=SECONDARY)
        drawn.append(tip * 1.1)

    points = np.vstack(drawn)
    low, high = points.min(axis=0), points.max(axis=0)
    margin = 0.05 * reach
    ax.set(
        xlim=(low[0] - margin, high[0] + margin),
        ylim=(low[1] - margin, high[1] + margin),
        zlim=(low[2] - margin, high[2] + margin),
    )
    # the body axes are drawn as arrows, so the box, its grid and its ticks go
    ax.set_axis_off()
    ax.set_title("The panels and their normals, in body axes")
    ax.set_box_aspect(tuple(high - low + 2 * margin))
    ax.view_init(elev=elev, azim=azim)
    handles = [Patch(color=colours[name], label=name) for name in generation_run.panels]
    if len(panel_of) < len(parts):
        handles.append(Patch(color=AXIS, alpha=0.35, label=MODEL))
    ax.legend(handles=handles, loc="upper center", bbox_to_anchor=(0.5, 0.02), ncol=3)
    return ax
