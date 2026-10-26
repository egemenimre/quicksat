# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
Element sets in CCSDS OMM, the Orbit Mean-Elements Message, in KVN, XML, JSON or CSV.

The file holds one element set or several. The metadata, where given, must name the
Earth, TEME, UTC and SGP4. sgp4's `omm.initialize` then builds the same `Satrec` that a
TLE gives. `docs/scenario/scenario_ref.ipynb`, under "An OMM file", explains the forms.

"""

import io
import json
import re
from pathlib import Path

import numpy as np
from astropy.time import Time
from sgp4 import omm
from sgp4.api import SGP4_ERRORS, WGS72, Satrec

from quicksat.orbit.ccsds import key_value, normalised_epoch
from quicksat.orbit.tle import Tle, pick_element_set

THEORIES = ("SGP4", "SGP/SGP4")
"""The `MEAN_ELEMENT_THEORY` values read: the elements must be SGP4's."""

REQUIRED = (
    "EPOCH",
    "MEAN_MOTION",
    "ECCENTRICITY",
    "INCLINATION",
    "RA_OF_ASC_NODE",
    "ARG_OF_PERICENTER",
    "MEAN_ANOMALY",
    "BSTAR",
)
"""The fields SGP4 needs. Without `BSTAR`, the drag would be lost."""

DEFAULTS = {
    "OBJECT_ID": "",
    "CLASSIFICATION_TYPE": "U",
    "EPHEMERIS_TYPE": "0",
    "NORAD_CAT_ID": "0",
    "ELEMENT_SET_NO": "999",
    "REV_AT_EPOCH": "0",
    "MEAN_MOTION_DOT": "0",
    "MEAN_MOTION_DDOT": "0",
}
"""The bookkeeping fields' values where the file leaves them out. SGP4 does not use
them."""

_EXPECTED = {
    "CENTER_NAME": ("EARTH",),
    "REF_FRAME": ("TEME",),
    "TIME_SYSTEM": ("UTC",),
    "MEAN_ELEMENT_THEORY": THEORIES,
}
"""What each metadata field must say, where the file gives it."""

_OBJECT_ID = re.compile(r"^\d{4}-\d{3}[A-Z]{0,3}$")
"""An international designator, such as 2020-003C."""

_NDOT_UNITS = 1036800.0 / np.pi
_NDDOT_UNITS = 2985984000.0 / 2.0 / np.pi
"""sgp4's factors from rev/day^2 and rev/day^3 to its own units."""


def _kvn_fields(text: str, path: Path) -> list[dict[str, str]]:
    """The one element set of an OMM in KVN, as text fields."""
    fields = {}
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if line and not line.startswith("COMMENT"):
            key, value = key_value(line, number, path)
            fields[key] = value
    return [fields]


def _fields(text: str, path: Path) -> list[dict[str, str]]:
    """
    The element sets of an OMM in any form, as text fields, told apart by the first
    character.
    """
    start = text.lstrip()
    try:
        if start.startswith("CCSDS_OMM_VERS"):
            return _kvn_fields(text, path)
        if start.startswith("<"):
            return list(omm.parse_xml(io.StringIO(text)))
        if start.startswith(("[", "{")):
            data = json.loads(text)
            records = data if isinstance(data, list) else [data]
            return [
                {
                    key: "" if value is None else str(value)
                    for key, value in record.items()
                }
                for record in records
            ]
        header = start.splitlines()[0] if start else ""
        if "MEAN_MOTION" in header:
            return list(omm.parse_csv(io.StringIO(start)))
    except (ValueError, AttributeError, TypeError) as error:
        # sgp4's XML reader fails with an AttributeError or a TypeError on a
        # segment that lacks a block
        raise ValueError(f"{path}: the OMM cannot be read: {error}") from error
    raise ValueError(
        f"{path}: not an OMM that quicksat reads. KVN starts with CCSDS_OMM_VERS, "
        "XML with '<', JSON with '[' or '{', and CSV with a header line of field "
        "names."
    )


def _checked(fields: dict[str, str], path: str | Path) -> dict[str, str]:
    """
    An element set's fields, checked, with the bookkeeping filled in, as sgp4's
    `omm.initialize` takes them.
    """
    fields = {key.strip().upper(): str(value).strip() for key, value in fields.items()}
    for key, accepted in _EXPECTED.items():
        value = fields.get(key, "")
        if value and value.upper() not in accepted:
            raise ValueError(
                f"{path}: {key} = {value}, but SGP4's elements need "
                f"{' or '.join(accepted)}"
            )
    if not fields.get("MEAN_MOTION") and fields.get("SEMI_MAJOR_AXIS"):
        raise ValueError(
            f"{path}: the OMM gives SEMI_MAJOR_AXIS, but SGP4's elements give "
            "MEAN_MOTION"
        )
    missing = [key for key in REQUIRED if not fields.get(key)]
    if missing:
        raise ValueError(f"{path}: the OMM has no {', '.join(missing)}")
    checked = DEFAULTS | {key: value for key, value in fields.items() if value}
    # sgp4 shortens an international designator, such as 2020-003C, by place,
    # so anything else would come out mangled
    if not _OBJECT_ID.match(checked["OBJECT_ID"]):
        checked["OBJECT_ID"] = ""
    for key in REQUIRED[1:] + ("MEAN_MOTION_DOT", "MEAN_MOTION_DDOT"):
        try:
            float(checked[key])
        except ValueError as error:
            raise ValueError(
                f"{path}: {key} = {checked[key]} is not a number"
            ) from error
    try:
        epoch = Time(normalised_epoch(checked["EPOCH"]), scale="utc", precision=6)
    except ValueError as error:
        raise ValueError(
            f"{path}: EPOCH = {checked['EPOCH']} is not an epoch"
        ) from error
    # sgp4 reads only this form: a date, with the seconds' fraction
    checked["EPOCH"] = str(epoch.isot)
    return checked


