# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
Plots of power: the panels in 3D, the panels' power, the loads by subsystem, the balance
and the battery's charge.

Each returns the matplotlib axes without showing the figure. The power plots shade the
eclipses, and each panel keeps one colour from `panel_colours`.

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
from quicksat.power.budget import BudgetRun
from quicksat.power.consumption import ConsumptionRun
from quicksat.power.generation import GenerationRun
from quicksat.scenario.run import ScenarioRun
from quicksat.scenario.spacecraft import read_model
from quicksat.utils.plot_helpers import (
    AXIS,
    CRITICAL,
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
"""How strongly the eclipses are shaded, under the lines."""


def panel_colours(generation_run: GenerationRun) -> dict[str, str]:
    """
    The colour of each panel, in the power system file's order.

    Parameters
    ----------
    generation_run : GenerationRun
        The generation

    Returns
    -------
    colours : dict
        Each panel's colour, as a hex string
    """
    return value_colours(generation_run.power)


def _minutes(run: ScenarioRun) -> np.ndarray:
    """The run's grid, in minutes from its start."""
    return np.asarray((run.times - run.times[0]).to_value(u.min))


def _shade_eclipses(ax: Axes, run: ScenarioRun) -> Patch:
    """Shades each eclipse, and gives the legend's entry."""
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
            zorder=0,
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

    Parameters
    ----------
    generation_run : GenerationRun
        The generation
    colours : dict, optional
        Each panel's colour, by default `panel_colours`
    ax : Axes, optional
        The axes to draw on, by default a new figure

    Returns
    -------
    ax : Axes
        The axes drawn on
    """
    colours = colours or panel_colours(generation_run)
    if ax is None:
        _, ax = plt.subplots(figsize=(10, 3.8))
    minutes = _minutes(generation_run.run)
    handles: list = []
    for name, power in generation_run.power.items():
        (line,) = ax.plot(
            minutes, power.to_value(u.W), color=colours[name], linewidth=2, label=name
        )
        handles.append(line)
    handles.append(_shade_eclipses(ax, generation_run.run))
    _finish(ax, minutes, "Power of each panel", handles)
    return ax


def total_power_plot(generation_run: GenerationRun, ax: Axes | None = None) -> Axes:
    """
    The power of all the panels against time, with a dashed line at each whole orbit's
    mean.

    Parameters
    ----------
    generation_run : GenerationRun
        The generation
    ax : Axes, optional
        The axes to draw on, by default a new figure

    Returns
    -------
    ax : Axes
        The axes drawn on
    """
    if ax is None:
        _, ax = plt.subplots(figsize=(10, 3.8))
    minutes = _minutes(generation_run.run)
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
    handles.append(_shade_eclipses(ax, generation_run.run))
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
    The panels and their normals in body axes, as a still 3D drawing with each wing at
    zero.

    Parameters
    ----------
    generation_run : GenerationRun
        The generation
    colours : dict, optional
        Each panel's colour, by default `panel_colours`
    ax : Axes3D, optional
        The 3D axes to draw on, by default a new figure
    elev, azim : float, optional
        The view's elevation and azimuth, in degrees

    Returns
    -------
    ax : Axes3D
        The axes drawn on
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


def consumption_plot(consumption_run: ConsumptionRun, ax: Axes | None = None) -> Axes:
    """
    The loads against time, stacked by subsystem, with the equipment margins.

    Parameters
    ----------
    consumption_run : ConsumptionRun
        The loads over a run
    ax : Axes, optional
        The axes to draw on, by default a new figure

    Returns
    -------
    ax : Axes
        The axes drawn on
    """
    if ax is None:
        _, ax = plt.subplots(figsize=(10, 3.8))
    run = consumption_run.run
    minutes = _minutes(run)
    power = consumption_run.subsystem_power()
    colours = value_colours(power)
    ax.stackplot(
        minutes,
        *[watts.to_value(u.W) for watts in power.values()],
        colors=[colours[name] for name in power],
        edgecolor="white",
        linewidth=0.4,
    )
    handles: list = [Patch(color=colours[name], label=name) for name in power]
    handles.append(_shade_eclipses(ax, run))
    _finish(ax, minutes, "Power consumed, by subsystem", handles)
    return ax


def balance_plot(budget: BudgetRun, ax: Axes | None = None) -> Axes:
    """
    The power at the array's output against the power the loads take, all margins in.

    Parameters
    ----------
    budget : BudgetRun
        The budget
    ax : Axes, optional
        The axes to draw on, by default a new figure

    Returns
    -------
    ax : Axes
        The axes drawn on
    """
    if ax is None:
        _, ax = plt.subplots(figsize=(10, 3.8))
    run = budget.generation.run
    minutes = _minutes(run)
    handles: list = []
    for label, power, colour in (
        ("generated", budget.generation.total, PALETTE[0]),
        ("consumed", budget.load, PALETTE[1]),
    ):
        (line,) = ax.plot(
            minutes, power.to_value(u.W), color=colour, linewidth=2, label=label
        )
        handles.append(line)
    handles.append(_shade_eclipses(ax, run))
    _finish(ax, minutes, "Power generated and consumed", handles)
    return ax


def charge_plot(budget: BudgetRun, ax: Axes | None = None) -> Axes:
    """
    The battery's charge against time, with the lowest charge allowed.

    Parameters
    ----------
    budget : BudgetRun
        The budget
    ax : Axes, optional
        The axes to draw on, by default a new figure

    Returns
    -------
    ax : Axes
        The axes drawn on
    """
    if ax is None:
        _, ax = plt.subplots(figsize=(10, 3.2))
    run = budget.generation.run
    minutes = _minutes(run)
    (line,) = ax.plot(
        minutes, 100 * budget.charge, color=PALETTE[2], linewidth=2, label="charge"
    )
    limit = 100 * budget.lowest_allowed
    ax.axhline(limit, color=CRITICAL, linestyle="--", linewidth=1.5)
    handles: list = [
        line,
        Line2D([], [], color=CRITICAL, linestyle="--", lw=1.5, label="lowest allowed"),
        _shade_eclipses(ax, run),
    ]
    low = min(limit, float(100 * budget.charge.min()))
    ax.set(
        xlim=(0, minutes[-1]),
        ylim=(max(0.0, low - 10), 101),
        xlabel="Minutes from the start of the run",
        ylabel="Charge [%]",
        title="Battery charge",
    )
    ax.legend(handles=handles, loc="upper center", bbox_to_anchor=(0.5, -0.22), ncol=3)
    return ax
