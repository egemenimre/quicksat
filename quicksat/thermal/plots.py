# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
Plots of the payload's heat account: its net heat in since the start of the run.

Each plot draws from a `ThermalRun` and returns the matplotlib axes, without
showing the figure, as the power plots do.
"""

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.axes import Axes
from matplotlib.patches import Patch

from quicksat import u
from quicksat.thermal.account import ThermalRun
from quicksat.utils.plot_helpers import AXIS, INK, value_colours

MODE_ALPHA = 0.22
"""How strongly the payload's modes are shaded behind the heat account's line."""


def heat_plot(thermal_run: ThermalRun, ax: Axes | None = None) -> Axes:
    """
    The payload's net heat in since the start of the run, over its modes.

    Each payload mode is shaded in a colour of its own behind the line. Where the
    line rises, heat builds up in the payload. Where it falls, the payload cools.

    Parameters
    ----------
    thermal_run : ThermalRun
        The payload's heat account
    ax : Axes, optional
        The axes to draw on. A new figure by default.

    Returns
    -------
    ax : Axes
        The axes drawn on
    """
    if ax is None:
        _, ax = plt.subplots(figsize=(10, 3.8))
    run = thermal_run.run
    minutes = np.asarray((run.times - run.times[0]).to_value(u.min))
    (line,) = ax.plot(
        minutes,
        thermal_run.running_energy.to_value(u.W * u.h),
        color=INK,
        linewidth=2,
        label="net heat in",
        zorder=2,
    )
    ax.axhline(0, color=AXIS, linewidth=1, zorder=1)
    handles: list = [line]
    for mode, colour in value_colours(thermal_run.mode_watts).items():
        for start, end, found in thermal_run.pieces:
            if found == mode:
                ax.axvspan(
                    start / 60, end / 60, color=colour, alpha=MODE_ALPHA, linewidth=0
                )
        handles.append(Patch(color=colour, alpha=MODE_ALPHA, label=mode))
    ax.set(
        xlim=(0, minutes[-1]),
        xlabel="Minutes from the start of the run",
        ylabel="Net heat in [W h]",
        title="The payload's net heat in since the start",
    )
    ax.legend(
        handles=handles,
        loc="upper center",
        bbox_to_anchor=(0.5, -0.18),
        ncol=min(len(handles), 4),
    )
    return ax
