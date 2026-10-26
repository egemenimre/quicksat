# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
Pydantic and unit parsing helpers, shared by every input file.

"""

import re
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Annotated, ClassVar, Self

import pandas as pd
import yaml
from astropy.units import Quantity
from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    PlainSerializer,
    PrivateAttr,
    StringConstraints,
    ValidationError,
    ValidationInfo,
)

from quicksat import Q_, u

_LEADING_NUMBER = re.compile(r"^\s*[-+]?[\d_.]+(?:[eE][-+]?[\d_]+)?")
"""The number at the start of a quantity's text, before its unit."""


def _parse_quantity(v):
    """
    Reads a quantity's text, with underscores taken out of its number, and refuses text
    that is not a number and a unit.
    """
    if isinstance(v, u.Quantity):
        return v
    text = _LEADING_NUMBER.sub(lambda m: m.group().replace("_", ""), str(v), count=1)
    try:
        return Q_(text)
    except TypeError as exc:
        raise ValueError(str(exc)) from exc


def _serialize_quantity(v) -> str:
    """A quantity as text: its value and its unit."""
    return str(v)


def _check_unit_fraction(value: Quantity, info: ValidationInfo) -> Quantity:
    """Refuses a fraction of 0, or above 1, naming the field."""
    if not 0 < float(value.to(u.dimensionless_unscaled).value) <= 1:
        raise ValueError(
            f"{info.field_name} must be above 0 and at most 1 (100 %), got {value}"
        )
    return value


def non_negative_quantity(unit, label: str):
    """
    An Annotated Quantity type for one dimension, with non-negative values.

    Parameters
    ----------
    unit : Unit
        Any unit of the dimension, such as `u.kg`
    label : str
        The quantity's name, for the error messages

    Returns
    -------
    annotated : type
        A Pydantic field type
    """

    def _validate(v):
        if not v.unit.is_equivalent(unit):
            raise ValueError(f"Value must have {label} dimensions, got '{v}'")
        if v < 0:
            raise ValueError(f"{label.capitalize()} must not be negative, got '{v}'")
        return v

    return Annotated[
        u.Quantity,
        BeforeValidator(_parse_quantity),
        AfterValidator(_validate),
        PlainSerializer(_serialize_quantity, return_type=str),
    ]


def signed_quantity(unit, label: str):
    """
    An Annotated Quantity type for one dimension, with values of either sign.

    Parameters
    ----------
    unit : Unit
        Any unit of the dimension, such as `u.deg`
    label : str
        The quantity's name, for the error messages

    Returns
    -------
    annotated : type
        A Pydantic field type
    """

    def _validate(v):
        if not v.unit.is_equivalent(unit):
            raise ValueError(f"Value must have {label} dimensions, got '{v}'")
        return v

    return Annotated[
        u.Quantity,
        BeforeValidator(_parse_quantity),
        AfterValidator(_validate),
        PlainSerializer(_serialize_quantity, return_type=str),
    ]


MassQty = non_negative_quantity(u.kg, "mass")
"""Annotated Quantity type for non-negative masses. It refuses another dimension, such
as `100 W`."""

LengthQty = non_negative_quantity(u.m, "length")
"""Annotated Quantity type restricted to non-negative lengths."""

PowerQty = non_negative_quantity(u.W, "power")
"""Annotated Quantity type restricted to non-negative powers, such as `10 W`."""

EnergyQty = non_negative_quantity(u.W * u.h, "energy")
"""Annotated Quantity type for non-negative energies, such as `1024 W h`, with a space."""

AreaQty = non_negative_quantity(u.m**2, "area")
"""Annotated Quantity type restricted to non-negative areas, such as `0.2 m2`."""


def _parse_temperature(v):
    """
    Reads a temperature, with Celsius turned into kelvin. Any other dimension passes on,
    for the check to refuse.
    """
    v = _parse_quantity(v)
    if v.unit is None or v.unit.physical_type != "temperature":
        return v
    return v.to(u.K, equivalencies=u.temperature())


