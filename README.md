# quicksat

Basic satellite sizing tool: mass budget, power subsystem and battery sizing, and basic delta-V. Deliberately spartan — the aim is a first-pass sizing, not a full systems engineering environment.

## Status

- **Mass budget** — implemented.
- **Power and battery sizing** — not yet specified.
- **Delta-V** — not yet specified.

## Mass budget

A satellite is described by two files. The first is a flat equipment list, one row per item — nothing is nested, because `location`, `responsibility` and `subsystem` are cross-cutting axes rather than a hierarchy, and any of them can then be summed over independently.

```csv
equipment_id,equipment_name,location,responsibility,subsystem,unit_mass,eqpt_margin,number_of_units,mass_class,comments
reaction_wheel,Rockwell RSI 45,Platform,Platform,ADCS,7.0 kg,10,4,equipment,Pyramid configuration
imu,Northrop LN-200S,Platform,Platform,ADCS,750 g,5,1,equipment,Entered in grams
star_tracker,Jena Astro HP,Payload,Platform,ADCS,1.2 kg,5,2,equipment,Redundant pair
hydrazine,Hydrazine load,Platform,Platform,Propulsion,22.0 kg,0,1,propellant,Carried as delta-V reserve
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

budget.in_orbit_mass()               # 472.83 kg  - separated wet mass
budget.on_ground_mass(propellant=0)  # 467.55 kg  - dry mass at launch
budget.in_orbit_mass(propellant=50)  # 461.83 kg  - half-way through the mission
budget.subsystem_mass("ADCS")        #  39.50 kg
```

All of these return a pint `Quantity` in kg.

The same rows can be summed over any of the three axes, and all three reconcile to the same total because they are three cuts of one table rather than three calculations:

```python
budget.by_location()
budget.by_responsibility()
budget.by_subsystem(propellant=0)
```

And the whole budget as a document — every item, grouped into subsystem blocks within each location, with the subtotals, the margins and the dry, propellant and wet masses in reading order:

```python
budget.tabulated_mass()
```

## Documentation

Split along [Diátaxis](https://diataxis.fr/) lines: the sample is there to be followed, the docs to be understood.

| | |
|---|---|
| [`sample/mass_budget.ipynb`](sample/mass_budget.ipynb) | **tutorial and how-to** — the whole thing worked through against a sample satellite, in the order you would actually do it |
| [`docs/mass_budget_ref.ipynb`](docs/mass_budget_ref.ipynb) | **explanation and reference** — the data model, unit handling, the two files column by column, how harness and the two margin layers are derived, the mass cases, and the limitations |

## Installation

```bash
conda env create -f environment.yml
conda activate quicksat
pip install -e .
```

## License

GPL-3.0-or-later. See `LICENSE.md`.
