# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
Helpers for quicksat's static plots: a style, colours, a legend and the coastlines.

Apply the style once with `plt.style.use(STYLE)`. Values take their colours from
`PALETTE` in a fixed order, so a value keeps its colour in every plot. The coastlines
are Natural Earth's 1:110m, which is public domain.

"""

import json
from collections.abc import Iterable
from importlib.resources import files

import numpy as np
from matplotlib.artist import Artist
from matplotlib.axes import Axes
from matplotlib.colors import to_rgb
from matplotlib.patches import Patch

INK = "#0b0b0b"
"""Colour of titles and of text on a light fill."""

SECONDARY = "#52514e"
"""Colour of axis labels and tick labels."""

MUTED = "#898781"
"""Colour of a value past the end of the palette."""

DIM = "#5c5b56"
"""Colour of the time that no activity plans: a grey darker than `MUTED`, apart from a
slew."""

GRID = "#e1e0d9"
"""Colour of grid lines."""

AXIS = "#c3c2b7"
"""Colour of axis lines, and of the coastlines."""

CRITICAL = "#d03b3b"
"""Colour that marks a problem, such as an activity outside its constraint."""

PALETTE = (
    "#2a78d6",
    "#eb6834",
    "#1baf7a",
    "#eda100",
    "#e87ba4",
    "#008300",
    "#4a3aa7",
    "#e34948",
)
"""The colours that values take, in this order."""

ILLUMINATION_COLOURS = {
    "sunlit": "#c9d6e8",
    "penumbra": "#8197b8",
    "umbra": "#4a5d7e",
}
"""The illumination's colours: one slate hue, light in the sun and dark in the shadow,
apart from `PALETTE`."""

STYLE = {  # noqa: V107
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.edgecolor": AXIS,
    "axes.titlelocation": "left",
    "axes.titlecolor": INK,
    "axes.labelcolor": SECONDARY,
    "axes.grid": True,
    "axes.axisbelow": True,
    "grid.color": GRID,
    "xtick.color": SECONDARY,
    "ytick.color": SECONDARY,
    "xtick.major.size": 0,
    "ytick.major.size": 0,
    "legend.frameon": False,
    "legend.fontsize": 9,
}
"""matplotlib settings for quicksat's plots."""


def value_colours(values: Iterable[str]) -> dict[str, str]:
    """
    One colour for each value, in `PALETTE`'s order, and grey past its end.

    Parameters
    ----------
    values : iterable of str
        The values, in the order they take the colours

    Returns
    -------
    colours : dict
        Each value's colour, as a hex string
    """
    unique = dict.fromkeys(values)
    return {
        value: PALETTE[index] if index < len(PALETTE) else MUTED
        for index, value in enumerate(unique)
    }


def text_colour(fill: str) -> str:
    """
    Colour for text drawn on a fill: white on a dark fill, and `INK` on a light one.

    Parameters
    ----------
    fill : str
        The fill colour, in any form matplotlib reads

    Returns
    -------
    colour : str
        `white` or `INK`
    """
    red, green, blue = to_rgb(fill)
    luminance = 0.2126 * red + 0.7152 * green + 0.0722 * blue
    return "white" if luminance < 0.5 else INK


def legend_below(
    ax: Axes, colours: dict[str, str], extra: Iterable[Artist] = ()
) -> None:
    """
    A legend in one row below the plot: a patch for each value, then any extras.

    Parameters
    ----------
    ax : Axes
        The axes to put the legend on
    colours : dict
        The colour of each value to show, in the order to show them
    extra : iterable of Artist, optional
        Further legend entries after the values, such as a marker
    """
    handles = [Patch(color=colour, label=value) for value, colour in colours.items()]
    handles += list(extra)
    ax.legend(
        handles=handles,
        loc="upper center",
        bbox_to_anchor=(0.5, -0.15),
        ncol=max(len(handles), 1),
    )


def load_coastlines() -> list[np.ndarray]:
    """
    Read the coastlines shipped with quicksat, from -180 to 180 degrees of longitude.
    None crosses the antimeridian.

    Returns
    -------
    lines : list of ndarray
        One array of shape (n, 2) per line, in degrees of longitude and latitude
    """
    text = (files("quicksat") / "data" / "coastlines.json").read_text()
    return [np.asarray(flat, dtype=float).reshape(-1, 2) for flat in json.loads(text)]
