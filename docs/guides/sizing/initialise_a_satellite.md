# How to initialise a satellite for analysis

This guide takes you from the sample files to a satellite you can analyse. You
fill in a set of input files that describe your satellite. Then you load each
file into a budget.

The sample files describe a small Earth observation satellite. They are a
working example, so they give you correct file names, column headings and units
to start from.

You need quicksat installed first. The README has the steps, under
"Installation".

## 1. Copy the sample data

Copy the `sample/sizing/data` folder and give the copy your own name:

```bash
cp -r sample/sizing/data my_satellite
```

Then edit the files in `my_satellite/`. Do not edit `sample/sizing/data/` itself. The
sample notebooks read it, and the figures in them depend on its contents.

The folder can go anywhere. The code below assumes it is called `my_satellite`
and sits in the folder you run Python from.

## 2. Fill in the input files

There are seven files. The mission file is shared. Each of the other six belongs
to one budget.

| File | Describes | Used by |
|---|---|---|
| `mission.yaml` | The orbit and the design life | data, delta-V, agility |
| `equipment.csv` | Every item on the satellite, with its mass | mass |
| `mass_budget_config.yaml` | Margins and harness for each location | mass |
| `pl_dataflow_model.yaml` | Payload data generation and downlink | data |
| `manoeuvres.csv` | Every manoeuvre, with its size and count | delta-V |
| `delta_v_config.yaml` | Engine performance and the delta-V margin | delta-V |
| `agility_config.yaml` | Inertia, reaction wheels and settling time | agility |

You do not need every budget. The mass budget needs only its own two files. The
data, delta-V and agility budgets also need `mission.yaml`. You can leave out
the files of any budget you do not want. Start with the mission file, because
three budgets read it.

Some fields take a bare percentage, such as `eqpt_margin: 10`. Others take a
value with a unit, such as `duty_cycle: 5 %`. Copy the form that the sample file
uses for each field.

### `mission.yaml`

Holds the altitude, the inclination and the design life. The orbit is circular.
A fact that more than one budget can use goes in this file. A fact that only one
budget can use stays in that budget's own file.

All three values are required. The design life, `duration`, scales every
delta-V manoeuvre that recurs each year.

Details: [`mission_ref.ipynb`](../../sizing/mission_ref.ipynb), section "The file".

### `equipment.csv`

One row per item, with no nesting. Each item has a mass with its unit (`7.0 kg`
or `750 g`), a margin in percent, and a number of units. Each item also sits at
a `location`, in a `subsystem`, under a `responsibility`. The location decides
how margins are applied. The subsystem and the responsibility are only used to
group the report.

Mark propellant with `mass_class` set to `propellant`. Propellant is exempt from
the margins. Leave the field blank for all other items.

Details: [`mass_budget_ref.ipynb`](../../sizing/mass_budget_ref.ipynb), section "The
equipment file".

### `mass_budget_config.yaml`

One entry for each location used in `equipment.csv`. Each entry sets the system
margin, the harness size and the harness margin, all in percent. It can also
say whether the hardware stays with the satellite after separation.

Every location in the CSV needs an entry here. If one is missing, loading stops
with an error that names it.

Details: [`mass_budget_ref.ipynb`](../../sizing/mass_budget_ref.ipynb), section "The
config file".

### `pl_dataflow_model.yaml`

Three sections. `generation` holds the instrument data rate, the compression
ratio and the share of each orbit spent collecting. `downlink` holds the link
rate, the contacts per day and the average contact length. `storage` holds the
number of orbits the satellite must survive without a contact.

The contact numbers are inputs, taken from a mission analysis. The budget does
not work them out.

Details: [`data_budget_ref.ipynb`](../../sizing/data_budget_ref.ipynb), section "The
files".

### `manoeuvres.csv`

One row per manoeuvre. The `manoeuvre_type` column decides what the `value`
column means. For an altitude change it is a length. For an inclination change
it is an angle. For a manoeuvre you have already worked out, type `given`, and
`value` is the delta-V itself.

Set `recurring` to `true` when `count` is per year. The budget then multiplies
it by the mission duration.

