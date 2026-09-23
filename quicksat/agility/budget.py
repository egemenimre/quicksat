# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
Attitude agility: how long a rest-to-rest slew takes, and whether it fits.

The wheel geometry collapses to two numbers per axis -- how much momentum and how
much torque the assembly can put about it -- and the slew maths takes it from
there. There is no distribution matrix and no per-wheel loading: a sizing model
wants to know whether 40 degrees fits the time allowed, not how the command is
shared out.

Roll and pitch run the same machinery. The wheel pyramid's symmetry axis is along
yaw, which puts both of them in the base plane, so they differ only in the
spacecraft's inertia about them. Hence one model that takes the axis as an
argument rather than two that would drift apart.

"""

import os
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, cast

import numpy as np
import pandas as pd
import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from quicksat import Q_
from quicksat.agility.report import tabulate

if TYPE_CHECKING:  # a type annotation only, so quicksat.mass stays unimported
    from quicksat.mass.budget import MassBudget
from quicksat.utils.orbit import Orbit
from quicksat.utils.parser_helpers import (
    AngleQty,
    FractionQty,
    InertiaQty,
    LengthQty,
    MomentumQty,
    TimeQty,
    TorqueQty,
)

DEFAULT_SLEW_ANGLES = (5, 10, 15, 20, 40, 45, 60, 90)
"""Slew angles reported by `slew_table` when none are given, in degrees."""


class Axis(str, Enum):
    """The axis a slew is flown about."""

    ROLL = "roll"
    """Across track. Inertia from the cross-track and nadir dimensions."""

    PITCH = "pitch"
    """Along track. Inertia from the along-track and nadir dimensions."""


class Profile(str, Enum):
    """Which limit binds, and so which rate profile the slew follows."""

    TRIANGULAR = "triangular"
    """Torque limited: accelerate to the midpoint, decelerate to the end."""

    TRAPEZOIDAL = "trapezoidal"
    """Momentum limited: the wheels saturate and the slew coasts at max rate."""


class Body(BaseModel):
    """
    A bus envelope, as a uniform rectangular box.

    Parameters
    ----------
    x : Quantity
        Along-track dimension
    y : Quantity
        Cross-track dimension
    z : Quantity
        Nadir dimension
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    x: LengthQty
    y: LengthQty
    z: LengthQty


class PerAxis(BaseModel):
    """
    A value for each slew axis.

    Parameters
    ----------
    roll : Quantity or float
        The roll figure
    pitch : Quantity or float
        The pitch figure
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    roll: InertiaQty | Annotated[float, Field(ge=1.0)]
    pitch: InertiaQty | Annotated[float, Field(ge=1.0)]


class InertiaCase(BaseModel):
    """
    One spacecraft, one set of mass properties.

    A case is **either** an envelope estimate -- a box and a per-axis appendage
    uplift, whose inertia follows whatever mass the mass budget reports -- **or**
    a stated inertia, as a mass properties report gives it. Never both, so there
    is never a question which of the two produced a number, and never neither.

    The two behave differently once the spacecraft changes, which is the reason
    to keep them apart: an envelope inertia tracks the mass automatically, a
    stated one is a fixed number and nothing checks it still applies.

    Parameters
    ----------
    body : Body, optional
        The bus envelope. With `appendage_factor`, makes this an envelope case
    appendage_factor : PerAxis, optional
        Inertia uplift for arrays, radiator and booms, per axis
    propellant : Quantity
        Percentage of the propellant load aboard, picking the mission point at
        which the mass budget is read. Envelope cases only
    inertia : PerAxis, optional
        Stated moment of inertia per axis. Makes this a stated case
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    body: Body | None = None
    appendage_factor: PerAxis | None = None
    propellant: FractionQty = Q_(100, "percent")
    inertia: PerAxis | None = None

    @property
    def is_envelope(self) -> bool:
        """Whether this case estimates its inertia from a box."""
        return self.inertia is None

    @model_validator(mode="after")
    def _exactly_one_shape(self):
        """
        Checks the case is an envelope or a stated inertia, not both or neither.

        Reports which keys were found rather than failing as an unmatched union,
        so a typo in `appendage_factor` reads as a missing envelope rather than
        as the case matching no shape at all.
        """
        envelope = [
            name
            for name in ("body", "appendage_factor")
            if getattr(self, name) is not None
        ]
        if self.inertia is not None:
            if envelope:
                raise ValueError(
                    f"A case states an inertia and also carries {envelope}. It has "
                    "to be one or the other: a stated inertia does not follow the "
                    "mass, so the two would disagree the moment the mass moved"
                )
        elif len(envelope) < 2:
            missing = sorted({"body", "appendage_factor"} - set(envelope))
            raise ValueError(
                f"A case needs either a stated 'inertia' or a full envelope. "
                f"Found {envelope or 'nothing'}, missing {missing}"
            )
        return self


