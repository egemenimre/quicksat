# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
The payload's thermal file: its surfaces, its heat flows and the Earth's constants.

The file is `payload_thermal.yaml`, in the power folder beside the power system
file. It is optional: without it, the folder sizes power only.

    surfaces:
      radiator: {part: Radiator, absorptance: 0.20, emissivity: 0.85, temperature: 273 K}
      aperture:
        part: Aperture
        absorptance: 0.90
        emissivity: 0.90
        temperature: 273 K
        fixed_temperature: true
    heat_flows:
      platform interface: -3 W
      x-band rf: {idle: 0 W, imaging: 0 W, downlink: -5 W}
    earth: {albedo: 0.30, infrared: 237 W/m2}

A surface is defined as a solar panel is: it names a flat part of the 3D model,
or gives a normal and an area. A heat flow is positive into the payload. It is
one power for every mode, or a power for each payload mode.

Temperatures are read in kelvin, or in Celsius and turned into kelvin. Kelvin is
preferred.

This module reads and checks the file on its own. The parts are checked against
the scenario's model, and the flows' modes against the run, when the account is
worked out, in `quicksat.thermal.account`.

"""

import os
from pathlib import Path
from typing import Annotated, ClassVar

import yaml
from astropy.units import Quantity
from pydantic import (
    BeforeValidator,
    ConfigDict,
    Discriminator,
    Field,
    PrivateAttr,
    StrictBool,
    Tag,
    ValidationInfo,
    field_validator,
)

from quicksat import Q_, u
from quicksat.power.config import FlatItem
from quicksat.utils.parser_helpers import (
    Commented,
    FractionQty,
    TemperatureQty,
    check_unit_fraction,
    non_negative_quantity,
    signed_quantity,
    without_comments,
)

SignedPowerQty = signed_quantity(u.W, "power")
"""Annotated Quantity type for a power of either sign, such as a heat flow's
`-3 W`."""

FluxQty = non_negative_quantity(u.W / u.m**2, "flux")
"""Annotated Quantity type for a flux, such as the Earth's `237 W/m2`."""

HeatFlow = Annotated[
    Annotated[SignedPowerQty, Tag("power")]
    | Annotated[dict[str, SignedPowerQty], Tag("by mode")],
    Discriminator(lambda value: "by mode" if isinstance(value, dict) else "power"),
]
"""A heat flow: one power for every mode, or a power for each payload mode. A
mapping is read as the powers by mode, and anything else as one power, so that a
mistake gives one error."""

DEFAULT_ALBEDO = Q_(0.30, "")
"""The Earth's albedo, if the file gives none: the share of sunlight it reflects,
averaged over the globe."""

DEFAULT_INFRARED = Q_(237, "W/m2")
"""The Earth's infrared flux at its surface, if the file gives none, averaged
over the globe."""


class Surface(FlatItem):
    """
    A surface of the payload that absorbs and radiates heat: a radiator, or an
    aperture.

    It is a part of the 3D model, or a normal and an area, as a solar panel is.
    A surface from the model turns with an articulation above it, and the rest
    of the model can shade the sun on it.

    Parameters
    ----------
    part : str, optional
        The name of the model's node that holds the surface. Its triangles must
        all face one way. Give either `part`, or both `normal` and `area`.
    normal : tuple of float, optional
        The direction the surface faces, in body axes: a signed body axis such
        as `+x`, or three numbers, scaled to unit length
    area : Quantity, optional
        The surface's area, positive
    absorptance : Quantity
        The share of sunlight it absorbs, α, such as 0.20 for white paint, for
        the year being sized. Above 0 and at most 1.
    emissivity : Quantity
        The share of a black body's infrared it emits, ε, such as 0.85. It also
        absorbs this share of the Earth's infrared. Above 0 and at most 1.
    temperature : Quantity
        Its design temperature, in kelvin, such as `273 K`. A temperature in
        Celsius is turned into kelvin.
    fixed_temperature : bool, optional
        True when something else holds the surface at its temperature, such as
        a telescope's own heaters. False by default: the surface floats, which
        matters only for the equilibrium ΔT.
    comments : str, optional
        Your own notes on this block. quicksat keeps them and does not read them.
    """

    kind: ClassVar[str] = "surface"
    part_hint: ClassVar[str] = "the name of its face in the 3D model"

    absorptance: FractionQty
    emissivity: FractionQty
    temperature: TemperatureQty
    fixed_temperature: StrictBool = False

    @field_validator("absorptance", "emissivity")
    @classmethod
    def _fraction(cls, value: Quantity, info: ValidationInfo) -> Quantity:
        """Checks that the absorptance and the emissivity are in (0, 1]."""
        return check_unit_fraction(value, str(info.field_name))