Details: [`delta_v_ref.ipynb`](../../sizing/delta_v_ref.ipynb), section "The manoeuvre
file".

### `delta_v_config.yaml`

Three settings: the specific impulse of the engine, one margin for the whole
delta-V total, and whether a collision avoidance hop returns to the original
orbit.

Details: [`delta_v_ref.ipynb`](../../sizing/delta_v_ref.ipynb), sections "The margin" and
"The rocket equation, and the sizing loop".

### `agility_config.yaml`

Three sections. `inertia_cases` holds one or more named sets of mass
properties. Each case is either an estimate from the satellite's dimensions or a
stated inertia from a mass properties report, never both. `wheels` describes
the reaction wheel pyramid. `settling_time` is the time the platform needs after
a slew before the payload can work.

The case names are yours. You pick one by name when you build the budget.

The file holds no mass and no target slew time. The mass comes from the mass
budget, and the target time is given when you ask a question.

Details: [`agility_ref.ipynb`](../../sizing/agility_ref.ipynb), sections "The config
file" and "Inertia cases, and why the two shapes are kept apart".

## 3. Load the satellite

Each budget has a `from_` method that reads its files. Load the mass budget
first. The delta-V and agility budgets can take it as an optional argument:

```python
from pathlib import Path

from quicksat import u
from quicksat.agility.budget import AgilityBudget, Axis
from quicksat.dataflow.budget import DataBudget
from quicksat.delta_v.budget import DeltaVBudget
from quicksat.mass.budget import MassBudget
from quicksat.utils.mission import Mission

DATA = Path("my_satellite")

mission = Mission.from_yaml_file(DATA / "mission.yaml")

mass = MassBudget.from_csv(
    DATA / "equipment.csv",
    DATA / "mass_budget_config.yaml",
)

data = DataBudget.from_yaml_file(
    DATA / "pl_dataflow_model.yaml",
    DATA / "mission.yaml",
)

delta_v = DeltaVBudget.from_csv(
    DATA / "manoeuvres.csv",
    DATA / "delta_v_config.yaml",
    DATA / "mission.yaml",
    mass_budget=mass,
)

roll = AgilityBudget.from_yaml_file(
    DATA / "agility_config.yaml",
    DATA / "mission.yaml",
    Axis.ROLL,
    "first_guess",  # the name of a case in agility_config.yaml
    mass_budget=mass,
)
```

Attaching the mass budget lets the delta-V budget work out the propellant mass.
It also lets the agility budget take the inertia of an estimated case from the
mass budget.

Each `from_` method reads `mission.yaml` itself, so the file is read more than
once. To share one loaded `Mission` between budgets, use the constructors
instead. The data budget reference explains both routes in the section "The
class".

## 4. Check that it loaded

Ask each budget one question. The values in the comments are what the sample
data gives. Yours will differ.

```python
mass.in_orbit_mass()         # 470.62 kg
data.margin                  # 0.12
delta_v.total_deltav()       # 116.5 m/s
roll.slew_time(40 * u.deg)   # 63.2 s
```

If a file is wrong, loading stops with an error. The error names the file, the
row and the field. For example, a location in `equipment.csv` that has no entry
in the config gives:

```text
Location 'Bus' is used in the equipment list but is missing from the budget
config. Add it under 'locations:'.
```

The most common causes are a value without its unit, a missing column, a space
in an `equipment_id` or `manoeuvre_id`, and a missing `duration` in
`mission.yaml`.

## Next steps

The README shows the main calls for each budget. The sample notebooks work
through each budget from start to finish:

- [`sample/sizing/mass_budget.ipynb`](../../../sample/sizing/mass_budget.ipynb)
- [`sample/sizing/data_budget.ipynb`](../../../sample/sizing/data_budget.ipynb)
- [`sample/sizing/delta_v_budget.ipynb`](../../../sample/sizing/delta_v_budget.ipynb)
- [`sample/sizing/agility_roll.ipynb`](../../../sample/sizing/agility_roll.ipynb) and
  [`sample/sizing/agility_pitch.ipynb`](../../../sample/sizing/agility_pitch.ipynb)
