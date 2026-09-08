# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
Package for Pydantic and unit parsing helpers.

"""

from typing import Annotated

from pydantic import AfterValidator, BeforeValidator, PlainSerializer, StringConstraints

from quicksat import Q_, u


def is_quantity(quantity_text: str) -> bool:
    """
    Checks whether the `quantity_text` can be parsed as a valid `Quantity` object.

    Parameters
    ----------
    quantity_text : str
        Text that will be parsed as a `Quantity` object

    Returns
    -------
    is_quantity : bool
        `True` if text can be parsed, `False` otherwise
    """
    try:
        Q_(quantity_text)
    except Exception:
        return False
    else:
        return True


def _parse_quantity(v):
    """Pydantic BeforeValidator for Quantity objects."""
    if isinstance(v, u.Quantity):
        return v
    return Q_(str(v).replace("_", ""))


def _serialize_quantity(v) -> str:
    """Pydantic PlainSerializer for Quantity objects."""
    return str(v)


PydanticQty = Annotated[
    u.Quantity,
    BeforeValidator(_parse_quantity),
    PlainSerializer(_serialize_quantity, return_type=str),
]
"""Annotated Quantity type for use in Pydantic models.

Parses strings like '100 kg' into pint Quantity objects, and serializes them
back to strings.
"""


def _validate_mass(v):
    """Pydantic AfterValidator that requires a non-negative mass Quantity."""
    if not v.check("[mass]"):
        raise ValueError(f"Value must have mass dimensions, got '{v}'")
    if v.magnitude < 0:
        raise ValueError(f"Mass must not be negative, got '{v}'")
    return v


MassQty = Annotated[
    u.Quantity,
    BeforeValidator(_parse_quantity),
    AfterValidator(_validate_mass),
    PlainSerializer(_serialize_quantity, return_type=str),
]
"""Annotated Quantity type restricted to non-negative masses.

Rejects a dimensionally wrong entry such as '100 W' in a mass column, which a
plain float would have silently accepted.
"""

NoSpaceStr = Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^\S+$")]
"""String field that must not contain whitespace, used for the grouping axes."""
