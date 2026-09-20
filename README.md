# quicksat

Basic satellite sizing tool: mass, data and delta-V budgets, with power, battery and radiator sizing to come. Deliberately spartan — the aim is a first-pass sizing, not a full systems engineering environment.

## Status

| | |
|---|---|
| **Mass budget** | implemented |
| **Data and downlink budget** | implemented |
| **Delta-V budget** | implemented |
| **Power, battery and radiator sizing** | not yet specified |

## The shared orbit

Every budget that needs an orbit reads the same file, and derives what it wants from it:

```yaml
altitude: 500 km
inclination: 97.4 deg      # sun-synchronous at this altitude
```

```python
from quicksat.utils.orbit import Orbit

orbit = Orbit.from_yaml_file("sample/data/orbit.yaml")

orbit.period.to("min")  # 94.6 min
orbit.orbits_per_day    # 15.22
orbit.velocity          # 7.61 km/s
```

The data budget takes the period and the orbits in a day, delta-V takes the circular velocity. Each budget will read the file itself, or take an already-loaded `Orbit` — `DataBudget(model, orbit)`, `DeltaVBudget(manoeuvres, config, orbit)` — so that several budgets in one session demonstrably fly the same one rather than three parses that merely agree today. Stating the altitude once keeps them from drifting apart, which is what happens the first time the same number is copied into three config files and one of them is retuned. Circular throughout: nothing here models eccentricity, perturbations or drag.

## Mass budget

A satellite is described by two files. The first is a flat equipment list, one row per item — nothing is nested, because `location`, `responsibility` and `subsystem` are cross-cutting axes rather than a hierarchy, and any of them can then be summed over independently.

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

