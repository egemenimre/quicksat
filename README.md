# quicksat

[![CircleCI](https://dl.circleci.com/status-badge/img/gh/egemenimre/quicksat/tree/master.svg?style=svg)](https://dl.circleci.com/status-badge/redirect/gh/egemenimre/quicksat/tree/master)
[![codecov](https://codecov.io/github/egemenimre/quicksat/graph/badge.svg?token=ANT5QB5UB8)](https://codecov.io/github/egemenimre/quicksat)

Basic satellite sizing tool. It covers the mass, data, delta-V and attitude agility budgets, and a mission scenario with a 3D viewer. Power, battery and radiator sizing will follow. quicksat is kept simple on purpose. It gives a first-pass sizing, not a full systems engineering environment.

## Status

| | |
|---|---|
| **Mass budget** | implemented |
| **Data and downlink budget** | implemented |
| **Delta-V budget** | implemented |
| **Attitude agility budget** | implemented |
| **Mission scenario** | implemented |
| **Power, battery and radiator sizing** | not yet specified |

## The shared mission

Every budget that needs to know where the spacecraft is, or how long it flies, reads the same file:

```yaml
altitude: 500 km
inclination: 97.4 deg      # sun-synchronous at this altitude
duration: 7 yr             # design life
```

```python
from quicksat.utils.mission import Mission

mission = Mission.from_yaml_file("sample/sizing/data/mission.yaml")

mission.period.to("min")  # 94.6 min
mission.orbits_per_day    # 15.22
mission.velocity          # 7.61 km/s
mission.duration          # 7 yr
```

Each budget takes what it needs from the mission. The data budget takes the period and the orbits in a day. The delta-V budget takes the circular velocity, and the design life that scales its recurring manoeuvres. The agility budget takes the ground track speed.

Each budget reads the file itself, or takes a `Mission` that is already loaded: `DataBudget(model, mission)`, `DeltaVBudget(manoeuvres, config, mission)` and `AgilityBudget(config, mission, axis, case)`. Several budgets in one session can then share one `Mission`. This shows that they use the same orbit, rather than separate copies that happen to agree today.

One rule decides what goes in this file. **A fact that more than one module can use goes here. A fact that only one module uses stays in that module's own config.** So the altitude is here, and the Isp is not. Each fact is stated once, so no two copies can disagree. Copies would disagree as soon as a number in three config files was changed in only one of them. The orbit is circular throughout. Nothing here models eccentricity, perturbations or drag.

## Mass budget

Two files describe a satellite. The first is a flat equipment list, with one row per item. Nothing is nested. `location`, `responsibility` and `subsystem` are independent axes rather than levels of a hierarchy. So the budget can sum over any one of them on its own.

```csv
equipment_id,equipment_name,location,responsibility,subsystem,unit_mass,eqpt_margin,number_of_units,mass_class,comments
reaction_wheel,Rockwell RSI 45,Platform,Platform,ADCS,7.0 kg,10,4,equipment,Pyramid configuration
imu,Northrop LN-200S,Platform,Platform,ADCS,750 g,5,1,equipment,Entered in grams
star_tracker,Jena Astro HP,Payload,Platform,ADCS,1.2 kg,5,2,equipment,Redundant pair
hydrazine,Hydrazine load,Platform,Platform,Propulsion,22.0 kg,0,1,propellant,No mass margin; carried as delta-V margin
```

The second holds the margins and the harness, keyed on location:

```yaml
locations:
  Platform:
    system_margin: 20     # percent, applied to the location subtotal
    harness_fraction: 4   # percent of this location's equipment mass, before margin
    harness_margin: 25    # percent, the harness's own contingency
```

Masses are entered with their units and parsed with [astropy](https://docs.astropy.org/en/stable/units/). So `750 g` is converted on load. `100 W` in a mass column raises an error, rather than being read as a plain number. The harness is not typed in. It is derived, with one row per location. Margins come in two layers: a contingency per item, and a system margin per location. Propellant takes neither.

Then query the budget. Every query takes the same four flags: `propellant`, `sys_margin`, `eqpt_margin` and `in_orbit`. By default, they describe the satellite as it flies at the start of life. So the usual query needs no arguments, and each change from it is one explicit flag.

```python
from quicksat.mass.budget import MassBudget

budget = MassBudget.from_csv("sample/sizing/data/equipment.csv", "sample/sizing/data/mass_budget_config.yaml")

budget.in_orbit_mass()               # 470.62 kg  - separated wet mass
budget.on_ground_mass(propellant=0)  # 465.34 kg  - dry mass at launch
budget.in_orbit_mass(propellant=50)  # 459.62 kg  - half-way through the mission
budget.subsystem_mass("ADCS")        #  39.50 kg
```

`by_location()`, `by_responsibility()` and `by_subsystem()` sum the same rows over each of the three axes. They give the same total, because they group one table rather than make three separate calculations. `tabulated_mass()` lays out the whole budget as a document. It lists every item, grouped by subsystem within each location. The subtotals, the margins, and the dry, propellant and wet masses follow in reading order.

## Data and downlink budget

There is nothing to sum here. The budget is one chain of calculations, from a few assumptions to a single comparison. So the input is a config file rather than a CSV. There are no rows, so there are no grouping views. Generation is counted per orbit, because the payload collects data for a fraction of each orbit. Downlink is counted per day, because the contacts follow the ground station's day. The two are compared per day, and the margin is taken there.

```yaml
generation:
  raw_datarate: 1000 Mbit/s   # before compression
  compression_ratio: 2.4
  duty_cycle: 5 %             # of each orbit: daytime, full VNIR

downlink:
  rate: 800 Mbit/s              # X-band transmitter throughput
  contacts_per_day: 7           # usable ground contacts, from Mission Analysis
  avg_contact_duration: 6 min

storage:
  orbits_without_contact: 3   # sizing case for the mass memory
```

```python
from quicksat.dataflow.budget import DataBudget

budget = DataBudget.from_yaml_file("sample/sizing/data/pl_dataflow_model.yaml", "sample/sizing/data/mission.yaml")

budget.generated_per_day    # 225.00 GB
budget.downlinked_per_day   # 252.00 GB
budget.margin               # 0.12: the link sends 12% more than the payload makes
budget.storage_required()   # 44.35 GB to cover three orbits without a pass
```

A positive margin means that each day's data is sent down the same day. A negative margin means data builds up until some is deleted or a pass is added. `storage_required()` sizes the memory for the gap between passes. It does not cover a backlog that grows from day to day. The two are the same only while the budget closes. `tabulated_data()` gives the whole chain as a document. It has one row per quantity, with the assumption behind it. Each row is tagged `input`, `derived`, `margin` or `storage`, so the report can be filtered.

## Delta-V budget

The input is a flat list again, with one row per manoeuvre. `phase` and `manoeuvre_type` are the two axes to group over. Each row names a type, and the type says how its `value` becomes a delta-V:

- `altitude_change`: a Hohmann transfer between circular altitudes.
- `collision_avoidance`: the same transfer, doubled when the config says the spacecraft returns to its altitude.
- `inclination_change`: a plane change at circular velocity.
- `deorbit`: a single deorbit burn.
- `given`: a delta-V worked out by real analysis elsewhere.

A `recurring` row is counted per year, and scaled by the mission duration.

```csv
manoeuvre_id,manoeuvre_name,phase,manoeuvre_type,value,count,recurring,loss_factor,comments
injection_correction,Launcher dispersion correction,Commissioning,altitude_change,12 km,1,false,1.0,Semi-major axis dispersion at separation
drag_makeup,Drag make-up,Operations,altitude_change,1.2 km,1,true,1.0,Per year at 500 km solar mean
collision_avoidance,Collision avoidance,Operations,collision_avoidance,200 m,4,true,1.0,Per year; one-way hop as the drag make-up absorbs the return
deorbit,End-of-life deorbit,Disposal,deorbit,250 km,1,false,1.0,Single burn to a 500 x 250 km disposal orbit; natural decay rather than controlled re-entry
```

The `value` column holds whatever its type needs, and is checked against the type on load. So a length where a velocity belongs raises an error at that row. There is one layer of margin rather than two: a single margin on the total. A margin per manoeuvre would mean little, because the counts are the uncertain part.

The closed forms assume impulsive burns. `loss_factor` corrects a row whose burn is not impulsive. It multiplies that row's delta-V, to cover finite-burn and gravity losses. It is 1.0 by default, and cannot be less. Its size depends on the thrust level, and on how the manoeuvre is split into several burns. That is an operational matter, so the factor is an input rather than a calculation. It is not the margin, which covers the uncertainty in the counts.

```python
from quicksat.delta_v.budget import DeltaVBudget
from quicksat.mass.budget import MassBudget

spacecraft = MassBudget.from_csv("sample/sizing/data/equipment.csv", "sample/sizing/data/mass_budget_config.yaml")
budget = DeltaVBudget.from_csv(
    "sample/sizing/data/manoeuvres.csv",
    "sample/sizing/data/delta_v_config.yaml",
    "sample/sizing/data/mission.yaml",
    mass_budget=spacecraft,
)

budget.total_deltav()               # 116.5 m/s, margin included
budget.total_deltav(margin=False)   # 111.0 m/s
budget.by_phase()                   # Commissioning 22.3, Operations 19.9, Disposal 74.3
budget.propellant_mass()            # 24.89 kg, from the attached mass budget
```

`tabulated_deltav()` lays out the budget as a document. It lists every manoeuvre, with a subtotal per phase. Then come the total before margin, the margin line, and the total with margin. `comments=True` and `loss_factor=True` each add a column that is hidden by default.

`propellant_mass` takes the dry mass from a `MassBudget`. The mass budget is attached when the delta-V budget is built, or given as an argument that overrides it. The attachment is optional and goes one way only. `quicksat.delta_v` never imports `quicksat.mass` at runtime, so every other query works with no spacecraft attached. Nothing is written back. The equipment CSV stays the only record of the propellant actually loaded.

In the sample data, the two do not quite agree. The budget asks for 24.9 kg, and the equipment list carries 22 kg. The disposal choice decides this. A single burn to a 500 × 250 km decay orbit takes 74 m/s of the 117 m/s total. A direct re-entry from the same orbit would take 152 m/s, and would raise the propellant to 42 kg.

## Attitude agility budget

The agility budget gives the rest-to-rest slew performance about one axis. The wheel geometry reduces to two numbers: the momentum and the torque that the wheels can apply about that axis. The slew calculation uses only these two. There is no distribution matrix and no load per wheel. A sizing model needs to know whether a 40° slew fits in the time, not how the wheels share the command.

Mass properties come as **named cases**, as many as the mission needs. A case is either an envelope estimate or a stated inertia. An envelope estimate is a box with an appendage factor per axis. Its inertia follows the mass that the mass budget reports. A stated inertia is given as a mass properties report gives it. A case is never both, so each number has only one possible source. You choose the names, and nothing in the code depends on them.

```yaml
inertia_cases:
  first_guess:               # inertia estimated from a uniform box
    body:
      x: 1.5 m
      y: 1.5 m
      z: 2.0 m
    appendage_factor:        # per axis: the appendages are not symmetric
      roll: 1.07
      pitch: 1.02
    propellant: 100 %        # mission point at which the mass budget is read

  measured_bol:              # stated outright, and needs no mass at all
    inertia:
      roll: 264.7 kg*m**2
      pitch: 280.0 kg*m**2

wheels:
  count: 4                   # pyramid, symmetry axis along yaw
  elevation: 26.5 deg        # of each wheel above the pyramid base plane
  momentum: 4.0 N*m*s        # nameplate, per wheel
  torque: 0.2 N*m
  momentum_use_factor: 33.3 %   # policy: the rest is disturbance storage
  torque_derating: 75 %         # policy: the rest is control authority

settling_time: 20 s          # an ADCS property, applied once at the end of a slew
```

The config holds **no mass**. The mass budget holds it, and a second copy here could come to disagree with it. The config also holds **no target duration**. How long a slew may take is a requirement placed on the spacecraft, not a property of it.

```python
from quicksat import u
from quicksat.agility.budget import AgilityBudget, Axis
from quicksat.mass.budget import MassBudget

spacecraft = MassBudget.from_csv("sample/sizing/data/equipment.csv", "sample/sizing/data/mass_budget_config.yaml")
roll = AgilityBudget.from_yaml_file(
    "sample/sizing/data/agility_config.yaml",
    "sample/sizing/data/mission.yaml",
    Axis.ROLL,
    "first_guess",
    mass_budget=spacecraft,
)

roll.slew_time(40 * u.deg)                 # 63.2 s, momentum limited
roll.total_time(40 * u.deg)                # 83.2 s once settling is added
roll.time_margin(40 * u.deg, 113 * u.s)    # +35.8% against that target
roll.achievable_angle(113 * u.s)           # 62.0 deg, the inverse solve
roll.slew_time(40 * u.deg, degraded=True)  # 117.5 s with one wheel failed
```

Momentum sets the highest rate at which the spacecraft can turn. Torque sets how quickly it reaches that rate. The crossover angle between the two is 6.5° here. Below it, the rate profile is a triangle: the body accelerates, then decelerates. Above it, the profile is a trapezoid that coasts at the maximum rate. Which of the two limits a slew is a useful output. Below the crossover, more torque would shorten the slew. Above it, only more momentum would.

Every capability query takes a `degraded` flag, so there is no second object for a failed wheel. With one of the four wheels failed, three remain. Only two of them can run at full torque if the net momentum in the base plane is to stay zero. So both the momentum and the torque about the axis halve. This models the same pyramid with one wheel failed, not a mounting designed for three wheels.

Roll and pitch use the same calculation. The pyramid's symmetry axis is along yaw, so roll and pitch both lie in its base plane. Only the inertia differs. So one implementation serves both, and takes the axis as an argument. Yaw is reported, but never slewed. It is the weak axis with this mounting, and its limits are what a yaw manoeuvre would have to stay within.

`tabulated_agility()` gives the slew table as a document. Given a `target_duration`, it also checks each angle against it, and marks the slews that do not fit. Without one, those columns are left out rather than hidden, because there is nothing to check against. The shared mission's ground track speed turns a slew time into a distance on the ground. During the 113 s allowance here, the ground track moves 798 km, and the payload images none of it. This distance is how a payload operator measures a slew.

## Mission scenario

The scenario flies the satellite through a list of activities on a real orbit. It checks the timeline: whether each activity falls in sunlight or in eclipse as planned, and how long the body takes to turn between attitudes. Power will build on it.

The orbit comes from a TLE or OMM file, from a sun-synchronous orbit that quicksat builds as a TLE, or from a trajectory file, in ECSV or CCSDS OEM. SGP4 flies a TLE, a trajectory is interpolated between its samples, and astropy gives the sun and the frames. The scenario does not read `mission.yaml`, because it needs a real orbit, with an epoch and a node. One file holds the whole scenario:

```yaml
orbit:
  sso: {altitude: 510 km, ltan: "13:30"}
start: 2026-10-01T09:00:00
duration: 3 orbits
3d_model: spacecraft.glb       # optional: the viewer draws a 1 m cube without it

attitudes:
  nadir: {nadir_axis: +z, orbit_normal: -y}
  sun pointing: {sun_axis: -z, constrain_to_orbit_normal: -y}

slew:
  max_rate: 0.7 deg/s
  max_acceleration: 0.08 deg/s2
  settling_time: 20 s

# the trigger that ends each activity, its attitude, its mode, and the illumination it expects
activities:
  - [eclipse entry, sun pointing, idle, sunlit]
  - [eclipse exit, nadir, idle, eclipse]
  - [latitude 45 deg -2 min, sun pointing, idle, sunlit]
  - [latitude 45 deg +4 min, nadir, imaging, sunlit]
  - [10 min, nadir, downlink]
```

Each activity starts where the one before it ends, and the list repeats until the run ends. An activity ends after a fixed time, or at an event: a shadow edge, a node, or a latitude crossing, with an optional offset. The shadow has an umbra and a penumbra, cast on the WGS84 ellipsoid. Before each change of attitude, the body slews into the new one, at the given rate and acceleration.

```python
from quicksat.scenario.config import Scenario
from quicksat.scenario.run import run_scenario
from quicksat.scenario.viewer import write_scenario_viewer

scenario = Scenario.from_yaml_file("sample/scenario/data/scenario.yaml")
run = run_scenario(scenario)

run.activity_summary  # 13 occurrences in 3 repeats, all ok but the last, cut at the end
run.activity_table    # one row per occurrence, with its slew time and status
len(run.slews)        # 10 slews, from 92 s to 214 s
write_scenario_viewer(run, "sample/scenario/output")
```

The activity table and a Gantt chart show which activities miss their constraint, and by how much. The viewer is a web page, `scenario_viewer.html`, with the run's data in `scenario.js` beside it. It shows the run in 3D, with the ground track and the timeline. The spacecraft is drawn from the GLB file that `3d_model` names in the scenario file, or as a 1 m cube without one. The page needs no Python and no server. So the folder can be sent to anyone, who opens the page with a double-click.

## Documentation

The documentation follows the [Diátaxis](https://diataxis.fr/) split. The samples are tutorials to follow, and the docs explain how things work. Files under `docs/` take a `_ref` suffix, so a sample and its reference cannot be confused. Each reads its own input files, from `sample/sizing/data/` or `docs/sizing/data/`. So a change to a sample's inputs cannot change a figure quoted in a reference.

The notebooks and their data are grouped by domain. `sizing` covers the mission, mass, data, delta-V and agility budgets below. `scenario` covers the orbit and the timeline of activities. `power` will hold power generation, built on the scenario. The tests follow the same split, under `tests/sizing/`, `tests/scenario/` and `tests/power/`. The orbit and shadow code that the scenario and power share is tested in `tests/orbit/`.

| | tutorial and how-to | explanation and reference |
|---|---|---|
| Mission | — | [`docs/sizing/mission_ref.ipynb`](docs/sizing/mission_ref.ipynb) |
| Mass | [`sample/sizing/mass_budget.ipynb`](sample/sizing/mass_budget.ipynb) | [`docs/sizing/mass_budget_ref.ipynb`](docs/sizing/mass_budget_ref.ipynb) |
| Data | [`sample/sizing/data_budget.ipynb`](sample/sizing/data_budget.ipynb) | [`docs/sizing/data_budget_ref.ipynb`](docs/sizing/data_budget_ref.ipynb) |
| Delta-V | [`sample/sizing/delta_v_budget.ipynb`](sample/sizing/delta_v_budget.ipynb) | [`docs/sizing/delta_v_ref.ipynb`](docs/sizing/delta_v_ref.ipynb) |
| Agility | [`sample/sizing/agility_roll.ipynb`](sample/sizing/agility_roll.ipynb), [`sample/sizing/agility_pitch.ipynb`](sample/sizing/agility_pitch.ipynb) | [`docs/sizing/agility_ref.ipynb`](docs/sizing/agility_ref.ipynb) |
| Scenario | [`sample/scenario/scenario.ipynb`](sample/scenario/scenario.ipynb) | [`docs/scenario/scenario_ref.ipynb`](docs/scenario/scenario_ref.ipynb) |

Three Markdown documents sit beside the notebooks. They cover the project as a whole rather than one budget.

| Document | What it holds |
|---|---|
| [`docs/explanations/decisions.md`](docs/explanations/decisions.md) | The decisions that shaped quicksat, and the reasons for each. Newest first. Read it to learn why the code is built the way it is. |
| [`docs/reference/conventions.md`](docs/reference/conventions.md) | The rules the code and the notebooks follow: how to handle units and constants, and how to write tests. Read it before changing the code. |
| [`docs/guides/`](docs/guides/) | Guides for getting a specific task done. Start with [how to initialise a satellite](docs/guides/sizing/initialise_a_satellite.md). For the timeline, see [how to set up and run a scenario](docs/guides/scenario/set_up_a_scenario.md). |

The sizing samples work through each budget for one sample satellite, in the order you would do it. The satellite is a small Earth observation platform in a 500 km sun-synchronous orbit. The scenario sample flies a 510 km sun-synchronous orbit for three orbits, with five activities. The reference notebooks explain why each part behaves as it does. They cover the data model, unit handling, and the input files field by field. They also show how the derived quantities and the margin layers are worked out, and where each budget stops.

## Installation

```bash
conda env create -f environment.yml
conda activate quicksat
pip install -e .
```

## License

GPL-3.0-or-later. See `LICENSE.md`.
