# The power model

This explains how quicksat's power budget works, and why it is built the way it is. It covers the generation, the losses, the battery and the consumption, and how they meet over a scenario run.

It is an explanation, not a reference. The reference notebooks give every key and column, the exact formulas, and the checks against Orekit:

- [`power_generation_ref.ipynb`](../power/power_generation_ref.ipynb), for the solar panels;
- [`power_consumption_ref.ipynb`](../power/power_consumption_ref.ipynb), for the loads;
- [`power_budget_ref.ipynb`](../power/power_budget_ref.ipynb), for the battery and the checks.

[How to set up and run a power budget](../guides/power/set_up_a_power_budget.md) takes you through the files.

## What it answers

Does the power system support the scenario? The budget answers two questions:

- Does the battery's charge stay above its limit?
- Does each orbit bring in at least the energy it uses?

It answers them over a run on a real orbit, step by step. The run follows the scenario's attitudes, slews, eclipses and modes. A first-pass budget often works from orbit averages instead: a sunlit power, an eclipse load and an eclipse length. quicksat follows the run because the averages hide where the energy is drawn. A downlink in eclipse costs more than the same downlink in sunlight, since its energy passes through the battery.

## The path of the energy

The energy takes one of these paths, from the sun to the loads:

```
sun ──> panels ──> array output ──> array regulator ──> bus ──> distribution ──> loads
                                                         │ ▲
                                          battery charge │ │ battery discharge
                                                         ▼ │
                                                       battery
```

Each step along the path loses some energy. The budget counts each loss once, at the place where it happens.

## The generation

At each step of the run, a panel generates

P = Φ × A × f × η × k × max(cos θ, 0) × L × ℓ

- **Φ, the solar flux,** comes from the sun's luminosity and its distance. It is about 1361 W/m² at 1 au, and changes by ±3.3% over a year. So the start date of the scenario matters.
- **A, the area,** and the direction the cells face, come from the panel's part in the 3D model. A panel can also be typed in, with a normal and an area.
- **f, the fill ratio,** is the share of the panel that the cells cover.
- **η, the cell efficiency,** is the cells' efficiency at their rated temperature, such as 30% for triple-junction GaAs.
- **k, the loss factor,** takes every loss up to the array's output. These are the cells' temperature, ageing, mismatch between cells, UV and the array's own wiring. It is set for the year being sized, such as the end of life.
- **θ, the sun's angle to the cells,** comes from the body's orientation at each step. Only the side the cells face generates.
- **L, the light,** is the share of the sun's disk that the Earth does not hide. It is 1 in sunlight, 0 in the umbra, and in between in the penumbra.
- **ℓ, the lit fraction,** is the share of the panel that no other part of the model shades. It is 1 when the self-shadowing is off, which it is unless the power system file turns it on.

**The panels come from the 3D model.** The model already holds the panels' sizes and directions, so they are not typed in twice. A panel on a solar wing turns with the wing's articulation, which the scenario sets. With the self-shadowing on, the model's other parts can shade a panel, such as a payload housing on the deck. A typed-in panel has no shape, so it stays fixed in body axes and is never shaded.

**There is no temperature model, and no ageing per year.** The cell efficiency and the loss factor take them in. The user sets them for the case being sized.

**The Earth's light is left out.** Sunlight reflected by the Earth and the Earth's infrared add a little power to panels that face the Earth. Leaving them out is on the safe side.

## The losses, in three places

A first-pass budget often takes one efficiency for the whole power system. quicksat splits the losses into three places instead:

1. **Up to the array's output:** the loss factor, in the generation.
2. **The power conditioning:** one efficiency for each path after the array's output.
   - `array_regulator`: from the array to the bus.
   - `battery_charge`: from the bus into the battery, through the charge regulator and the cells.
   - `battery_discharge`: back out of the battery to the bus.
   - `distribution`: from the bus to the loads, through the switches, the fuses and the harness.