def read_omm_sets(path: str | Path) -> list[Tle]:
    """
    Read every element set in an OMM file.

    Parameters
    ----------
    path : str or Path
        The OMM file

    Returns
    -------
    tles : list of Tle
        The element sets, each named by its `OBJECT_NAME`, in the file's order

    Raises
    ------
    FileNotFoundError
        If the file does not exist
    ValueError
        If the file holds none, or one that SGP4 cannot use
    """
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"File does not exist: {path}")
    element_sets = _fields(path.read_text(), path)
    if not element_sets:
        raise ValueError(f"{path}: the OMM holds no element set")
    tles = []
    for number, raw in enumerate(element_sets, start=1):
        where = path if len(element_sets) == 1 else f"{path}, element set {number}"
        fields = _checked(raw, where)
        satrec = Satrec()
        omm.initialize(satrec, fields, WGS72)
        if satrec.error != 0:
            raise ValueError(
                f"{where}: SGP4 rejected the elements with error code "
                f"{satrec.error}: {SGP4_ERRORS.get(satrec.error, 'unknown error')}"
            )
        tles.append(Tle(fields.get("OBJECT_NAME") or None, satrec))
    return tles


def read_omm_file(path: str | Path, satellite: str | int | None = None) -> Tle:
    """
    Read one element set from an OMM file: its only one, or the satellite asked for, as
    `pick_element_set` chooses.

    Parameters
    ----------
    path : str or Path
        The OMM file
    satellite : str or int, optional
        The satellite's `OBJECT_NAME` or `NORAD_CAT_ID`, for a file of several

    Returns
    -------
    tle : Tle
        The element set, named by its `OBJECT_NAME`

    Raises
    ------
    FileNotFoundError
        If the file does not exist
    ValueError
        If an element set is unusable, or the one asked for is missing
    """
    return pick_element_set(read_omm_sets(path), satellite, path)


def _object_id(designator: str) -> str:
    """
    A TLE's international designator in an OMM's form, such as 2020-003C, or UNKNOWN.
    """
    designator = designator.strip()
    if len(designator) < 5 or not designator[:5].isdigit():
        return "UNKNOWN"
    # TLE years run from 1957 to 2056
    year = int(designator[:2])
    year += 1900 if year >= 57 else 2000
    return f"{year}-{designator[2:]}"


def write_omm_file(  # noqa: V103
    path: str | Path,
    tle: Tle,
    creation_date: Time | None = None,
) -> Path:
    """
    Write an element set as an OMM in KVN, version 2.0, at full precision.

    Parameters
    ----------
    path : str or Path
        The file to write
    tle : Tle
        The element set
    creation_date : Time, optional
        The `CREATION_DATE`, by default now

    Returns
    -------
    path : Path
        The file written
    """
    path = Path(path)
    s = tle.satrec
    created = Time.now() if creation_date is None else creation_date

    def number(value: float) -> str:
        # at full precision, and as a plain float rather than a numpy one
        return repr(float(value))

    def degrees(radians: float) -> str:
        return number(np.degrees(radians))

    lines = [
        "CCSDS_OMM_VERS = 2.0",
        f"CREATION_DATE = {Time(created.utc, precision=0).isot}",
        "ORIGINATOR = quicksat",
        "",
        f"OBJECT_NAME = {tle.name or 'UNKNOWN'}",
        f"OBJECT_ID = {_object_id(s.intldesg)}",
        "CENTER_NAME = EARTH",
        "REF_FRAME = TEME",
        "TIME_SYSTEM = UTC",
        "MEAN_ELEMENT_THEORY = SGP4",
        "",
        f"EPOCH = {Time(tle.epoch.utc, precision=6).isot}",
        f"MEAN_MOTION = {number(s.no_kozai * 720 / np.pi)} [rev/day]",
        f"ECCENTRICITY = {number(s.ecco)}",
        f"INCLINATION = {degrees(s.inclo)} [deg]",
        f"RA_OF_ASC_NODE = {degrees(s.nodeo)} [deg]",
        f"ARG_OF_PERICENTER = {degrees(s.argpo)} [deg]",
        f"MEAN_ANOMALY = {degrees(s.mo)} [deg]",
        "",
        f"EPHEMERIS_TYPE = {s.ephtype}",
        f"CLASSIFICATION_TYPE = {s.classification}",
        f"NORAD_CAT_ID = {s.satnum}",
        f"ELEMENT_SET_NO = {s.elnum}",
        f"REV_AT_EPOCH = {s.revnum}",
        f"BSTAR = {number(s.bstar)} [1/ER]",
        f"MEAN_MOTION_DOT = {number(s.ndot * _NDOT_UNITS)} [rev/day**2]",
        f"MEAN_MOTION_DDOT = {number(s.nddot * _NDDOT_UNITS)} [rev/day**3]",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n")
    return path
