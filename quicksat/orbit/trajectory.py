# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
Trajectories: an orbit given as positions and velocities at times.

A `Trajectory` holds states in GCRS and interpolates between them. It does not
know where they came from. `quicksat.orbit.ecsv_trajectory` reads them from an
ECSV file, and a CCSDS OEM reader can come later in the same way.

The states may be given in a frame centred on the Earth: GCRS, ITRS, TEME,
CIRS, TETE, or EME2000, which astropy calls `PrecessedGeocentric` at J2000.
astropy centres ICRS and FK5 on the solar system's barycentre, so a satellite's
position read in them would land 150 million km away. They are refused.

Between the states, the position and the velocity each come from an
interpolating spline of degree 5, as in satmad. At 60 s between samples in low
orbit, the position is good to a millimetre, except within about three samples
of either end, where it is good to a centimetre. Nothing is extrapolated.

One orbit is measured from the states. It is the mean time between ascending
node crossings, as SGP4's nodal period is for a TLE. Below 1 degree of
inclination the node is not well defined. There, one orbit is the mean time
between crossings of a half-plane fixed in GCRS, which holds the orbit normal
and a GCRS axis in the orbit plane.

"""

import warnings

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
from scipy.interpolate import make_interp_spline
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
"""The frames a trajectory file may use, each with the astropy frame and its
fixed attributes. All are centred on the Earth."""

BARYCENTRIC_FRAMES = ("ICRS", "FK5", "FK4")
"""Frames that are refused with a reason: astropy centres them on the solar
system's barycentre."""

SPLINE_DEGREE = 5
"""Degree of the interpolating splines, as in satmad."""

END_SAMPLES = 3
"""Within this many samples of either end, the interpolation is less accurate,
and a run that comes this close gets a warning."""

NODE_MIN_INCLINATION = Q_(1, "deg")
"""Below this inclination, one orbit is measured against a fixed direction
instead of the ascending node."""

ASCENDING_NODES = "ascending nodes"
FIXED_DIRECTION = "a fixed direction"
TWO_BODY = "two-body estimate"


def _crossings(offsets: np.ndarray, values: np.ndarray, value_at, keep) -> list:
    """
    The times a value rises through zero, located between the samples.

    Parameters
    ----------
    offsets : ndarray
        The sample times [s]
    values : ndarray
        The value at each sample
    value_at : callable
        The value at any time [s]
    keep : ndarray
        Whether a crossing between a sample and the next one counts

    Returns
    -------
    crossings : list of float
        The times of the crossings [s], in order
    """
    rising = (values[:-1] < 0) & (values[1:] >= 0) & keep
    return [
        brentq(value_at, offsets[k], offsets[k + 1], xtol=1e-6)
        for k in np.flatnonzero(rising)
    ]


