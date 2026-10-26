# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
The scenario's orbit and its targets, as the scenario file gives them.

The orbit comes from a TLE file, an OMM file, a sun-synchronous orbit or a
trajectory file. A ground target is a point on the Earth. A satellite target is
another satellite, whose orbit comes from a file. A relative path is taken from
the folder of the scenario file.

"""

import re
from pathlib import Path
from typing import Annotated, cast

from astropy.units import Quantity
from pydantic import (
    BeforeValidator,
    ConfigDict,
    Field,
    ValidationInfo,
    field_validator,
    model_validator,
)

from quicksat import Q_, u
from quicksat.utils.parser_helpers import (
    COMMENTS,
    Commented,
    LengthQty,
    SignedAngleQty,
    SignedLengthQty,
)


class GroundTarget(Commented):
    """
    A point on the ground, which turns with the Earth. An attitude can point at it.

    Parameters
    ----------
    latitude : Quantity
        Geodetic latitude, from -90 to 90 degrees
    longitude : Quantity
        Longitude, east
    altitude : Quantity, optional
        Height above the WGS84 ellipsoid, 0 m by default
    min_elevation : Quantity, optional
        The elevation above the point's horizon at which the satellite rises
        and sets, for the `rise` and `set` triggers. 5 deg by default.
    comments : str, optional
        Your own notes on this block. quicksat keeps them and does not read them.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    latitude: SignedAngleQty
    longitude: SignedAngleQty
    altitude: SignedLengthQty = Q_(0, "m")
    min_elevation: SignedAngleQty = Q_(5, "deg")

    @model_validator(mode="after")
    def _check(self):
        """Checks the latitude and the minimum elevation."""
        if abs(self.latitude) > Q_(90, "deg"):
            raise ValueError(
                f"latitude must be from -90 to 90 deg, got '{self.latitude}'"
            )
        if not Q_(0, "deg") <= self.min_elevation < Q_(90, "deg"):
            raise ValueError(
                f"min_elevation must be from 0 deg up to 90 deg, got "
                f"'{self.min_elevation}'"
            )
        return self


_CLOCK_TIME = re.compile(r"(\d{1,2}):(\d{2})(?::(\d{2}(?:\.\d+)?))?")
"""A time of day written as hours and minutes, with seconds if wanted."""


def _parse_node_time(value, name: str) -> Quantity:
    """
    The local time of a node: of the ascending node, or of the descending node.

    Parameters
    ----------
    value : str or Quantity
        A time of day in quotes, such as `"10:30"` or `"10:30:15"`, or a time
        with a unit, such as `10.5 h`
    name : str
        The field's name, `ltan` or `ltdn`, for the error messages

    Returns
    -------
    time : Quantity
        The local time of the node, in hours, from 0 to 24

    Raises
    ------
    ValueError
        If the value is a bare number, is not a time of day, or is not from 0 to
        24 h. YAML reads an unquoted `10:30` as the number 630, a base-60 number.
        So the error for a bare number says to add quotes.
    """
    example = 'such as "10:30" in quotes, or 10.5 h'
    if isinstance(value, bool) or isinstance(value, (int, float)):
        raise ValueError(
            f"{name} must be a time of day, {example}. Got the bare number {value}. "
            "YAML reads an unquoted 10:30 as the number 630, so put it in quotes."
        )
    if isinstance(value, Quantity):
        hours = value
    elif isinstance(value, str):
        text = value.strip()
        match = _CLOCK_TIME.fullmatch(text)
        if match:
            hour, minute, second = match.groups()
            if int(minute) >= 60 or float(second or 0) >= 60:
                raise ValueError(
                    f"{name} has more than 59 minutes or seconds: '{text}'"
                )
            hours = Q_(int(hour) + int(minute) / 60 + float(second or 0) / 3600, "h")
        else:
            try:
                hours = Q_(text)
            except (TypeError, ValueError):
                raise ValueError(
                    f"{name} must be a time of day, {example}. Got '{text}'"
                ) from None
    else:
        raise ValueError(f"{name} must be a time of day, {example}. Got {value!r}")
    if not u.h.is_equivalent(hours.unit):
        raise ValueError(f"{name} must be a time of day, {example}. Got '{hours}'")
    hours = hours.to(u.h)
    if not Q_(0, "h") <= hours < Q_(24, "h"):
        raise ValueError(f"{name} must be from 0 to 24 h, got {hours}")
    return hours


