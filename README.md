# quicksat

Basic satellite sizing tool: mass budget, power subsystem and battery sizing, and basic delta-V. Deliberately spartan — the aim is a first-pass sizing, not a full systems engineering environment.

## Status

- **Mass budget** — implemented.
- **Power and battery sizing** — not yet specified.
- **Delta-V** — not yet specified.

## Mass budget

The satellite is described by a flat equipment CSV plus a config YAML. Nothing is nested: `location`, `responsibility` and `subsystem` are cross-cutting axes, so any of them can be summed over independently.

### Equipment CSV

| column | meaning |
|---|---|
| `equipment_id` | short identifier, no whitespace (`star_tracker`) |
| `equipment_name` | full name, free text (`Jena Astro HP`) |
| `location` | where it sits — the computation axis |
| `responsibility` | who owns it — reporting only |
| `subsystem` | `ADCS`, `EPS`, ... — reporting only |
| `unit_mass` | mass of one unit, with its unit (`100 kg`, `750 g`) |
| `equipment_margin` | per-item contingency, percent |
| `number_of_units` | how many are flown |
| `mass_class` | `equipment` or `propellant`; blank means `equipment` |
| `comments` | free text |

Masses are parsed with [pint](https://pint.readthedocs.io/), so a dimensionally wrong entry such as `100 W` in the mass column is rejected on load rather than quietly becoming a number.

### Config YAML

Margins and harness are keyed on location:

```yaml
locations:
  Platform:
    system_margin: 20     # percent, applied to the location subtotal
    harness_fraction: 5   # percent of this location's equipment CBE
    harness_margin: 10    # percent, the harness's own contingency
  Payload:
    system_margin: 15
    harness_fraction: 3
    harness_margin: 10
```

`Launcher` is a reserved location name and needs no entry: it defaults to no margins, no harness, and being dropped at separation. Any *other* location used in the CSV but missing from the config is an error rather than a silent zero.

### Harness

Harness is not entered by hand. One row per location is derived as `harness_fraction` of that location's equipment CBE, given its own `harness_margin`, and injected before aggregation. The base excludes propellant, and uses CBE rather than margined mass so the estimate does not compound the equipment margins.

### Mass cases

Two switches give the four standard reporting masses:

| | `with_propellant=True` | `with_propellant=False` |
|---|---|---|
| `ON_GROUND` | launch mass | dry mass at launch |
| `IN_ORBIT` | separated wet mass | in-orbit dry mass |

The separation interface is entered as two ordinary equipment rows — the satellite-side half at `location: Platform`, the launcher-side half at `location: Launcher` — with their real masses. There is no split factor to configure, and an asymmetric interface costs nothing extra.

## Usage

```python
from quicksat.mass.budget import MassBudget, MassCase

budget = MassBudget.from_csv("sample/equipment.csv", "sample/budget_config.yaml")

budget.total(case=MassCase.ON_GROUND, with_propellant=True)   # launch mass
budget.by_subsystem(case=MassCase.IN_ORBIT, with_propellant=False)
```

`sample/mass_budget.ipynb` works through the whole thing against the sample data.

## Installation

```bash
conda env create -f environment.yml
conda activate quicksat
pip install -e .
```

## License

GPL-3.0-or-later. See `LICENSE.md`.
