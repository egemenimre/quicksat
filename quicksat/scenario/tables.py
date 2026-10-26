# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
The run's tables: the occurrences, their summary, the Gantt chart's rows, and the
targets' passes.

"""

from typing import TYPE_CHECKING, cast

import numpy as np
import pandas as pd
import portion as P
from astropy.coordinates import CartesianRepresentation, SkyCoord

from quicksat import u
from quicksat.scenario.attitude import SlewWindow
from quicksat.scenario.events import (
    CUT_AT_END,
    EVENT_NEVER_CAME,
    NEGATIVE_DURATION,
    OUTSIDE_CONSTRAINT,
    SLEW_STARTS_EARLY,
    IlluminationIntervals,
    Occurrence,
)
from quicksat.scenario.names import (
    GROUPS,
    PAYLOAD,
    PLATFORM,
    SLEW,
    THIS_ACTIVITY,
    UNPLANNED,
)
from quicksat.utils.intervals import duration

if TYPE_CHECKING:  # a type annotation only, as run.py imports this module
    from quicksat.scenario.run import ScenarioRun


def activity_table(occurrences: list[Occurrence]) -> pd.DataFrame:
    """
    Tabulate the occurrences, one row each.

    Parameters
    ----------
    occurrences : list of Occurrence
        The occurrences

    Returns
    -------
    table : pd.DataFrame
        The numbers, the title, the start and end in UTC, the duration in min, the
        trigger, the attitude, the slew in s, the modes, the constraint, the time
        outside it in s, and the statuses
    """
    rows = []
    for occurrence in occurrences:
        activity = occurrence.activity
        rows.append(
            {
                "repeat": occurrence.repeat,
                "activity": occurrence.number,
                "title": activity.title,
                "start [UTC]": occurrence.start.utc.isot,
                "end [UTC]": occurrence.end.utc.isot,
                "duration [min]": round(
                    float((occurrence.end - occurrence.start).to_value(u.s)), 3
                )
                / 60,
                "trigger": activity.trigger.text,
                "attitude": activity.attitude,
                "slew [s]": (
                    np.nan if occurrence.slew is None else occurrence.slew.to_value(u.s)
                ),
                "payload mode": activity.mode.payload,
                "platform mode": activity.mode.platform,
                "constraint": activity.constraint or "",
                "outside [s]": (
                    np.nan
                    if occurrence.outside is None
                    else occurrence.outside.to_value(u.s)
                ),
                "status": ", ".join(occurrence.statuses),
            }
        )
    return pd.DataFrame(rows)


def activity_summary(occurrences: list[Occurrence]) -> str:
    """
    One line that sums up the occurrences and how many have each problem.

    Parameters
    ----------
    occurrences : list of Occurrence
        The occurrences

    Returns
    -------
    summary : str
        The line
    """
    repeats = occurrences[-1].repeat if occurrences else 0
    early = sum(occurrence.negative_duration for occurrence in occurrences)
    failed = sum(occurrence.failed for occurrence in occurrences)
    never_came = sum(occurrence.event_never_came for occurrence in occurrences)
    cut = sum(occurrence.cut_at_end for occurrence in occurrences)
    slews = sum(occurrence.slew_starts_early for occurrence in occurrences)
    return (
        f"Occurrences: {len(occurrences)} in {repeats} repeat{'' if repeats == 1 else 's'}. "
        f"{NEGATIVE_DURATION.capitalize()}: {early}. "
        f"{OUTSIDE_CONSTRAINT.capitalize()}: {failed}. "
        f"{EVENT_NEVER_CAME.capitalize()}: {never_came}. "
        f"{CUT_AT_END.capitalize()}: {cut}. "
        f"{SLEW_STARTS_EARLY.capitalize()}: {slews}."
    )


def gantt_rows(
    illumination: IlluminationIntervals,
    occurrences: list[Occurrence],
    slews: list[SlewWindow],
) -> tuple[P.IntervalDict, P.IntervalDict, dict[str, P.IntervalDict]]:
    """
    The rows of the Gantt chart, each with one value at any time, and touching pieces
    merged.

    A slew takes the attitude's row and the platform's mode, and the payload's too with
    `payload_mode_in_slew: this_activity`.

    Parameters
    ----------
    illumination : dict
        The intervals of `sunlit`, `penumbra` and `umbra`
    occurrences : list of Occurrence
        The occurrences
    slews : list of SlewWindow
        The slews, from `plan_slews`

    Returns
    -------
    illumination : portion.IntervalDict
        `sunlit`, `penumbra` and `umbra`
    attitude : portion.IntervalDict
        The attitudes, `slew`, and `unplanned` after the last occurrence
    mode : dict of str to portion.IntervalDict
        The payload's and the platform's modes, with `slew` and `unplanned`
    """
    row = P.IntervalDict()
    for state in ("sunlit", "penumbra", "umbra"):
        row[illumination[state]] = state
    attitude = P.IntervalDict()
    mode = {group: P.IntervalDict() for group in GROUPS}
    for occurrence in occurrences:
        attitude[occurrence.interval] = occurrence.activity.attitude
        for group in GROUPS:
            mode[group][occurrence.interval] = occurrence.activity.mode[group]
    # the illumination covers the whole run, so what is left of it is unplanned
    unplanned = row.domain() - attitude.domain()
    if not unplanned.empty:
        attitude[unplanned] = UNPLANNED
        for group in GROUPS:
            mode[group][unplanned] = UNPLANNED
    for window in slews:
        attitude[window.interval] = SLEW
        mode[PLATFORM][window.interval] = SLEW
        modes = occurrences[window.into].activity.mode
        if modes.payload_mode_in_slew == THIS_ACTIVITY:
            mode[PAYLOAD][window.interval] = modes.payload
    return row, attitude, mode


def _km(state: SkyCoord) -> np.ndarray:
    """A state's positions in km, one row each."""
    cartesian = cast(CartesianRepresentation, state.cartesian)
    return np.atleast_2d(cartesian.xyz.to_value(u.km).T)


def pass_table(run: "ScenarioRun") -> pd.DataFrame:
    """
    Tabulate every target's passes, one row each, cut at the run's ends.

    Parameters
    ----------
    run : ScenarioRun
        The run

    Returns
    -------
    table : pd.DataFrame
        The target, the start and end in UTC, the duration in min, and a satellite's
        closest range in km on the grid, in the order of the starts
    """
    columns = ["target", "from [UTC]", "to [UTC]", "duration [min]", "closest [km]"]
    here = _km(run.state)
    rows = []
    for name, seen in run.in_view.items():
        ranges = None
        if name in run.sat_states:
            ranges = np.linalg.norm(_km(run.sat_states[name]) - here, axis=1)
        for piece in seen:
            inside = (run.times >= piece.lower) & (run.times <= piece.upper)
            closest = np.nan
            if ranges is not None and inside.any():
                closest = round(float(ranges[inside].min()), 3)
            rows.append(
                {
                    "target": name,
                    "from [UTC]": piece.lower.utc.isot,
                    "to [UTC]": piece.upper.utc.isot,
                    "duration [min]": duration(piece).to_value(u.min),
                    "closest [km]": closest,
                }
            )
    table = pd.DataFrame(rows, columns=columns)
    return table.sort_values(["from [UTC]", "target"], ignore_index=True)