def _validate_temperature(v):
    """Refuses a value that is not a temperature, or is at or below 0 K."""
    if v.unit.physical_type != "temperature":
        raise ValueError(f"Value must have temperature dimensions, got '{v}'")
    if v <= 0 * u.K:
        raise ValueError(f"Temperature must be above 0 K, got '{v}'")
    return v


TemperatureQty = Annotated[
    u.Quantity,
    BeforeValidator(_parse_temperature),
    AfterValidator(_validate_temperature),
    PlainSerializer(_serialize_quantity, return_type=str),
]
"""Annotated Quantity type for absolute temperatures, held in kelvin.  Celsius, such as
`20 °C`, turns into kelvin as it is read, but kelvin is preferred. A temperature
difference must not use this type."""

AngleQty = non_negative_quantity(u.deg, "angle")
"""Annotated Quantity type for angles, which refuses a bare number."""

SignedAngleQty = signed_quantity(u.deg, "angle")
"""Annotated Quantity type for angles of either sign, such as `-90 deg`."""

SignedLengthQty = signed_quantity(u.m, "length")
"""Annotated Quantity type for lengths of either sign, such as an altitude below the
ellipsoid."""


PlainQty = Annotated[
    u.Quantity,
    BeforeValidator(_parse_quantity),
    PlainSerializer(_serialize_quantity, return_type=str),
]
"""Annotated Quantity type with no dimension check, for a field whose dimension a model
validator checks."""

DataRateQty = non_negative_quantity(u.bit / u.s, "data rate")
"""Annotated Quantity type for data rates, such as `800 Mbit/s`. `800 Mbps` does not
read."""

DataVolumeQty = non_negative_quantity(u.byte, "data volume")
"""Annotated Quantity type for data volumes, such as `2 TB` or `16 Tbit`."""

TimeQty = non_negative_quantity(u.s, "time")
"""Annotated Quantity type restricted to non-negative durations."""

AngularRateQty = non_negative_quantity(u.deg / u.s, "angular rate")
"""Annotated Quantity type for non-negative angular rates, such as `0.7 deg/s`."""

AngularAccelerationQty = non_negative_quantity(u.deg / u.s**2, "angular acceleration")
"""Annotated Quantity type for non-negative angular accelerations, such as `0.08
deg/s2`."""

FractionQty = non_negative_quantity(u.dimensionless_unscaled, "fraction")
"""Annotated Quantity type for dimensionless fractions: `5 %` and `0.05` are the same."""

UnitFractionQty = Annotated[FractionQty, AfterValidator(_check_unit_fraction)]
"""Annotated Quantity type for a fraction above 0 and at most 1, such as an efficiency."""

NoSpaceStr = Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^\S+$")]
"""String field that must not contain whitespace, used for the grouping axes."""

MomentumQty = non_negative_quantity(u.N * u.m * u.s, "angular momentum")
"""Annotated Quantity type for angular momentum, as a wheel stores it (`4 N*m*s`)."""

TorqueQty = non_negative_quantity(u.N * u.m, "torque")
"""Annotated Quantity type for torque. It cannot tell `0.2 N*m` from `0.2 J`."""

InertiaQty = non_negative_quantity(u.kg * u.m**2, "moment of inertia")
"""Annotated Quantity type for a moment of inertia (`264.7 kg*m**2`)."""


COMMENTS = "comments"
"""The key of the user's notes in every block. No named item may take it."""


class Commented(BaseModel):
    """
    A block of an input file that may hold the user's notes, under `comments`, which the
    editor keeps.

    Parameters
    ----------
    comments : str, optional
        The user's notes, which quicksat does not read
    """

    comments: str | None = None