3. **Fixed overheads, as loads:** the power unit's own electronics and the heaters are rows of the consumption files.

The reason is that energy routed through the battery pays both of its paths, about 10% with the samples' 0.95 each way. Energy used in sunlight does not. One efficiency for the whole system would hide that, and would understate a long eclipse. The split also keeps each loss in the file of the person who knows it.

## The battery

The battery is an energy store. It is described by four figures:

- **The capacity:** what it holds when new and full, such as 1024 W h.
- **The capacity factor:** the share left in the year being sized, after fade, such as 0.80 at the end of life.
- **The maximum depth of discharge:** the deepest it may go. In low orbit, the battery cycles some 5500 times a year, so 30% is a usual limit.
- **The initial charge:** the charge at the start of the run, full by default.

Its voltage, its current and its temperature are not modelled. So a limit on the charge rate is not checked.

## The consumption

**Two groups, each with its modes.** The spacecraft has two modes at any time: the payload's and the platform's. Each activity of the scenario names both. Each group has its own consumption file, with one row for each piece of equipment and one column for each of its modes. The user chooses which equipment goes in which file. The samples put the mass memory and the X-band transmitter with the payload, as ESA's payload data handling and transmission does.

**A mode's power is an average.** A heater that a thermostat switches, or a magnetorquer that runs now and then, gives its mean power over the mode. Every cell needs a power, `0 W` included, so that no mode is assumed to draw what another does.

**A slew is a platform mode.** While the body turns between attitudes, the run gives the platform the mode `slew`, and its file needs a column for it. The payload keeps one of its own modes through the turn, since its work, such as a file transfer, need not depend on the attitude. It keeps the mode of the activity before or the activity after, as the activity after chooses.

**Two layers of margin.** Each row carries its own margin, as in the mass budget: 5% for equipment that has flown, 10% for equipment that needs changes, and 20% for new designs. The samples' heaters take 20% too, since their power depends on the thermal design. The power system file adds a system margin on all the loads together.

**The modes change at exact times.** A mode can start or end between two steps of the run's grid. The loads' energy is worked out from the mode intervals, not from the grid, so no energy is lost at a mode change.

## The budget, step by step

The budget follows the energy over each step of the run's grid:

1. The loads, with both margins, need their energy at the bus: their energy divided by `distribution`.
2. The array's energy reaches the bus times `array_regulator`.
3. A surplus charges the battery, times `battery_charge`, until it is full. What a full battery cannot take is unused.
4. A shortfall comes from the battery, which gives it at `battery_discharge`. If the battery is empty, the rest is unmet.

The energy over a step is exact. The generation changes in a straight line between steps, and the loads change at exact times.

## The checks

- **Battery charge:** the charge never falls below 1 less the maximum depth of discharge.
- **Energy balance:** each whole orbit has a margin of zero or more.
- **Loads met:** the battery never runs flat.

The first check alone is not enough. A run that starts with a full battery can stay above the limit for a few orbits, while it loses energy every orbit. Over a longer mission, the battery would run down. So the energy balance matters as much.

The energy balance counts the energy that a full battery could not take as if it had taken it. So the margin does not depend on where the orbit starts, nor on how full the battery is.

## Where it stops

- **Energy, not current.** The battery's voltage, current and temperature are not modelled.
- **Steady efficiencies.** Each path keeps one efficiency, whatever its load.
- **Unused energy is lost.** Once the battery is full, the array's spare power is not used.
- **Average powers.** Inrush currents and a heater's on and off are not followed.
- **No safe mode by itself.** A safe mode is a mode like any other, with its own columns and activities.
- **No strings of cells.** A shaded area costs only its share of a panel's power. A real string loses more, since its weakest cell limits it.
- **Short runs.** A run covers an orbit to a day or two. Seasons and the worst beta angle each need a scenario of their own, such as winter and summer.

The reasons behind these choices are in [`decisions.md`](decisions.md): entries 10 to 12 for the domain, the panels and the losses, and entry 24 for the two groups of modes.
