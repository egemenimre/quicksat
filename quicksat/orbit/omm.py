# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
Element sets in CCSDS OMM, the Orbit Mean-Elements Message.

An OMM holds the same elements as a TLE, as named fields, such as
`MEAN_MOTION` and `BSTAR`. quicksat reads it in each of the forms in use, and
tells them apart by their first character:

- KVN, the CCSDS text form: `KEY = value` lines, with comments, and units in
  brackets that are not read. It starts with `CCSDS_OMM_VERS`.
- XML, the CCSDS XML form. It starts with `<`, and sgp4 reads it.
- JSON, as CelesTrak and Space-Track give it, with the same field names. It
  starts with `[` or `{`.
- CSV, as CelesTrak gives it, with a header line of field names. sgp4 reads
  it.

The file holds exactly one element set. Where the file gives them, the centre
must be the Earth, the frame TEME, the time system UTC, and the element theory
SGP4: other elements would not mean the same thing to SGP4. The elements then
go to sgp4's `omm.initialize`, which builds the same `Satrec` that a TLE gives.
The bookkeeping fields, such as `ELEMENT_SET_NO`, take a TLE's usual values
where the file leaves them out.

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
from quicksat.orbit.tle import Tle

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
"""The bookkeeping fields, with the values they take where the file leaves them
out. SGP4 does not use them to propagate."""

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
"""sgp4's factors from rev/day^2 and rev/day^3 to its own units, for writing."""


def _kvn_fields(text: str, path: Path) -> list[dict[str, str]]:
    """
    The fields of an OMM in KVN, which holds one element set.

    Parameters
    ----------
    text : str
        The file's text
    path : Path
        The file, for the messages

    Returns
    -------
    fields : list of dict
        One set of fields, by name
    """
    fields = {}
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if line and not line.startswith("COMMENT"):
            key, value = key_value(line, number, path)
            fields[key] = value
    return [fields]


def _fields(text: str, path: Path) -> list[dict[str, str]]:
    """
    The element sets in an OMM, in any of its forms, as text fields by name.

    Parameters
    ----------
    text : str
        The file's text
    path : Path
        The file, for the messages

    Returns
    -------
    fields : list of dict
        One set of fields for each element set in the file

    Raises
    ------
    ValueError
        If the file is none of the forms, or cannot be read as the one it starts
        like
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


def _checked(fields: dict[str, str], path: Path) -> dict[str, str]:
    """
    An element set's fields, checked, with the bookkeeping filled in and the
    epoch in the form sgp4 reads.

    Parameters
    ----------
    fields : dict
        The fields, as text by name
    path : Path
        The file, for the messages

    Returns
    -------
    fields : dict
        The fields that sgp4's `omm.initialize` takes

    Raises
    ------
    ValueError
        If the metadata names other elements than SGP4's, a field SGP4 needs is
        missing, or a value is not a number or an epoch
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


def read_omm_file(path: str | Path) -> Tle:
    """
    Read a file holding exactly one OMM element set. See the module notes.

    Parameters
    ----------
    path : str | Path
        Filepath of the OMM

    Returns
    -------
    tle : Tle
        The element set, ready for SGP4, named by its `OBJECT_NAME`

    Raises
    ------
    FileNotFoundError
        If the file does not exist
    ValueError
        If the file does not hold exactly one element set that SGP4 can use, or
        if SGP4 reports an error when it initialises from it
    """
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"File does not exist: {path}")
    element_sets = _fields(path.read_text(), path)
    if len(element_sets) != 1:
        raise ValueError(
            f"{path}: an OMM file holds exactly one element set here. Found "
            f"{len(element_sets)}."
        )
    fields = _checked(element_sets[0], path)
    satrec = Satrec()
    omm.initialize(satrec, fields, WGS72)
    if satrec.error != 0:
        raise ValueError(
            f"{path}: SGP4 rejected the elements with error code {satrec.error}: "
            f"{SGP4_ERRORS.get(satrec.error, 'unknown error')}"
        )
    return Tle(fields.get("OBJECT_NAME") or None, satrec)


def _object_id(designator: str) -> str:
    """
    A TLE's international designator, such as 20003C, as an OMM writes it,
    2020-003C.

    Parameters
    ----------
    designator : str
        The designator as sgp4 holds it

    Returns
    -------
    object_id : str
        In the OMM's form, or UNKNOWN where there is none
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
    Write an element set as an OMM in KVN, version 2.0.

    This writes out, for example, the TLE that quicksat builds for a
    sun-synchronous orbit, in a form that other tools read.

    Parameters
    ----------
    path : str | Path
        The file to write
    tle : Tle
        The element set
    creation_date : Time, optional
        The `CREATION_DATE`, now by default. Give one for a file that must not
        change from one run to the next.

    Returns
    -------
    path : Path
        The file written, with the elements at full precision
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