class Trajectory:
    """
    An orbit given as states at times, interpolated in between.

    Build one with `from_states`, or read one from a file with
    `quicksat.orbit.ecsv_trajectory.read_ecsv_trajectory`.

    Parameters
    ----------
    epoch : Time
        The time the offsets are counted from
    offsets : ndarray
        The time of each sample since the epoch [s], rising
    positions : ndarray
        The position of each sample in GCRS [km], shape (n, 3)
    velocities : ndarray
        The velocity of each sample in GCRS [km/s], shape (n, 3)
    name : str, optional
        The name of the satellite
    file : str, optional
        The name of the file the states were read from
    frame : str, optional
        The frame the states were given in, before they were turned into GCRS

    Raises
    ------
    ValueError
        If there are fewer than six samples, or the times do not rise
    """

    def __init__(
        self,
        epoch: TimeArray,
        offsets: np.ndarray,
        positions: np.ndarray,
        velocities: np.ndarray,
        name: str | None = None,
        file: str | None = None,
        frame: str = "GCRS",
    ):
        offsets = np.asarray(offsets, dtype=float)
        if len(offsets) <= SPLINE_DEGREE:
            raise ValueError(
                f"a trajectory needs at least {SPLINE_DEGREE + 1} samples, "
                f"got {len(offsets)}"
            )
        if np.any(np.diff(offsets) <= 0):
            raise ValueError("the times of a trajectory must rise, with no repeats")
        self.epoch = epoch
        self.name = name
        self.file = file
        self.frame = frame
        self._offsets = offsets
        self._positions = np.asarray(positions, dtype=float)
        self._velocities = np.asarray(velocities, dtype=float)
        self._position = make_interp_spline(offsets, self._positions, k=SPLINE_DEGREE)
        self._velocity = make_interp_spline(offsets, self._velocities, k=SPLINE_DEGREE)
        self.period, self.period_method = self._measure_period()

    @classmethod
    def from_states(
        cls, state: SkyCoord, name: str | None = None, frame: str = "GCRS"
    ) -> "Trajectory":
        """
        A trajectory through a satellite's states, such as from `tle_states`.

        Parameters
        ----------
        state : SkyCoord
            Positions with velocities, in any frame that astropy can turn into
            GCRS, with an `obstime` for each
        name : str, optional
            The name of the satellite
        frame : str, optional
            The frame to report the states as given in. GCRS by default.

        Returns
        -------
        trajectory : Trajectory
            The trajectory, with its epoch at the first state
        """
        times: TimeArray = state.obstime
        gcrs = state.transform_to(GCRS(obstime=times)).cartesian
        assert isinstance(gcrs, CartesianRepresentation)
        velocity = gcrs.differentials["s"]
        assert isinstance(velocity, CartesianDifferential)
        return cls(
            epoch=times[0],
            offsets=(times - times[0]).to_value(u.s),
            positions=gcrs.xyz.to_value(u.km).T,
            velocities=velocity.d_xyz.to_value(u.km / u.s).T,
            name=name,
            frame=frame,
        )

    @property
    def start(self) -> TimeArray:
        """
        The time of the first sample.

        Returns
        -------
        start : Time
        """
        return self.epoch + Q_(self._offsets[0], "s")

    @property
    def end(self) -> TimeArray:
        """
        The time of the last sample.

        Returns
        -------
        end : Time
        """
        return self.epoch + Q_(self._offsets[-1], "s")

    @property
    def sample_count(self) -> int:
        """
        The number of samples.

        Returns
        -------
        count : int
        """
        return len(self._offsets)

    @property
    def period_measured(self) -> bool:
        """
        Whether one orbit was measured from the file, rather than estimated.

        Returns
        -------
        measured : bool
            False for a file shorter than one orbit, where the period is the
            two-body estimate from the first state
        """
        return self.period_method != TWO_BODY

    def _measure_period(self) -> tuple[Quantity, str]:
        """
        One orbit, measured from the samples. See the module notes.

        Returns
        -------
        period : Quantity
            The mean time between crossings, in seconds, or the two-body period
            from the first state where there are fewer than two crossings
        method : str
            `ascending nodes`, `a fixed direction` or `two-body estimate`
        """
        normals = np.cross(self._positions, self._velocities)
        normal = np.mean(normals / np.linalg.norm(normals, axis=1, keepdims=True), 0)
        normal /= np.linalg.norm(normal)
        inclination = Q_(np.arccos(np.clip(normal[2], -1.0, 1.0)), "rad")

        if inclination >= NODE_MIN_INCLINATION:
            # the equator, crossed northward
            method, across = ASCENDING_NODES, np.array([0.0, 0.0, 1.0])
            keep = np.ones(len(self._offsets) - 1, dtype=bool)
        else:
            # the half-plane on the side of the GCRS axis that lies most in the
            # orbit plane, crossed in the direction of motion
            method = FIXED_DIRECTION
            axis = np.eye(3)[np.argmin(np.abs(np.eye(3) @ normal))]
            towards = axis - (axis @ normal) * normal
            towards /= np.linalg.norm(towards)
            across = np.cross(normal, towards)
            keep = (self._positions @ towards)[:-1] > 0

        crossings = _crossings(
            self._offsets,
            self._positions @ across,
            lambda t: float(self._position(t) @ across),
            keep,
        )
        if len(crossings) >= 2:
            seconds = (crossings[-1] - crossings[0]) / (len(crossings) - 1)
            return Q_(seconds, "s"), method

        r = np.linalg.norm(self._positions[0])
        v = np.linalg.norm(self._velocities[0])
        mu = MU_EARTH.to_value(u.km**3 / u.s**2)
        semi_major_axis = 1 / (2 / r - v**2 / mu)
        if semi_major_axis <= 0:
            raise ValueError("the trajectory is not a closed orbit around the Earth")
        return Q_(2 * np.pi * np.sqrt(semi_major_axis**3 / mu), "s"), TWO_BODY

    def states(self, times: TimeArray, with_velocity: bool = True) -> SkyCoord:
        """
        The satellite's state at any times inside the trajectory, in GCRS.

        Parameters
        ----------
        times : Time
            The times, as an array
        with_velocity : bool, optional
            Whether the state carries velocities as well as positions. True by
            default.

        Returns
        -------
        state : SkyCoord
            The position relative to the centre of the Earth, and the velocity if
            asked for, in GCRS. Its `obstime` is `times`.

        Raises
        ------
        ValueError
            If a time lies outside the trajectory
        """
        offsets = np.atleast_1d((times - self.epoch).to_value(u.s))
        # a microsecond of slack for the rounding of the times
        if offsets.min() < self._offsets[0] - 1e-6 or offsets.max() > (
            self._offsets[-1] + 1e-6
        ):
            raise ValueError(
                "a time lies outside the trajectory, which runs from "
                f"{self.start.utc.isot} to {self.end.utc.isot} UTC"
            )
        offsets = np.clip(offsets, self._offsets[0], self._offsets[-1])
        data = CartesianRepresentation(Q_(self._position(offsets).T, "km"))
        if with_velocity:
            data = data.with_differentials(
                CartesianDifferential(Q_(self._velocity(offsets).T, "km/s"))
            )
        return SkyCoord(GCRS(data, obstime=times))

    def check_covers(self, start: TimeArray, end: TimeArray) -> None:
        """
        Check that a run lies inside the trajectory, and warn if it comes close
        to either end.

        Parameters
        ----------
        start, end : Time
            The start and the end of the run

        Raises
        ------
        ValueError
            If the run starts before the first sample or ends after the last
        """
        first = float((start - self.epoch).to_value(u.s))
        last = float((end - self.epoch).to_value(u.s))
        if first < self._offsets[0] - 1e-6 or last > self._offsets[-1] + 1e-6:
            raise ValueError(
                f"The run, from {start.utc.isot} to {end.utc.isot} UTC, does not lie "
                f"inside the trajectory, which runs from {self.start.utc.isot} to "
                f"{self.end.utc.isot} UTC. quicksat does not extrapolate."
            )
        if first < self._offsets[END_SAMPLES] or last > self._offsets[-1 - END_SAMPLES]:
            warnings.warn(
                f"The run comes within {END_SAMPLES} samples of an end of the "
                "trajectory, where the interpolation is less accurate. A file that "
                "reaches a few samples past the run at each end avoids it.",
                stacklevel=2,
            )


def frame_of(name: str) -> tuple[type, dict]:
    """
    The astropy frame class and attributes for a frame name in a file.

    Parameters
    ----------
    name : str
        The frame, as a file gives it, in any case

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