class Earth(Commented):
    """
    The Earth's two constants: the sunlight it reflects and its own infrared.

    Parameters
    ----------
    albedo : Quantity, optional
        The share of sunlight that the Earth reflects, from 0 to 1. 0.30 by
        default.
    infrared : Quantity, optional
        The Earth's infrared flux, such as `237 W/m2`, the default
    comments : str, optional
        Your own notes on this block. quicksat keeps them and does not read them.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    albedo: FractionQty = DEFAULT_ALBEDO
    infrared: FluxQty = DEFAULT_INFRARED

    @field_validator("albedo")
    @classmethod
    def _albedo(cls, value: Quantity) -> Quantity:
        """Checks that the albedo is from 0 to 1."""
        if not 0 <= float(value.to(u.dimensionless_unscaled).value) <= 1:
            raise ValueError(f"albedo must be from 0 to 1 (100 %), got {value}")
        return value


class PayloadThermal(Commented):
    """
    The payload's thermal file: the surfaces, the heat flows and the Earth.

    Parameters
    ----------
    surfaces : dict of str to Surface
        The surfaces, each under a name of your choice. At least one.
    heat_flows : dict of str to Quantity or dict, optional
        The powers that cross the payload's boundary elsewhere than a surface,
        each under a name of your choice, positive into the payload. Each is
        one power, such as `-3 W`, or a power for each payload mode, such as
        `{idle: 0 W, downlink: -5 W}`. None by default.
    earth : Earth, optional
        The Earth's albedo and infrared, the defaults without it
    comments : str, optional
        Your own notes on the whole file. quicksat keeps them and does not read
        them. The sections `surfaces` and `heat_flows` may hold their own
        `comments` too, so no surface or flow may take that name.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    surfaces: Annotated[dict[str, Surface], BeforeValidator(without_comments)]
    heat_flows: Annotated[dict[str, HeatFlow], BeforeValidator(without_comments)] = (
        Field(default_factory=dict)
    )
    earth: Earth = Field(default_factory=Earth)

    _source_file: Path | None = PrivateAttr(None)
    _source_text: str | None = PrivateAttr(None)

    @property
    def source_file(self) -> Path | None:
        """
        The file the thermal file was read from.

        Returns
        -------
        path : Path or None
            None when it was read from text
        """
        return self._source_file

    @property
    def source_text(self) -> str | None:
        """
        The text the thermal file was read from, as written.

        Returns
        -------
        text : str or None
            None when it was built in code
        """
        return self._source_text

    @field_validator("surfaces")
    @classmethod
    def _name_surfaces(cls, surfaces: dict[str, Surface]) -> dict[str, Surface]:
        """Checks that there is a surface, and that no name is empty."""
        if not surfaces:
            raise ValueError("surfaces must define at least one surface")
        if any(not str(name).strip() for name in surfaces):
            raise ValueError("a surface's name must not be empty")
        return surfaces

    @field_validator("heat_flows")
    @classmethod
    def _name_flows(cls, flows: dict[str, HeatFlow]) -> dict[str, HeatFlow]:
        """Checks that no name is empty, and that a flow by mode has a mode."""
        for name, flow in flows.items():
            if not str(name).strip():
                raise ValueError("a heat flow's name must not be empty")
            if isinstance(flow, dict):
                if not flow:
                    raise ValueError(
                        f"heat flow '{name}' gives no mode: give one power, or a "
                        "power for each payload mode"
                    )
                if any(not str(mode).strip() for mode in flow):
                    raise ValueError(f"heat flow '{name}' has a mode with no name")
        return flows

    @property
    def flows_by_mode(self) -> dict[str, dict[str, Quantity]]:
        """
        The heat flows given by mode.

        Returns
        -------
        flows : dict of str to dict of str to Quantity
            Each flow's power by the payload mode's name, by the flow's name
        """
        return {
            name: flow
            for name, flow in self.heat_flows.items()
            if isinstance(flow, dict)
        }

    def flow_watts(self, mode: str) -> dict[str, float]:
        """
        Each heat flow's power in one payload mode.

        Parameters
        ----------
        mode : str
            The payload mode's name. Each flow given by mode must have it.

        Returns
        -------
        watts : dict of str to float
            In W, positive into the payload, by the flow's name
        """
        return {
            name: float((flow[mode] if isinstance(flow, dict) else flow).to_value(u.W))
            for name, flow in self.heat_flows.items()
        }

    @classmethod
    def from_yaml_file(cls, file_path: str | Path) -> "PayloadThermal":
        """
        Initialise the thermal file from a YAML file.

        Parameters
        ----------
        file_path : str | Path
            Path to the YAML file

        Returns
        -------
        thermal : PayloadThermal
            The thermal file's contents

        Raises
        ------
        FileNotFoundError
            If there is no such file
        """
        if not os.path.isfile(file_path):
            raise FileNotFoundError(f"File does not exist: {file_path}")
        path = Path(file_path)
        thermal = cls.from_yaml_text(path.read_text(encoding="utf-8"))
        thermal._source_file = path
        return thermal

    @classmethod
    def from_yaml_text(cls, yaml_text: str) -> "PayloadThermal":
        """
        Initialise the thermal file from YAML text.

        Parameters
        ----------
        yaml_text : str
            Text containing the thermal file (YAML)

        Returns
        -------
        thermal : PayloadThermal
            The thermal file's contents

        Raises
        ------
        ValueError
            If the text is empty, or is not a mapping of keys to values
        """
        if not yaml_text:
            raise ValueError("Text content is None.")
        data = yaml.safe_load(yaml_text)
        if not isinstance(data, dict):
            raise ValueError("A thermal file must be a mapping of keys to values.")
        thermal = cls.model_validate(data)
        thermal._source_text = yaml_text
        return thermal
