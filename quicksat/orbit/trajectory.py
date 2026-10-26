# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
Trajectories: an orbit given as positions and velocities at times.

A `Trajectory` holds states in GCRS in segments, each with its own degree-5 splines, so
none is smoothed across a manoeuvre. Nothing is extrapolated. One orbit is measured from
the states, between ascending nodes. `docs/scenario/scenario_ref.ipynb`, under "A
trajectory file", explains the frames, the splines and their accuracy.

"""

import warnings
from dataclasses import dataclass

import numpy as np
from astropy.coordinates import (
    CIRS,
    GCRS,
    ITRS,
    TEME,
    TETE,
    CartesianDifferential,
    CartesianRepresentation,
    PrecessedGeocentric,
    SkyCoord,
)
from astropy.time import Time
from astropy.units import Quantity
from scipy.interpolate import BSpline, make_interp_spline
from scipy.optimize import brentq

from quicksat import MU_EARTH, Q_, u
from quicksat.utils.intervals import TimeArray

FRAMES = {
    "GCRS": (GCRS, {}),
    "ITRS": (ITRS, {}),
    "TEME": (TEME, {}),
    "CIRS": (CIRS, {}),
    "TETE": (TETE, {}),
    "EME2000": (PrecessedGeocentric, {"equinox": Time("J2000", scale="tt")}),
}
"""The frames a trajectory file may use, each with its astropy frame and fixed
attributes, all centred on the Earth."""

BARYCENTRIC_FRAMES = ("ICRS", "FK5", "FK4")
"""Frames refused because astropy centres them on the solar system's barycentre."""

SPLINE_DEGREE = 5
"""Degree of the interpolating splines, as in satmad."""

END_SAMPLES = 3
"""Within this many samples of either end, the interpolation is less accurate, and a run
gets a warning."""

NODE_MIN_INCLINATION = Q_(1, "deg")
"""Below this inclination, one orbit is measured against a fixed direction, not the
node."""

ASCENDING_NODES = "ascending nodes"
FIXED_DIRECTION = "a fixed direction"
TWO_BODY = "two-body estimate"


def _crossings(offsets: np.ndarray, values: np.ndarray, value_at, keep) -> list:
    """
    The times, in s, at which a value rises through zero, located between the samples.
    """
    rising = (values[:-1] < 0) & (values[1:] >= 0) & keep
    return [
        brentq(value_at, offsets[k], offsets[k + 1], xtol=1e-6)
        for k in np.flatnonzero(rising)
    ]


@dataclass(frozen=True)
class _Segment:
    """
    One stretch of samples with no manoeuvre in it: its times in s, its states in km and
    km/s, the span it serves, and its splines.
    """

    offsets: np.ndarray
    positions: np.ndarray
    velocities: np.ndarray
    first: float
    last: float
    position: BSpline
    velocity: BSpline


def _segment(
    offsets: np.ndarray,
    positions: np.ndarray,
    velocities: np.ndarray,
    span: tuple[float, float] | None,
    number: int,
    count: int,
) -> _Segment:
    """
    A segment through samples, with degree-5 splines where there are enough, or an error
    for too few samples, falling times, or a span past them.
    """
    offsets = np.asarray(offsets, dtype=float)
    where = f"segment {number}" if count > 1 else "the trajectory"
    if len(offsets) < 2:
        raise ValueError(f"{where} needs at least 2 samples, got {len(offsets)}")
    if np.any(np.diff(offsets) <= 0):
        raise ValueError(f"the times of {where} must rise, with no repeats")
    first, last = span if span is not None else (offsets[0], offsets[-1])
    if first < offsets[0] - 1e-6 or last > offsets[-1] + 1e-6 or first >= last:
        raise ValueError(
            f"the useable span of {where} must lie inside its samples, and end "
            "after it starts"
        )
    degree = min(SPLINE_DEGREE, len(offsets) - 1)
    if degree < SPLINE_DEGREE:
        warnings.warn(
            f"{where.capitalize()} has {len(offsets)} samples, so its splines are "
            f"of degree {degree} instead of {SPLINE_DEGREE}, and less accurate.",
            stacklevel=3,
        )
    positions = np.asarray(positions, dtype=float)
    velocities = np.asarray(velocities, dtype=float)
    return _Segment(
        offsets=offsets,
        positions=positions,
        velocities=velocities,
        first=float(first),
        last=float(last),
        position=make_interp_spline(offsets, positions, k=degree),
        velocity=make_interp_spline(offsets, velocities, k=degree),
    )


