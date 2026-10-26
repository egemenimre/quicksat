# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
The scenario's orbit and its targets, as the scenario file gives them.

A relative path is taken from the scenario file's folder.
`docs/scenario/scenario_ref.ipynb`, under "The orbit", explains each source.

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
        Height above the WGS84 ellipsoid, by default 0 m
    min_elevation : Quantity, optional
        The elevation at which the satellite rises and sets, by default 5 deg
    comments : str, optional
        The user's notes, which quicksat does not read
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
    A node's local time, from 0 to 24 h, from a quoted `"10:30"` or a quantity. A bare
    number gets an error that asks for quotes, since YAML reads `10:30` as 630.
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
    A circular sun-synchronous orbit, whose TLE quicksat builds with its epoch at the
    run's start. See `quicksat.orbit.sso`.

    Parameters
    ----------
    altitude : Quantity
        The distance from the Earth's centre less `R_EARTH`, averaged over one orbit,
        positive
    ltan : Quantity, optional
        The ascending node's local mean time, `"10:30"` in quotes or `10.5 h`
    ltdn : Quantity, optional
        The descending node's, in place of `ltan`, 12 h apart
    comments : str, optional
        The user's notes, which quicksat does not read
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
"""The keys that name an orbit's file, for the orbit and the satellite targets."""


def _from_the_scenario_folder(path: Path | None, info: ValidationInfo) -> Path | None:
    """
    A file's path, with a relative one taken from the scenario file's folder, the
    context's `base_dir`.
    """
    base_dir = (info.context or {}).get("base_dir")
    if path is not None and base_dir is not None and not path.is_absolute():
        return Path(base_dir) / path
    return path


class Orbit(Commented):
    """
    Where the orbit comes from: exactly one of a TLE file, an OMM file, a
    sun-synchronous orbit, or a trajectory file.

    Parameters
    ----------
    tle_file : Path, optional
        A file with exactly one TLE
    omm_file : Path, optional
        A file with exactly one OMM element set, in KVN, XML, JSON or CSV
    sso : SsoOrbit, optional
        A sun-synchronous orbit
    trajectory_file : Path, optional
        A file of states, in ECSV or a CCSDS OEM in KVN
    comments : str, optional
        The user's notes, which quicksat does not read
    """

    model_config = ConfigDict(extra="forbid")

    tle_file: Path | None = None
    omm_file: Path | None = None
    sso: SsoOrbit | None = None
    trajectory_file: Path | None = None

    @model_validator(mode="before")
    @classmethod
    def _exactly_one_key(cls, data):
        """Checks the orbit has exactly one known source key."""
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
        """Takes a relative path from the scenario file's folder."""
        return _from_the_scenario_folder(path, info)


DEFAULT_CLEARANCE = Q_(100, "km")
"""A satellite target's `min_clearance` when it gives none, which keeps the line of
sight above the atmosphere."""


class SatelliteTarget(Commented):
    """
    Another satellite, which an attitude or an articulation can point at, with its orbit
    from exactly one file.

    Parameters
    ----------
    tle_file : Path, optional
        A file with one TLE or several
    omm_file : Path, optional
        A file with one OMM element set or several
    trajectory_file : Path, optional
        A file of states, in ECSV or a CCSDS OEM, covering the whole run
    satellite : str or int, optional
        Written `object`: the satellite's name or catalogue number, in a file of element
        sets. By default, the target's name
    min_clearance : Quantity, optional
        The line of sight's least height above the ellipsoid, by default
        `DEFAULT_CLEARANCE`
    comments : str, optional
        The user's notes, which quicksat does not read
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
        """Checks the target names exactly one orbit file, and no `sso`."""
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
        """Takes a relative path from the scenario file's folder."""
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
        """The TLE, OMM or trajectory file the orbit comes from."""
        return cast(Path, self.tle_file or self.omm_file or self.trajectory_file)