class YamlFile(Commented):
    """
    An input file in YAML, read from a file or from text as UTF-8.

    It keeps the path and the text it was read from. A file's validators find its folder
    as `base_dir` in the validation context.
    """

    _EMPTY_ALLOWED: ClassVar[bool] = False
    """Whether empty text reads as a file with every key left out."""

    _source_file: Path | None = PrivateAttr(None)
    _source_text: str | None = PrivateAttr(None)

    @property
    def source_file(self) -> Path | None:
        """The file this was read from, or None."""
        return self._source_file

    @property
    def source_text(self) -> str | None:
        """The text this was read from, as written, or None."""
        return self._source_text

    @classmethod
    def from_yaml_file(cls, file_path: str | Path) -> Self:
        """
        Read the file.

        Parameters
        ----------
        file_path : str or Path
            The YAML file

        Returns
        -------
        model : Self
            The file's contents

        Raises
        ------
        FileNotFoundError
            If there is no such file
        ValueError
            If the file is empty, not a mapping, or fails the checks
        """
        return cls._from_file(file_path)

    @classmethod
    def from_yaml_text(cls, yaml_text: str) -> Self:
        """
        Read the file's contents from text.

        Parameters
        ----------
        yaml_text : str
            The YAML text

        Returns
        -------
        model : Self
            The contents

        Raises
        ------
        ValueError
            If the text is empty, not a mapping, or fails the checks
        """
        return cls._from_text(yaml_text)

    @classmethod
    def _from_file(cls, file_path: str | Path, **context) -> Self:
        """`from_yaml_file`, with more entries for the validation context."""
        path = Path(file_path)
        if not path.is_file():
            raise FileNotFoundError(f"File does not exist: {file_path}")
        model = cls._from_text(
            path.read_text(encoding="utf-8"), base_dir=path.parent, **context
        )
        model._source_file = path
        return model

    @classmethod
    def _from_text(cls, yaml_text: str, **context) -> Self:
        """`from_yaml_text`, with the entries of the validation context."""
        if not yaml_text and not cls._EMPTY_ALLOWED:
            raise ValueError("The text is empty.")
        data = yaml.safe_load(yaml_text)
        if data is None and cls._EMPTY_ALLOWED:
            data = {}
        if not isinstance(data, dict):
            raise ValueError("The file must be a mapping of keys to values.")
        model = cls.model_validate(data, context=context)
        model._source_text = yaml_text
        return model


def read_csv_rows(csv_path: str | Path, required: Iterable[str]) -> pd.DataFrame:
    """
    An input file in CSV, with every cell as text and the spaces around the cells and
    the names taken out.

    Parameters
    ----------
    csv_path : str or Path
        The CSV file
    required : iterable of str
        The columns the file must have

    Returns
    -------
    frame : pd.DataFrame
        One row per line after the header

    Raises
    ------
    FileNotFoundError
        If there is no such file
    ValueError
        If a required column is missing
    """
    path = Path(csv_path)
    if not path.is_file():
        raise FileNotFoundError(f"File does not exist: {csv_path}")
    raw = pd.read_csv(path, dtype=str, keep_default_na=False, skipinitialspace=True)
    raw.columns = [str(column).strip() for column in raw.columns]
    missing = [name for name in required if name not in raw.columns]
    if missing:
        raise ValueError(f"{path.name}: missing columns {missing}")
    return raw


def validated_rows[T](
    model: Callable[..., T], records: Iterable[dict], file_name: str
) -> list[T]:
    """
    Each row of a CSV file, read by a model.

    Parameters
    ----------
    model : callable
        The model of one row
    records : iterable of dict
        The rows' fields, in the file's order
    file_name : str
        The file's name, for the error message

    Returns
    -------
    rows : list
        One model per row

    Raises
    ------
    ValueError
        If a row fails the checks, naming the file and the row's line
    """
    rows = []
    for row_number, record in enumerate(records, start=2):
        try:
            rows.append(model(**record))
        except ValidationError as exc:
            raise ValueError(f"{file_name}, row {row_number}:\n{exc}") from exc
    return rows


def without_comments(value):
    """
    Takes the section's `comments` out of a mapping of named items, before the items are
    read.

    Parameters
    ----------
    value
        The mapping as the file gives it, or anything else, which passes on

    Returns
    -------
    value
        The mapping without `comments`

    Raises
    ------
    ValueError
        If `comments` holds anything but text
    """
    if not isinstance(value, dict) or COMMENTS not in value:
        return value
    if not (value[COMMENTS] is None or isinstance(value[COMMENTS], str)):
        raise ValueError(
            f"'{COMMENTS}' holds the notes on the whole section, so no item may "
            "take that name"
        )
    return {name: item for name, item in value.items() if name != COMMENTS}