Masses are entered with their units and parsed with [pint](https://pint.readthedocs.io/), so `750 g` is converted on load and `100 W` in a mass column is rejected rather than quietly becoming a number. Harness is not typed in but derived, one row per location. Margins come in two layers — a per-item contingency and a per-location system margin — and propellant is exempt from both.

Then ask the budget things. Every query takes the same four flags — `propellant`, `sys_margin`, `eqpt_margin`, `in_orbit` — all defaulting to the satellite as it flies at the start of life, so the usual question is a bare call and each deviation is one explicit switch.

```python
from quicksat.mass.budget import MassBudget

budget = MassBudget.from_csv("sample/data/equipment.csv", "sample/data/budget_config.yaml")

budget.in_orbit_mass()               # 470.62 kg  - separated wet mass
budget.on_ground_mass(propellant=0)  # 465.34 kg  - dry mass at launch
budget.in_orbit_mass(propellant=50)  # 459.62 kg  - half-way through the mission
budget.subsystem_mass("ADCS")        #  39.50 kg
```

The same rows summed over any of the three axes reconcile to the same total, because they are three cuts of one table rather than three calculations — `by_location()`, `by_responsibility()`, `by_subsystem()`. And `tabulated_mass()` lays the whole budget out as a document: every item, grouped into subsystem blocks within each location, with the subtotals, the margins and the dry, propellant and wet masses in reading order.

## Data and downlink budget

There is nothing to sum here. This is one chain of calculations from a handful of assumptions to a single comparison, so the input is config rather than a CSV, and there are no grouping views because there are no rows. Generation is naturally per orbit — the payload collects for a fraction of each revolution — while downlink is naturally per day, because contacts belong to the ground station's day. The two meet at the daily figure, which is where the margin is taken.

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

budget = DataBudget.from_yaml_file("sample/data/pl_dataflow_model.yaml", "sample/data/orbit.yaml")

budget.generated_per_day    # 225.00 GB
budget.downlinked_per_day   # 252.00 GB
budget.margin               # 0.12 — the link clears 12% more than the payload makes
budget.storage_required()   # 44.35 GB to cover three orbits without a pass
```

A positive margin means the backlog clears; a negative one means data accumulates until something is deleted or a pass is added. `storage_required()` sizes the gap between passes rather than an accumulating backlog — the two coincide only while the budget closes. `tabulated_data()` gives the whole chain as a document, one row per quantity with the assumption behind it, each tagged `input`, `derived`, `margin` or `storage` so the report can be filtered.

## Delta-V budget

A flat list again, one row per manoeuvre, with `phase` and `manoeuvre_type` as the two axes to group over. Each row names a type that says how its `value` becomes a delta-V — a Hohmann transfer between circular altitudes, a collision avoidance hop that is the same transfer doubled when the config says it returns, a plane change at circular velocity, a deorbit impulse, or `given` for anything that needs real analysis done elsewhere. A `recurring` row is counted per year and scaled by the mission duration.

```csv
manoeuvre_id,manoeuvre_name,phase,manoeuvre_type,value,count,recurring,comments
injection_correction,Launcher dispersion correction,Commissioning,altitude_change,12 km,1,false,Semi-major axis dispersion at separation
drag_makeup,Drag make-up,Operations,altitude_change,1.2 km,1,true,Per year at 500 km solar mean
collision_avoidance,Collision avoidance,Operations,collision_avoidance,200 m,4,true,Per year; one-way hop as the drag make-up absorbs the return
deorbit,End-of-life deorbit,Disposal,deorbit,250 km,1,false,Single burn to a 500 x 250 km disposal orbit; natural decay rather than controlled re-entry
```

The `value` column carries whatever its type requires, and is checked against it on load: a length where a velocity belongs is caught at the row that holds it. Margins are one layer rather than two — a single margin on the total, because per-manoeuvre contingency means little when the counts are the uncertain part.

```python
from quicksat.delta_v.budget import DeltaVBudget

budget = DeltaVBudget.from_csv(
    "sample/data/manoeuvres.csv", "sample/data/delta_v_config.yaml", "sample/data/orbit.yaml"
)

budget.total_deltav()               # 116.5 m/s, margin included
budget.total_deltav(margin=False)   # 111.0 m/s
budget.by_phase()                   # Commissioning 22.3, Operations 19.9, Disposal 74.3
budget.propellant_mass(dry_mass)    # 24.89 kg, for a 448.6 kg dry spacecraft
```

`tabulated_deltav()` lays the budget out as a document: every manoeuvre, a subtotal per phase, then the total before margin, the margin line, and the total with it.

`propellant_mass` takes the dry mass as an argument rather than reaching for a `MassBudget`, so the two modules stay decoupled and the sizing loop between them is closed where it can be seen. Nothing is written back: the equipment CSV stays the source of truth for what is actually loaded. In the sample data that loop does not quite close: the budget asks for 24.9 kg where the equipment list carries 22. The disposal choice is what decides it — a single burn to a 500 × 250 km decay orbit costs 74 m/s of the 117 m/s total, where a direct re-entry from the same orbit would cost 152 and put the propellant at 42 kg.

## Documentation

Split along [Diátaxis](https://diataxis.fr/) lines: the sample is there to be followed, the docs to be understood. Files under `docs/` take a `_ref` suffix, so the two halves of a topic cannot be confused.

| | tutorial and how-to | explanation and reference |
|---|---|---|
| Orbit | — | [`docs/orbit_ref.ipynb`](docs/orbit_ref.ipynb) |
| Mass | [`sample/mass_budget.ipynb`](sample/mass_budget.ipynb) | [`docs/mass_budget_ref.ipynb`](docs/mass_budget_ref.ipynb) |
| Data | [`sample/data_budget.ipynb`](sample/data_budget.ipynb) | [`docs/data_budget_ref.ipynb`](docs/data_budget_ref.ipynb) |
| Delta-V | [`sample/delta_v_budget.ipynb`](sample/delta_v_budget.ipynb) | [`docs/delta_v_ref.ipynb`](docs/delta_v_ref.ipynb) |

The sample notebooks work each budget through against one sample satellite — a small Earth observation platform in a 500 km sun-synchronous orbit — in the order you would actually do it. The reference notebooks sit behind them and say why each piece behaves as it does: the data model, unit handling, the input files field by field, how the derived quantities and the margin layers are worked out, and where each budget stops.

## Installation

```bash
conda env create -f environment.yml
conda activate quicksat
pip install -e .
```

## License

GPL-3.0-or-later. See `LICENSE.md`.
