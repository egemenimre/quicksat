# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
The run's tables: the occurrences of the activities, their summary, the rows of
the Gantt chart, and the targets' passes.

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
    Illumination,
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
        The occurrences from `resolve_activities`

    Returns
    -------
    table : pd.DataFrame
        The columns are the repeat and activity numbers, the title, the start and
        end as UTC text, the duration in minutes, the trigger as written, the attitude, the
        time of the slew into it in seconds, the payload's mode and the
        platform's, the constraint, the time
        outside the constraint in seconds, and the status. The duration is
        negative for an activity that ends before it starts. The status is `ok`,
        or any of `negative duration`, `outside constraint`, `event never came`,
        `cut at end` and `slew starts early`, joined by commas. The slew is NaN
        where there is none. The constraint is blank and the time outside is NaN
        where an activity has no constraint.
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
    One line that sums up the occurrences and how many have a problem.

    Parameters
    ----------
    occurrences : list of Occurrence
        The occurrences from `resolve_activities`

    Returns
    -------
    summary : str
        The number of occurrences and repeats, and how many have a negative
        duration, are outside their constraint, saw an event that never came, were
        cut at the end, or have a slew that starts early
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
    illumination: Illumination,
    occurrences: list[Occurrence],
    slews: list[SlewWindow],
) -> tuple[P.IntervalDict, P.IntervalDict, dict[str, P.IntervalDict]]:
    """
    Build the rows of the Gantt chart: the illumination, the attitude, and the
    payload's and the platform's modes.

    Each row has exactly one value at any time of the run. Touching pieces with
    the same value merge into one. The attitude and mode rows give the time after
    the last occurrence, if any, as `unplanned`.

    Parameters
    ----------
    illumination : dict
        The intervals of `sunlit`, `penumbra` and `umbra`
    occurrences : list of Occurrence
        The occurrences from `resolve_activities`
    slews : list of SlewWindow
        The slews, from `plan_slews`. They take the attitude row's and the
        platform's mode row's time over from the activities. They take the
        payload's too, where the activity after the slew asks for its own mode
        through `payload_mode_in_slew`.

    Returns
    -------
    illumination : portion.IntervalDict
        `sunlit`, `penumbra` and `umbra`
    attitude : portion.IntervalDict
        The attitude names, `slew` while the body turns or settles, and
        `unplanned` after the last occurrence
    mode : dict of str to portion.IntervalDict
        The mode names of the payload and of the platform, by the group's name,
        and `unplanned` after the last occurrence. The platform's mode is `slew`
        while the body turns or settles. By default, the payload's carries on
        through the turn, which takes the end of the activity before it. With
        `payload_mode_in_slew: this_activity`, the payload takes the mode of the
        activity after the slew for the whole turn.
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
    Tabulate every target's passes: each time it is in view, one row each.

    A pass under way when the run starts begins at the start, and one under way
    when it ends ends at the end. So it is cut, as the run is.

    Parameters
    ----------
    run : ScenarioRun
        The run

    Returns
    -------
    table : pd.DataFrame
        The columns are the target, the start and the end of the pass as UTC
        text, its duration in minutes, and, for a satellite target, the closest
        range in km at the grid's times in the pass. The range is NaN for a
        ground target, and for a pass between two grid times. The rows are in
        the order of their starts.
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
