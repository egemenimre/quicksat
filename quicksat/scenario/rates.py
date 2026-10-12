# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
The body's turn rate within each activity, against the slew capacity.

A slew turns the body between attitudes within the `slew` block's rate and
acceleration. Within an activity, the attitude can move too: nadir turns with the
orbit, and tracking a ground station turns the body fastest as the station
passes below. Over a station near the zenith of a pass, the line of sight turns
at about the ground speed over the altitude: 7.6 km/s over 510 km is 0.85 deg/s.

So the run measures the body's rate and acceleration within each occurrence,
outside the slews, between the steps of the grid. Where either goes past the
`slew` block's limit, the satellite cannot follow that attitude, and the run
gives a warning. The warnings are text, for the notebook and the viewer. The
check needs a `slew` block: without one, attitude changes are instant and there
is no capacity to check against.

The rate is an average over each step of the grid, so a peak shorter than a step
reads low.

"""

from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np
from astropy.units import Quantity

from quicksat import Q_, u
from quicksat.orbit.attitude import body_rates
from quicksat.scenario.attitude import body_rotations
from quicksat.utils.intervals import TimeArray

if TYPE_CHECKING:  # a type annotation only, as run.py imports this module
    from quicksat.scenario.run import Occurrence, ScenarioRun


@dataclass(frozen=True)
class RateExcess:
    """
    An occurrence whose attitude turns the body faster than the slews may.

    Parameters
    ----------
    occurrence : Occurrence
        The occurrence
    start : Time
        When its own attitude starts, after the slew into it
    peak_rate : Quantity
        The fastest turn within it, in deg/s
    peak_acceleration : Quantity
        The largest angular acceleration within it, in deg/s2
    max_rate, max_acceleration : Quantity or None
        The `slew` block's limits. Either may be left out of the block, and is
        then None.
    """

    occurrence: "Occurrence"
    start: TimeArray
    peak_rate: Quantity
    peak_acceleration: Quantity
    max_rate: Quantity | None
    max_acceleration: Quantity | None

    @property
    def text(self) -> str:
        """
        The warning, as a sentence or two.

        Returns
        -------
        text : str
            Such as "Tracking in downlink Svalbard (track Svalbard), starting
            2026-10-01 09:16:57 UTC, exceeds the slew capacity. ..."
        """
        rate = float(self.peak_rate.to(u.deg / u.s).value)
        acceleration = float(self.peak_acceleration.to(u.deg / u.s**2).value)
        limits = []
        if self.max_rate is not None:
            limits.append(f"{float(self.max_rate.to(u.deg / u.s).value):g} deg/s")
        if self.max_acceleration is not None:
            limits.append(
                f"{float(self.max_acceleration.to(u.deg / u.s**2).value):g} deg/s2"
            )
        return (
            f"Tracking in {self.occurrence.activity.title} "
            f"({self.occurrence.activity.attitude}), starting "
            f"{self.start.utc.iso[:19]} UTC, exceeds the slew capacity. Its peak "
            f"rate is {rate:.3f} deg/s and its peak acceleration "
            f"{acceleration:.4f} deg/s2, against the slew block's "
            f"{' and '.join(limits)}."
        )


def rate_excesses(run: "ScenarioRun") -> list[RateExcess]:
    """
    The occurrences whose own attitude turns faster than the slew capacity.

    Only the steps wholly inside an occurrence's own attitude time count, so the
    slews, and the steps across their ends, are left out.

    Parameters
    ----------
    run : ScenarioRun
        The run

    Returns
    -------
    excesses : list of RateExcess
        In time order. Empty without a `slew` block.
    """
    slew = run.scenario.slew
    if slew is None:
        return []
    start = run.times[0]
    seconds = np.asarray((run.times - start).to_value(u.s))
    rates, accelerations = body_rates(body_rotations(run), seconds)
    # a limit left out of the block is never passed
    max_rate = (
        np.inf if slew.max_rate is None else float(slew.max_rate.to(u.rad / u.s).value)
    )
    max_acceleration = (
        np.inf
        if slew.max_acceleration is None
        else float(slew.max_acceleration.to(u.rad / u.s**2).value)
    )

    excesses = []
    for occurrence in run.occurrences:
        own = [
            piece
            for piece in run.attitude.find(occurrence.activity.attitude)
            & occurrence.interval
            if not piece.empty
        ]
        if not own:
            continue
        pieces = [
            (
                float((piece.lower - start).to_value(u.s)),
                float((piece.upper - start).to_value(u.s)),
            )
            for piece in own
        ]
        inside_rate = np.zeros(len(rates), dtype=bool)
        inside_acceleration = np.zeros(len(accelerations), dtype=bool)
        for lower, upper in pieces:
            inside_rate |= (seconds[:-1] >= lower) & (seconds[1:] <= upper)
            inside_acceleration |= (seconds[:-2] >= lower) & (seconds[2:] <= upper)
        if not inside_rate.any():
            continue
        peak_rate = float(rates[inside_rate].max())
        peak_acceleration = float(accelerations[inside_acceleration].max(initial=0.0))
        if peak_rate > max_rate or peak_acceleration > max_acceleration:
            excesses.append(
                RateExcess(
                    occurrence,
                    own[0].lower,
                    Q_(np.degrees(peak_rate), "deg / s"),
                    Q_(np.degrees(peak_acceleration), "deg / s2"),
                    slew.max_rate,
                    slew.max_acceleration,
                )
            )
    return excesses