class SsoOrbit(Commented):
    """
    A circular sun-synchronous orbit. quicksat builds its TLE.

    The TLE has its epoch at the start of the run. Its inclination makes SGP4's
    node rate match the mean sun. See `quicksat.orbit.sso`.

    Parameters
    ----------
    altitude : Quantity
        Distance from the centre of the Earth minus `R_EARTH`, averaged over one
        orbit. Positive.
    ltan : Quantity, optional
        Local mean time of the ascending node, from 0 to 24 h. Written `"10:30"`,
        in quotes, or `10.5 h`.
    ltdn : Quantity, optional
        Local mean time of the descending node, in place of `ltan`. The two are
        12 h apart, so `ltdn: "10:30"` is the same orbit as `ltan: "22:30"`.
        Exactly one of `ltan` and `ltdn` is given.
    comments : str, optional
        Your own notes on this block. quicksat keeps them and does not read them.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    altitude: LengthQty
    ltan: Annotated[
        Quantity | None, BeforeValidator(lambda v: _parse_node_time(v, "ltan"))
    ] = None
    ltdn: Annotated[
        Quantity | None, BeforeValidator(lambda v: _parse_node_time(v, "ltdn"))
    ] = None

    @model_validator(mode="after")
    def _one_node_time(self):
        """Checks that exactly one of the two node times is given."""
        if (self.ltan is None) == (self.ltdn is None):
            raise ValueError(
                'sso needs exactly one of ltan and ltdn, such as ltan: "10:30"'
            )
        return self

    @property
    def ascending_node_time(self) -> Quantity:
        """The local time of the ascending node: `ltan`, or `ltdn` 12 h away."""
        if self.ltan is not None:
            return self.ltan
        return (self.ltdn + Q_(12, "h")) % Q_(24, "h")

    @property
    def node_label(self) -> str:
        """The node time as the file gives it, such as `LTDN 10.5 h`."""
        if self.ltan is not None:
            return f"LTAN {self.ltan:.4g}"
        return f"LTDN {self.ltdn:.4g}"


ORBIT_FILES = ("tle_file", "omm_file", "trajectory_file")
"""The keys that name an orbit's file, in the `orbit` block and for a satellite
target."""


def _from_the_scenario_folder(path: Path | None, info: ValidationInfo) -> Path | None:
    """
    A file's path, with a relative one taken from the folder of the scenario file.

    Parameters
    ----------
    path : Path or None
        The path as the file gives it
    info : ValidationInfo
        Pydantic's validation info, whose context may hold `base_dir`

    Returns
    -------
    path : Path or None
        The path, from the scenario file's folder if it was relative
    """
    base_dir = (info.context or {}).get("base_dir")
    if path is not None and base_dir is not None and not path.is_absolute():
        return Path(base_dir) / path
    return path


class Orbit(Commented):
    """
    Where the orbit comes from: a TLE file, an OMM file, a sun-synchronous
    orbit, or a trajectory file.

    Exactly one of the four is given.

    Parameters
    ----------
    tle_file : Path, optional
        A file with exactly one TLE. A relative path is taken from the folder of
        the scenario file.
    omm_file : Path, optional
        A file with exactly one OMM element set, in KVN, XML, JSON or CSV. See
        `quicksat.orbit.omm`. A relative path is taken from the folder of the
        scenario file.
    sso : SsoOrbit, optional
        A sun-synchronous orbit. quicksat builds its TLE, with the epoch at the
        start of the run.
    trajectory_file : Path, optional
        A file of positions and velocities, which the run interpolates: ECSV,
        or a CCSDS OEM in KVN. See `quicksat.orbit.trajectory_files`. A
        relative path is taken from the folder of the scenario file.
    comments : str, optional
        Your own notes on this block. quicksat keeps them and does not read them.
    """

    model_config = ConfigDict(extra="forbid")

    tle_file: Path | None = None
    omm_file: Path | None = None
    sso: SsoOrbit | None = None
    trajectory_file: Path | None = None

    @model_validator(mode="before")
    @classmethod
    def _exactly_one_key(cls, data):
        """
        Checks that the orbit has exactly one source key, and that it is
        accepted. The comments are not a source.
        """
        accepted = sorted(name for name in cls.model_fields if name != COMMENTS)
        if not isinstance(data, dict):
            raise ValueError(f"orbit must have exactly one key, one of: {accepted}")
        keys = [str(key) for key in data if key != COMMENTS]
        if len(keys) != 1 or keys[0] not in accepted:
            raise ValueError(
                f"orbit must have exactly one key, one of: {accepted}. Got: {keys}"
            )
        return data

    @field_validator(*ORBIT_FILES)
    @classmethod
    def _relative_to_the_file(
        cls, path: Path | None, info: ValidationInfo
    ) -> Path | None:
        """Takes a relative path from the folder of the scenario file."""
        return _from_the_scenario_folder(path, info)


DEFAULT_CLEARANCE = Q_(100, "km")
"""A satellite target's `min_clearance`, when it gives none: the line of sight
then keeps above the atmosphere."""


class SatelliteTarget(Commented):
    """
    Another satellite, which an attitude or an articulation can point at.

    Its orbit comes from a file, read as the `orbit` block reads one: a TLE file,
    an OMM file, or a trajectory file. Exactly one of the three is given.

    Parameters
    ----------
    tle_file : Path, optional
        A file with one TLE or several, as CelesTrak gives a group of
        satellites. A relative path is taken from the folder of the scenario
        file.
    omm_file : Path, optional
        A file with one OMM element set or several, in KVN, XML, JSON or CSV. A
        relative path is taken from the folder of the scenario file.
    trajectory_file : Path, optional
        A file of positions and velocities, ECSV or CCSDS OEM, which the run
        interpolates. It must cover the whole run. A relative path is taken from
        the folder of the scenario file.
    satellite : str or int, optional
        Written `object` in the file. The element set to take from a TLE or OMM
        file that holds several: a satellite's name, or its catalogue number.
        Without it, the target's own name is looked for. It must match a file
        of one element set too. Not for a trajectory file, which holds one
        satellite.
    min_clearance : Quantity, optional
        The least height of the line between the two satellites above the WGS84
        ellipsoid, for the target to be in view. It sets the `rise` and `set`
        triggers. 0 or more, and `DEFAULT_CLEARANCE` by default.
    comments : str, optional
        Your own notes on this block. quicksat keeps them and does not read them.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    tle_file: Path | None = None
    omm_file: Path | None = None
    trajectory_file: Path | None = None
    satellite: str | int | None = Field(None, alias="object")
    min_clearance: LengthQty = DEFAULT_CLEARANCE

    @model_validator(mode="before")
    @classmethod
    def _one_file(cls, data):
        """Checks that the target names exactly one orbit file, and no `sso`."""
        if not isinstance(data, dict):
            raise ValueError(
                f"a satellite target needs exactly one of: {list(ORBIT_FILES)}"
            )
        if "sso" in data:
            raise ValueError(
                "a satellite target takes its orbit from a file: tle_file, omm_file "
                "or trajectory_file. sso builds an orbit for the scenario's own "
                "satellite."
            )
        files = [key for key in ORBIT_FILES if data.get(key) is not None]
        if len(files) != 1:
            raise ValueError(
                f"a satellite target needs exactly one of: {list(ORBIT_FILES)}. "
                f"Got: {files}"
            )
        return data

    @field_validator(*ORBIT_FILES)
    @classmethod
    def _relative_to_the_file(
        cls, path: Path | None, info: ValidationInfo
    ) -> Path | None:
        """Takes a relative path from the folder of the scenario file."""
        return _from_the_scenario_folder(path, info)

    @model_validator(mode="after")
    def _check(self):
        """Checks that `object` names a satellite, and only in an element set file."""
        if self.satellite is None:
            return self
        if self.trajectory_file is not None:
            raise ValueError(
                "object picks an element set from a TLE or OMM file. A trajectory "
                "file holds one satellite, so it takes no object."
            )
        if not str(self.satellite).strip():
            raise ValueError("object must give a satellite's name or catalogue number")
        return self

    @property
    def file(self) -> Path:
        """
        The file the orbit comes from, whichever kind it is.

        Returns
        -------
        path : Path
            The TLE, OMM or trajectory file
        """
        return cast(Path, self.tle_file or self.omm_file or self.trajectory_file)