class WheelAssembly(BaseModel):
    """
    A pyramid of reaction wheels, symmetry axis along yaw.

    `momentum_use_factor` and `torque_derating` are policy rather than hardware:
    the remainder of each is held back for disturbance storage and for control
    authority during the slew. Both belong here rather than in the wheel's
    nameplate figures, which are what the vendor sells.

    Parameters
    ----------
    count : int
        Number of wheels
    elevation : Quantity
        Angle of each wheel above the pyramid base plane
    momentum : Quantity
        Nameplate momentum storage, per wheel
    torque : Quantity
        Nameplate torque, per wheel
    momentum_use_factor : Quantity
        Fraction of nameplate momentum available for slewing
    torque_derating : Quantity
        Fraction of nameplate torque available for slewing
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    count: Annotated[int, Field(ge=1)]
    elevation: AngleQty
    momentum: MomentumQty
    torque: TorqueQty
    momentum_use_factor: FractionQty
    torque_derating: FractionQty


class AgilityConfig(BaseModel):
    """
    The agility inputs: what is slewed, what slews it, and the time allowed.

    The time allowed for a manoeuvre is deliberately absent: that is a question
    asked of a spacecraft, not a property of one, so it is supplied at the call.

    Parameters
    ----------
    inertia_cases : dict of str to InertiaCase
        Mass properties cases, keyed by whatever names suit. Nothing in the code
        matches on them
    wheels : WheelAssembly
        The wheel pyramid and its use policy
    settling_time : Quantity
        What the platform needs after a slew before the payload can work
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    inertia_cases: dict[str, InertiaCase]
    wheels: WheelAssembly
    settling_time: TimeQty

    def for_case(self, name: str) -> InertiaCase:
        """
        Mass properties for one named case.

        An unlisted name is an error rather than a silent fallback, which would
        quietly answer for a spacecraft nobody asked about.

        Parameters
        ----------
        name : str
            Case name, as written in the config

        Returns
        -------
        case : InertiaCase
            That case's mass properties

        Raises
        ------
        KeyError
            If no case of that name is configured
        """
        case = self.inertia_cases.get(name)
        if case is None:
            known = ", ".join(sorted(self.inertia_cases)) or "none"
            raise KeyError(f"No inertia case named '{name}'. Configured: {known}")
        return case

    @classmethod
    def from_yaml_file(cls, file_path: str | Path) -> "AgilityConfig":
        """
        Initialise the agility config from a YAML file.

        Parameters
        ----------
        file_path : str | Path
            Filepath containing the agility config (YAML)

        Returns
        -------
        config : AgilityConfig
            Config object from the input data
        """
        if not file_path:
            raise ValueError("Path is None. No file to be found.")
        elif not os.path.isfile(file_path):
            raise FileNotFoundError(f"File does not exist: {file_path}")
        else:
            with open(file_path, "rt") as file:
                return cls.from_yaml_text(file.read())

    @classmethod
    def from_yaml_text(cls, yaml_text: str) -> "AgilityConfig":
        """
        Initialise the agility config from YAML text.

        Parameters
        ----------
        yaml_text : str
            Text containing the agility config (YAML)

        Returns
        -------
        config : AgilityConfig
            Config object from the input data
        """
        return cls(**yaml.safe_load(yaml_text))


