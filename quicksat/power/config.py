# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
The power generation file: the solar panels, their efficiencies and losses.

The file is `power_generation.yaml`. Each panel either names a part of the
scenario's 3D model, which gives its area and its normal, or gives a normal and
an area itself:

    cell_efficiency: 30 %
    loss_factor: 0.80
    panels:
      wing +y inner: {part: Wing +y inner cells, fill_ratio: 85 %}
      side +x: {normal: +x, area: 0.2 m2, fill_ratio: 80 %}
    self_shadowing: {enabled: true, points: 512}

This module reads and checks the file on its own. The parts are checked against
the scenario's model when the generation is worked out, in
`quicksat.power.generation`.

"""

import os
from pathlib import Path
from typing import Annotated

import numpy as np
import yaml
from astropy.units import Quantity
from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    PrivateAttr,
    StrictBool,
    ValidationInfo,
    field_validator,
    model_validator,
)

from quicksat import u
from quicksat.orbit.attitude import axis_vector
from quicksat.utils.parser_helpers import AreaQty, FractionQty

DEFAULT_POINTS = 512
"""Sample points on each panel for the self-shadowing, if the file gives none.
In the prototype, 512 points kept the lit fraction within 0.012 of the exact one,
and the energy within 0.01%."""

AXES = ("+x", "-x", "+y", "-y", "+z", "-z")
"""The signed body axes that a normal can be written as."""


def _read_normal(value) -> tuple[float, float, float] | None:
    """
    A panel's normal as a unit vector, from a signed body axis or three numbers.

    Parameters
    ----------
    value : str, list or None
        A signed body axis such as `+x`, or three numbers in body axes, such as
        `[0, 1, -1]`, scaled here to unit length

    Returns
    -------
    normal : tuple of float or None
        The unit vector, or None if no normal is given

    Raises
    ------
    ValueError
        If the value is neither form, or is three zeros
    """
    if value is None:
        return None
    if isinstance(value, str):
        axis = value.strip()
        if axis not in AXES:
            raise ValueError(
                f"normal must be a signed body axis, one of {list(AXES)}, or three "
                f"numbers, got '{value}'"
            )
        x, y, z = axis_vector(axis)
        return (float(x), float(y), float(z))
    try:
        vector = np.array(value, dtype=float)
    except (TypeError, ValueError):
        vector = np.empty(0)
    if vector.shape != (3,) or not np.all(np.isfinite(vector)):
        raise ValueError(
            f"normal must be a signed body axis, such as +x, or three numbers, "
            f"got {value!r}"
        )
    length = float(np.linalg.norm(vector))
    if length == 0:
        raise ValueError("normal must not be three zeros")
    x, y, z = vector / length
    return (float(x), float(y), float(z))


def _check_unit_fraction(value: Quantity, name: str) -> Quantity:
    """
    Checks that a fraction is above 0 and at most 1.

    Parameters
    ----------
    value : Quantity
        The fraction, dimensionless
    name : str
        The field's name, for the error message

    Returns
    -------
    value : Quantity
        The fraction, unchanged

    Raises
    ------
    ValueError
        If the fraction is 0, or above 1
    """
    if not 0 < float(value.to(u.dimensionless_unscaled).value) <= 1:
        raise ValueError(f"{name} must be above 0 and at most 1 (100 %), got {value}")
    return value


class Panel(BaseModel):
    """
    A solar panel: a part of the 3D model, or a normal and an area.

    A panel from the model takes its area and its normal from the part's
    triangles. It turns with an articulation above it in the model, and it can
    be shaded by the rest of the model. A typed-in panel stays fixed in body
    axes. It is never shaded and shades nothing.

    Parameters
    ----------
    part : str, optional
        The name of the model's node that holds the cells. Its triangles must all
        face one way. Give either `part`, or both `normal` and `area`.
    normal : tuple of float, optional
        The direction the cells face, in body axes: a signed body axis such as
        `+x`, or three numbers, scaled to unit length
    area : Quantity, optional
        The panel's area, positive
    fill_ratio : Quantity
        The share of the area that the cells cover, above 0 and at most 1
    """

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    part: str | None = None
    normal: Annotated[
        tuple[float, float, float] | None, BeforeValidator(_read_normal)
    ] = None
    area: AreaQty | None = None
    fill_ratio: FractionQty

    @field_validator("fill_ratio")
    @classmethod
    def _fraction(cls, value: Quantity, info: ValidationInfo) -> Quantity:
        """Checks that the fill ratio is above 0 and at most 1."""
        return _check_unit_fraction(value, str(info.field_name))

    @model_validator(mode="after")
    def _one_kind(self):
        """Checks that the panel is either a part, or a normal and an area."""
        typed = (self.normal is not None, self.area is not None)
        if self.part is not None:
            if any(typed):
                raise ValueError(
                    "a panel gives either part, or normal and area, not both: the "
                    "part gives its own normal and area"
                )
            if not self.part.strip():
                raise ValueError("part must not be empty")
        elif not all(typed):
            raise ValueError(
                "a panel needs either part, the name of its cells in the 3D model, "
                "or both normal and area"
            )
        elif self.area is not None and self.area.value == 0:
            raise ValueError("area must be above zero")
        return self

    @property
    def from_model(self) -> bool:
        """
        Whether the panel is a part of the 3D model.

        Returns
        -------
        from_model : bool
            True for a panel that names a part, False for a typed-in one
        """
        return self.part is not None


class SelfShadowing(BaseModel):
    """
    The switch for the self-shadowing, and how finely it samples each panel.

    Parameters
    ----------
    enabled : bool
        Whether parts of the model may shade the panels. Required.
    points : int, optional
        Sample points on each panel, 512 by default. More points give a finer
        lit fraction, and take longer.
    """

    model_config = ConfigDict(extra="forbid")

    enabled: StrictBool
    points: int = Field(DEFAULT_POINTS, gt=0)


class PowerGeneration(BaseModel):
    """
    The power generation file: the panels, their efficiencies and losses.

    The power of a panel is the solar flux × its area × its fill ratio × the cell
    efficiency × the loss factor × the cosine of the sun's angle to its normal.
    It is scaled by the light from the sun that the Earth does not hide, and by
    the panel's lit fraction when the self-shadowing is on.

    Parameters
    ----------
    cell_efficiency : Quantity
        The cells' efficiency, at their working temperature. Above 0 and at most
        1, such as `30 %` or `0.30`.
    loss_factor : Quantity
        All other losses, as the share of the power left: wiring, the power
        converter, temperature, cell mismatch and ageing, for the year being
        sized. Above 0 and at most 1, such as `0.80`.
    panels : dict of str to Panel
        The panels, each under a name of your choice. At least one.
    self_shadowing : SelfShadowing, optional
        Whether the 3D model shades the panels. Off without it.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    cell_efficiency: FractionQty
    loss_factor: FractionQty
    panels: dict[str, Panel]
    self_shadowing: SelfShadowing | None = None

    _source_file: Path | None = PrivateAttr(None)

    @property
    def source_file(self) -> Path | None:
        """
        The file the generation was read from.

        Returns
        -------
        path : Path or None
            None when it was read from text
        """
        return self._source_file

    @property
    def shading(self) -> bool:
        """
        Whether the self-shadowing is on.

        Returns
        -------
        shading : bool
        """
        return self.self_shadowing is not None and self.self_shadowing.enabled

    @field_validator("cell_efficiency", "loss_factor")
    @classmethod
    def _fraction(cls, value: Quantity, info: ValidationInfo) -> Quantity:
        """Checks that the efficiency and the loss factor are in (0, 1]."""
        return _check_unit_fraction(value, str(info.field_name))

    @field_validator("panels")
    @classmethod
    def _name_panels(cls, panels: dict[str, Panel]) -> dict[str, Panel]:
        """Checks that there is a panel, and that no name is empty."""
        if not panels:
            raise ValueError("panels must define at least one panel")
        if any(not str(name).strip() for name in panels):
            raise ValueError("a panel's name must not be empty")
        return panels

    @classmethod
    def from_yaml_file(cls, file_path: str | Path) -> "PowerGeneration":
        """
        Initialise the power generation from a YAML file.

        Parameters
        ----------
        file_path : str | Path
            Path to the YAML file

        Returns
        -------
        generation : PowerGeneration
            The power generation from the file

        Raises
        ------
        FileNotFoundError
            If there is no such file
        """
        if not os.path.isfile(file_path):
            raise FileNotFoundError(f"File does not exist: {file_path}")
        path = Path(file_path)
        generation = cls.from_yaml_text(path.read_text())
        generation._source_file = path
        return generation

    @classmethod
    def from_yaml_text(cls, yaml_text: str) -> "PowerGeneration":
        """
        Initialise the power generation from YAML text.

        Parameters
        ----------
        yaml_text : str
            Text containing the power generation (YAML)

        Returns
        -------
        generation : PowerGeneration
            The power generation from the text

        Raises
        ------
        ValueError
            If the text is empty, or is not a mapping of keys to values
        """
        if not yaml_text:
            raise ValueError("Text content is None.")
        data = yaml.safe_load(yaml_text)
        if not isinstance(data, dict):
            raise ValueError(
                "A power generation file must be a mapping of keys to values."
            )
        return cls.model_validate(data)