class Trajectory:
    """
    An orbit given as states at times, in segments, interpolated in between.

    Where one segment ends as the next starts, the later applies. A run may not cross a
    gap. Build one with `from_states` or `from_segments`, or read one from a file.

    Parameters
    ----------
    epoch : Time
        The time the offsets count from
    segments : list of tuple
        Each segment's times since the epoch in s, and positions and velocities in GCRS
        in km and km/s
    spans : list, optional
        The span each segment serves, in s, or None for all its samples
    name : str, optional
        The satellite's name
    frame : str, optional
        The frame the states were given in

    Attributes
    ----------
    file, format, originator : str or None
        The file's name, `ECSV` or `OEM`, and an OEM's writer, which a reader fills in

    Raises
    ------
    ValueError
        If a segment has under two samples or falling times, or the segments overlap
    """

    def __init__(
        self,
        epoch: TimeArray,
        segments: list[tuple[np.ndarray, np.ndarray, np.ndarray]],
        spans: list[tuple[float, float] | None] | None = None,
        name: str | None = None,
        frame: str = "GCRS",
    ):
        served: list[tuple[float, float] | None] = (
            list(spans) if spans is not None else [None] * len(segments)
        )
        self._segments = [
            _segment(offsets, positions, velocities, span, number, len(segments))
            for number, ((offsets, positions, velocities), span) in enumerate(
                zip(segments, served, strict=True), start=1
            )
        ]
        for number, (before, after) in enumerate(
            zip(self._segments[:-1], self._segments[1:], strict=True), start=2
        ):
            # a segment may start at the last sample of the one before, at a
            # manoeuvre, but not before it
            if after.offsets[0] < before.offsets[-1] - 1e-6 or after.first < (
                before.last - 1e-6
            ):
                raise ValueError(f"segment {number} overlaps the one before it")
        self.epoch = epoch
        self.name = name
        self.frame = frame
        self.file: str | None = None
        self.format: str | None = None
        self.originator: str | None = None
        self.period, self.period_method = self._measure_period()

    @classmethod
    def from_states(
        cls, state: SkyCoord, name: str | None = None, frame: str = "GCRS"
    ) -> "Trajectory":
        """
        A trajectory of one segment through a satellite's states.

        Parameters
        ----------
        state : SkyCoord
            Positions with velocities and their times, in any frame astropy turns into
            GCRS
        name : str, optional
            The satellite's name
        frame : str, optional
            The frame to report, by default GCRS

        Returns
        -------
        trajectory : Trajectory
            The trajectory, with its epoch at the first state
        """
        return cls.from_segments([state], name=name, frame=frame)

    @classmethod
    def from_segments(
        cls,
        states: list[SkyCoord],
        spans: list[tuple[TimeArray, TimeArray] | None] | None = None,
        name: str | None = None,
        frame: str = "GCRS",
    ) -> "Trajectory":
        """
        A trajectory through segments of a satellite's states.

        Parameters
        ----------
        states : list of SkyCoord
            Each segment's positions with velocities and their times, in time order
        spans : list, optional
            Each segment's start and end, or None for all its samples
        name : str, optional
            The satellite's name
        frame : str, optional
            The frame to report, by default GCRS

        Returns
        -------
        trajectory : Trajectory
            The trajectory, with its epoch at the first state
        """
        first: TimeArray = states[0].obstime
        epoch: TimeArray = first[0]
        segments = []
        for state in states:
            times: TimeArray = state.obstime
            gcrs = state.transform_to(GCRS(obstime=times)).cartesian
            assert isinstance(gcrs, CartesianRepresentation)
            velocity = gcrs.differentials["s"]
            assert isinstance(velocity, CartesianDifferential)
            segments.append(
                (
                    np.atleast_1d((times - epoch).to_value(u.s)),
                    gcrs.xyz.to_value(u.km).T,
                    velocity.d_xyz.to_value(u.km / u.s).T,
                )
            )
        offset_spans = [
            None
            if span is None
            else (
                float((span[0] - epoch).to_value(u.s)),
                float((span[1] - epoch).to_value(u.s)),
            )
            for span in (spans or [None] * len(states))
        ]
        return cls(epoch, segments, offset_spans, name=name, frame=frame)

    @property
    def start(self) -> TimeArray:
        """The start of the first segment's span."""
        return self.epoch + Q_(self._segments[0].first, "s")

    @property
    def end(self) -> TimeArray:
        """The end of the last segment's span."""
        return self.epoch + Q_(self._segments[-1].last, "s")

    @property
    def sample_count(self) -> int:
        """The samples, over all the segments."""
        return sum(len(segment.offsets) for segment in self._segments)

    @property
    def segment_count(self) -> int:
        """The number of segments."""
        return len(self._segments)

    @property
    def period_measured(self) -> bool:
        """
        Whether one orbit was measured, rather than the two-body estimate of a
        trajectory under one orbit long.
        """
        return self.period_method != TWO_BODY

    def _measure_period(self) -> tuple[Quantity, str]:
        """
        One orbit, in s, as the mean time between crossings inside the segments' spans,
        with how it was found.
        """
        positions = np.concatenate([segment.positions for segment in self._segments])
        velocities = np.concatenate([s.velocities for s in self._segments])
        normals = np.cross(positions, velocities)
        normal = np.mean(normals / np.linalg.norm(normals, axis=1, keepdims=True), 0)
        normal /= np.linalg.norm(normal)
        inclination = Q_(np.arccos(np.clip(normal[2], -1.0, 1.0)), "rad")

        towards = None
        if inclination >= NODE_MIN_INCLINATION:
            # the equator, crossed northward
            method, across = ASCENDING_NODES, np.array([0.0, 0.0, 1.0])
        else:
            # the half-plane on the side of the GCRS axis that lies most in the
            # orbit plane, crossed in the direction of motion
            method = FIXED_DIRECTION
            axis = np.eye(3)[np.argmin(np.abs(np.eye(3) @ normal))]
            towards = axis - (axis @ normal) * normal
            towards /= np.linalg.norm(towards)
            across = np.cross(normal, towards)

        crossings = []
        for segment in self._segments:
            keep = np.ones(len(segment.offsets) - 1, dtype=bool)
            if towards is not None:
                keep = (segment.positions @ towards)[:-1] > 0
            found = _crossings(
                segment.offsets,
                segment.positions @ across,
                lambda t, spline=segment.position: float(spline(t) @ across),
                keep,
            )
            crossings += [t for t in found if segment.first <= t < segment.last]
        if len(crossings) >= 2:
            seconds = (max(crossings) - min(crossings)) / (len(crossings) - 1)
            return Q_(seconds, "s"), method

        r = np.linalg.norm(positions[0])
        v = np.linalg.norm(velocities[0])
        mu = MU_EARTH.to_value(u.km**3 / u.s**2)
        semi_major_axis = 1 / (2 / r - v**2 / mu)
        if semi_major_axis <= 0:
            raise ValueError("the trajectory is not a closed orbit around the Earth")
        return Q_(2 * np.pi * np.sqrt(semi_major_axis**3 / mu), "s"), TWO_BODY

    def _segment_indices(self, offsets: np.ndarray) -> np.ndarray:
        """The index of the segment that serves each time, or -1."""
        firsts = np.array([segment.first for segment in self._segments])
        lasts = np.array([segment.last for segment in self._segments])
        # a microsecond of slack for the rounding of the times; a time where two
        # segments meet goes to the later one
        indices = np.searchsorted(firsts - 1e-6, offsets, side="right") - 1
        inside = (indices >= 0) & (offsets <= lasts[np.maximum(indices, 0)] + 1e-6)
        return np.where(inside, indices, -1)

    def states(self, times: TimeArray, with_velocity: bool = True) -> SkyCoord:
        """
        The satellite's state at any times inside the trajectory, in GCRS.

        Parameters
        ----------
        times : Time
            The times, as an array
        with_velocity : bool, optional
            Whether to add the velocities

        Returns
        -------
        state : SkyCoord
            The positions from the Earth's centre, and any velocities, in GCRS, at
            `times`

        Raises
        ------
        ValueError
            If a time lies outside every segment's span
        """
        offsets = np.atleast_1d((times - self.epoch).to_value(u.s))
        indices = self._segment_indices(offsets)
        if np.any(indices < 0):
            raise ValueError(
                "a time lies outside the trajectory, which runs from "
                f"{self.start.utc.isot} to {self.end.utc.isot} UTC"
                + (", with gaps" if self.segment_count > 1 else "")
            )
        positions = np.empty((len(offsets), 3))
        velocities = np.empty((len(offsets), 3))
        for index in np.unique(indices):
            segment = self._segments[index]
            mask = indices == index
            at = np.clip(offsets[mask], segment.offsets[0], segment.offsets[-1])
            positions[mask] = segment.position(at)
            velocities[mask] = segment.velocity(at)
        data = CartesianRepresentation(Q_(positions.T, "km"))
        if with_velocity:
            data = data.with_differentials(
                CartesianDifferential(Q_(velocities.T, "km/s"))
            )
        return SkyCoord(GCRS(data, obstime=times))

    def check_covers(
        self, start: TimeArray, end: TimeArray, label: str = "the trajectory"
    ) -> str | None:
        """
        Check that a run lies inside the trajectory and crosses no gap, with a warning
        if it nears the ends of the samples.

        Parameters
        ----------
        start, end : Time
            The run's start and end
        label : str, optional
            What the trajectory is, for the messages

        Returns
        -------
        text : str or None
            The warning, or None

        Raises
        ------
        ValueError
            If the run reaches past the trajectory or crosses a gap
        """
        first = float((start - self.epoch).to_value(u.s))
        last = float((end - self.epoch).to_value(u.s))
        indices = self._segment_indices(np.array([first, last]))
        if np.any(indices < 0):
            raise ValueError(
                f"The run, from {start.utc.isot} to {end.utc.isot} UTC, does not lie "
                f"inside {label}, which runs from {self.start.utc.isot} to "
                f"{self.end.utc.isot} UTC. quicksat does not extrapolate."
            )
        for index in range(indices[0], indices[1]):
            before, after = self._segments[index], self._segments[index + 1]
            if after.first > before.last + 1e-6:
                gap_start = (self.epoch + Q_(before.last, "s")).utc.isot
                gap_end = (self.epoch + Q_(after.first, "s")).utc.isot
                raise ValueError(
                    f"The run crosses a gap in {label}, from {gap_start} to "
                    f"{gap_end} UTC, between segments {index + 1} and {index + 2}."
                )
        opening = self._segments[indices[0]].offsets
        closing = self._segments[indices[1]].offsets
        if (
            first < opening[min(END_SAMPLES, len(opening) - 1)]
            or last > (closing[max(-1 - END_SAMPLES, -len(closing))])
        ):
            text = (
                f"The run comes within {END_SAMPLES} samples of an end of {label}, "
                "where the interpolation is less accurate. A file that reaches a few "
                "samples past the run at each end avoids it."
            )
            warnings.warn(text, stacklevel=2)
            return text
        return None


def frame_of(name: str) -> tuple[type, dict]:
    """
    The astropy frame class and attributes for a frame's name in a file.

    Parameters
    ----------
    name : str
        The frame's name, in any case

    Returns
    -------
    frame : tuple
        The frame class and its fixed attributes

    Raises
    ------
    ValueError
        If the frame is not one of `FRAMES`
    """
    key = str(name).strip().upper()
    if key in FRAMES:
        return FRAMES[key]
    reason = (
        " astropy centres it on the solar system's barycentre, not on the Earth."
        if key in BARYCENTRIC_FRAMES
        else ""
    )
    raise ValueError(
        f"the frame '{name}' is not read.{reason} The frame must be one of: "
        f"{', '.join(FRAMES)}"
    )