class AgilityBudget:
    """
    Rest-to-rest slew performance about one axis, for one mass properties case.

    Every capability query takes a `degraded` flag rather than there being two
    objects, because the failure case is a halved capability about the same axis
    and reads best beside the nominal one. With one wheel failed, only two of the
    three survivors can be used at full torque if net in-plane momentum is to stay
    zero, so both momentum and torque about the axis halve. The geometry does not
    change -- this is the same pyramid flying degraded, not a three-wheel mounting.

    Parameters
    ----------
    config : AgilityConfig
        Inertia cases, wheels and the settling time
    orbit : Orbit
        The shared orbit, for ground track speed
    axis : Axis
        Which axis the slews are about
    case : str
        Which inertia case to fly. Required: a default would leave a reader
        guessing which spacecraft produced a number
    mass_budget : MassBudget, optional
        Where the mass comes from, for an envelope case. Read at the case's own
        propellant fraction. Unused by a case that states its inertia
    mass : Quantity, optional
        A mass to slew, overriding the budget. For a what-if or a fixture

    Raises
    ------
    KeyError
        If no case of that name is configured
    """

    def __init__(
        self,
        config: AgilityConfig,
        orbit: Orbit,
        axis: Axis,
        case: str,
        mass_budget: "MassBudget | None" = None,
        mass=None,
    ):
        self.config = config
        self.orbit = orbit
        self.axis = Axis(axis)
        self.case_name = case
        self.case = config.for_case(case)
        self.mass_budget = mass_budget
        self._mass = mass

    @property
    def mass(self):
        """
        The mass being slewed, for an envelope case.

        An explicit `mass` wins; otherwise the attached mass budget is read at the
        case's propellant fraction. In orbit and propellant-scaled, since that is
        what is actually turning: the launch adapter is long gone and the tanks
        empty over the mission, which is why a satellite grows more agile with age.

        A case that states its inertia never reaches here -- inertia is the only
        route mass takes into the slew maths, so such a case needs no mass at all.

        Returns
        -------
        mass : Quantity
            In kg

        Raises
        ------
        ValueError
            If an envelope case has neither a mass nor a mass budget to read
        """
        if self._mass is not None:
            return self._mass
        if self.mass_budget is not None:
            return self.mass_budget.in_orbit_mass(
                propellant=self.case.propellant.to("percent").magnitude
            )
        raise ValueError(
            f"Case '{self.case_name}' estimates its inertia from an envelope, so "
            "it needs a mass. Attach a mass_budget, pass mass=, or use a case "
            "that states its inertia outright."
        )

    @classmethod
    def from_yaml_file(
        cls,
        config_path: str | Path,
        orbit_path: str | Path,
        axis: Axis,
        case: str,
        mass_budget: "MassBudget | None" = None,
        mass=None,
    ) -> "AgilityBudget":
        """
        Build an agility budget from a config and an orbit file.

        Where several budgets share one orbit, load it once with
        `Orbit.from_yaml_file` and use the constructor instead.

        Parameters
        ----------
        config_path : str | Path
            Filepath of the agility config (YAML)
        orbit_path : str | Path
            Filepath of the shared orbit (YAML)
        axis : Axis
            Which axis the slews are about
        case : str
            Which inertia case to fly
        mass_budget : MassBudget, optional
            Where the mass comes from, for an envelope case
        mass : Quantity, optional
            A mass to slew, overriding the budget

        Returns
        -------
        budget : AgilityBudget
            The assembled budget
        """
        return cls(
            AgilityConfig.from_yaml_file(Path(config_path)),
            Orbit.from_yaml_file(Path(orbit_path)),
            axis,
            case,
            mass_budget,
            mass,
        )

    @property
    def inertia(self):
        """
        Moment of inertia about the axis, from whichever shape the case carries.

        A stated case gives it verbatim. An envelope case works it out as a
        uniform box with an appendage uplift, from the mass at the case's
        propellant fraction, so it moves when the mass budget does.

        Returns
        -------
        inertia : Quantity
            In kg*m**2
        """
        if not self.case.is_envelope:
            return cast(Q_, getattr(self.case.inertia, self.axis.value)).to("kg * m**2")
        body = cast(Body, self.case.body)
        first, second = (body.y, body.x)[self.axis is Axis.PITCH], body.z
        factor = getattr(self.case.appendage_factor, self.axis.value)
        box = self.mass / 12 * (first**2 + second**2)
        return (box * factor).to("kg * m**2")

    @property
    def projection(self):
        """
        Fraction of a wheel's capability that lands on an in-plane axis.

        `cos(elevation)` takes the wheel into the pyramid base plane, and
        `cos(45 deg)` resolves it onto roll or pitch within that plane.

        Returns
        -------
        projection : Quantity
            Dimensionless
        """
        elevation = self.config.wheels.elevation
        # numpy stubs do not know pint, though the ufunc dispatches fine at runtime
        return (np.cos(elevation) * np.cos(Q_(45, "deg"))).to(  # pyright: ignore[reportCallIssue, reportArgumentType]
            "dimensionless"
        )

    @property
    def usable_momentum_per_wheel(self):
        """
        Momentum one wheel contributes, after the use policy.

        Returns
        -------
        momentum : Quantity
            In N*m*s
        """
        wheels = self.config.wheels
        return (wheels.momentum * wheels.momentum_use_factor).to("N * m * s")

    @property
    def usable_torque_per_wheel(self):
        """
        Torque one wheel contributes, after derating.

        Returns
        -------
        torque : Quantity
            In N*m
        """
        wheels = self.config.wheels
        return (wheels.torque * wheels.torque_derating).to("N * m")

    @property
    def yaw_momentum(self):
        """
        Momentum about the pyramid's symmetry axis.

        The weak axis under this mounting. It drives no slew case here, but is
        reported because it is what a yaw manoeuvre would have to live within.

        Returns
        -------
        momentum : Quantity
            In N*m*s
        """
        wheels = self.config.wheels
        return (
            wheels.count * self.usable_momentum_per_wheel * np.sin(wheels.elevation)
        ).to("N * m * s")

    def _wheels_used(self, degraded: bool) -> float:
        """
        Effective wheel count, halved when one has failed.

        Parameters
        ----------
        degraded : bool
            One wheel failed

        Returns
        -------
        count : float
            Wheels that can be commanded about the axis
        """
        return self.config.wheels.count / 2 if degraded else self.config.wheels.count

    def axis_momentum(self, degraded: bool = False):
        """
        Momentum the assembly can put about the axis.

        Parameters
        ----------
        degraded : bool
            One wheel failed, halving the usable capability

        Returns
        -------
        momentum : Quantity
            In N*m*s
        """
        used = self._wheels_used(degraded)
        return (used * self.usable_momentum_per_wheel * self.projection).to("N * m * s")

    def axis_torque(self, degraded: bool = False):
        """
        Torque the assembly can put about the axis.

        Parameters
        ----------
        degraded : bool
            One wheel failed, halving the usable capability

        Returns
        -------
        torque : Quantity
            In N*m
        """
        used = self._wheels_used(degraded)
        return (used * self.usable_torque_per_wheel * self.projection).to("N * m")

    def max_rate(self, degraded: bool = False):
        """
        Fastest the spacecraft can turn before the wheels saturate.

        Parameters
        ----------
        degraded : bool
            One wheel failed

        Returns
        -------
        rate : Quantity
            In deg/s
        """
        return (self.axis_momentum(degraded) / self.inertia).to("deg / s")

    def max_acceleration(self, degraded: bool = False):
        """
        Angular acceleration the available torque produces.

        Parameters
        ----------
        degraded : bool
            One wheel failed

        Returns
        -------
        acceleration : Quantity
            In deg/s**2
        """
        return (self.axis_torque(degraded) / self.inertia).to("deg / s**2")

    def crossover_angle(self, degraded: bool = False):
        """
        Slew angle at which torque limiting gives way to momentum limiting.

        Below it the wheels never saturate and the profile is triangular; above
        it they do, and the slew coasts. Which side a manoeuvre falls on says
        whether more torque or more momentum would buy anything.

        Parameters
        ----------
        degraded : bool
            One wheel failed

        Returns
        -------
        angle : Quantity
            In degrees
        """
        rate, acceleration = self.max_rate(degraded), self.max_acceleration(degraded)
        return (rate**2 / acceleration).to("deg")

    def profile(self, angle, degraded: bool = False) -> Profile:
        """
        Which limit binds for a slew of this size.

        Parameters
        ----------
        angle : Quantity
            Slew angle
        degraded : bool
            One wheel failed

        Returns
        -------
        profile : Profile
            `TRIANGULAR` when torque limited, `TRAPEZOIDAL` when momentum limited
        """
        if angle <= self.crossover_angle(degraded):
            return Profile.TRIANGULAR
        return Profile.TRAPEZOIDAL

    def slew_time(self, angle, degraded: bool = False):
        """
        Rest-to-rest slew time, settling excluded.

        Parameters
        ----------
        angle : Quantity
            Slew angle
        degraded : bool
            One wheel failed

        Returns
        -------
        time : Quantity
            In seconds
        """
        rate, acceleration = self.max_rate(degraded), self.max_acceleration(degraded)
        if self.profile(angle, degraded) is Profile.TRIANGULAR:
            return (2 * (angle / acceleration) ** 0.5).to("s")
        return (angle / rate + rate / acceleration).to("s")

    def peak_rate(self, angle, degraded: bool = False):
        """
        Fastest the spacecraft turns during the slew.

        Parameters
        ----------
        angle : Quantity
            Slew angle
        degraded : bool
            One wheel failed

        Returns
        -------
        rate : Quantity
            In deg/s
        """
        if self.profile(angle, degraded) is Profile.TRIANGULAR:
            return ((angle * self.max_acceleration(degraded)) ** 0.5).to("deg / s")
        return self.max_rate(degraded)

    def momentum_used(self, angle, degraded: bool = False):
        """
        Fraction of the axis momentum the slew actually calls on.

        Reaches 1 for any slew past the crossover, which is what momentum limited
        means. Below it, the shortfall is the headroom a larger slew would use.

        Parameters
        ----------
        angle : Quantity
            Slew angle
        degraded : bool
            One wheel failed

        Returns
        -------
        fraction : Quantity
            Dimensionless
        """
        peak = (self.inertia * self.peak_rate(angle, degraded)).to("N * m * s")
        return (peak / self.axis_momentum(degraded)).to("dimensionless")

    def slew_table(self, angles=None, degraded: bool = False) -> pd.DataFrame:
        """
        One row per slew angle, with the time, profile and momentum used.

        Parameters
        ----------
        angles : iterable of Quantity, optional
            Slew angles. Defaults to `DEFAULT_SLEW_ANGLES`, in degrees
        degraded : bool
            One wheel failed

        Returns
        -------
        frame : pd.DataFrame
            Angles in degrees, times in seconds, rates in deg/s
        """
        if angles is None:
            angles = [Q_(value, "deg") for value in DEFAULT_SLEW_ANGLES]
        records = [
            {
                "angle": angle.to("deg").magnitude,
                "profile": self.profile(angle, degraded).value,
                "slew_time": self.slew_time(angle, degraded).to("s").magnitude,
                "total_time": self.total_time(angle, degraded).to("s").magnitude,
                "peak_rate": self.peak_rate(angle, degraded).to("deg / s").magnitude,
                "momentum_used": self.momentum_used(angle, degraded).magnitude,
            }
            for angle in angles
        ]
        return pd.DataFrame(records)

    def total_time(self, angle, degraded: bool = False):
        """
        Slew time plus the settling allowance, applied once at the end.

        Parameters
        ----------
        angle : Quantity
            Slew angle
        degraded : bool
            One wheel failed

        Returns
        -------
        time : Quantity
            In seconds
        """
        settling = self.config.settling_time
        return (self.slew_time(angle, degraded) + settling).to("s")

    def time_margin(self, angle, target_duration, degraded: bool = False):
        """
        How much of a target duration is left over, as a fraction of what is needed.

        The target duration is an argument rather than config: how long a manoeuvre
        may take is a question asked of a spacecraft, not a property of one, and
        the same spacecraft is asked it differently by different operations.

        Parameters
        ----------
        angle : Quantity
            Slew angle
        target_duration : Quantity
            Time the operation allows for the whole manoeuvre
        degraded : bool
            One wheel failed

        Returns
        -------
        margin : Quantity
            Dimensionless; negative when the manoeuvre does not fit
        """
        needed = self.total_time(angle, degraded)
        return ((target_duration - needed) / needed).to("dimensionless")

    def achievable_angle(self, target_duration, degraded: bool = False):
        """
        Largest slew that fits, given the time available.

        The inverse of `slew_time`, solved on the momentum-limited branch and
        capped there: a manoeuvre big enough to be worth asking about is past the
        crossover, and below it the answer is the torque-limited form instead.

        Parameters
        ----------
        target_duration : Quantity
            Time the operation allows for the whole manoeuvre
        degraded : bool
            One wheel failed

        Returns
        -------
        angle : Quantity
            In degrees
        """
        slewing = target_duration - self.config.settling_time
        rate, acceleration = self.max_rate(degraded), self.max_acceleration(degraded)
        coasting = slewing - rate / acceleration
        if coasting <= Q_(0, "s"):
            return (acceleration * (slewing / 2) ** 2).to("deg")
        return (rate * coasting).to("deg")

    def ground_distance(self, time):
        """
        How far the ground track runs while a manoeuvre is flown.

        Ties the slew to the orbit the other budgets already share, which is what
        makes a slew time mean something: it is the swath the satellite gives up.

        Parameters
        ----------
        time : Quantity
            Duration

        Returns
        -------
        distance : Quantity
            In km
        """
        return (self.orbit.ground_track_speed * time).to("km")

    def tabulated_agility(
        self, angles=None, degraded: bool = False, target_duration=None
    ):
        """
        The slew table as a document.

        Parameters
        ----------
        angles : iterable of Quantity, optional
            Slew angles. Defaults to `DEFAULT_SLEW_ANGLES`
        degraded : bool
            One wheel failed
        target_duration : Quantity, optional
            Time the operation allows. Given one, the table also says whether
            each manoeuvre fits; without one those columns are left out

        Returns
        -------
        report : Styler
            One row per slew angle, rendered for reading
        """
        return tabulate(self.slew_table(angles, degraded), target_duration)
