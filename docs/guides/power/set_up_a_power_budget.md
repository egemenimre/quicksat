# How to set up and run a power budget

This guide takes you from the sample files to a power budget of your own. You describe the solar panels, the battery and what each piece of equipment draws. Then you run them over a scenario, check the results, and open the viewer.

The sample flies the scenario sample's three orbits, with cells on four turning wing panels and on the deck. It is a working example, so it gives you correct keys, columns and units to start from.

You need quicksat installed first, and a scenario that runs. The README has the installation steps. [How to set up and run a scenario](../scenario/set_up_a_scenario.md) covers the scenario.

You can also fill in the power files in the editor, a web page that takes you through them step by step. [How to edit, run and view a scenario](../scenario/edit_and_view_a_scenario.md) shows how, for a power folder too. This guide says what each field means, either way.

## 1. Copy the sample data, one folder for each case

A case is one set of conditions to check the sizing against, such as winter and summer, or the start and the end of life. Give each case a folder of its own, outside quicksat, with a copy of the sample data:

```bash
cp -r path/to/quicksat/sample/power/data my_project/winter
cp -r path/to/quicksat/sample/power/data my_project/summer
```

Each folder holds the whole set of power inputs:

- `scenario.yaml`, the case's own copy of the scenario, and the 3D model it names;
- `power_system.yaml`, the panels, the battery and the power conditioning;
- `payload_consumption.csv` and `platform_consumption.csv`, what each piece of equipment draws in each of its group's modes.

The cases may differ in any of them. Winter and summer differ in the scenario's start date, which sets the sun's angle to the orbit and the length of the eclipses. They may differ in the consumption too, such as more power for the heaters in a cold season. A case at the end of life has a lower `loss_factor` and `capacity_factor`.

Do not edit `sample/power/data/` itself. The sample notebooks read it, and the figures in them depend on its contents. The code below assumes a case folder called `winter`, in the folder you run Python from.

## 2. Put your scenario in the case

Replace `scenario.yaml` with your own scenario, and copy the GLB file it names into the folder too. Power takes the panels from the model's parts, so the model should hold the faces of cells as parts of their own. A model is optional: without one, you type the panels in (see the next step).

Each activity gives two modes: the payload's and the platform's. If the scenario has slews, the run gives the platform the mode `slew` while the body turns. The platform's consumption file then needs a `slew` column (see step 4). The payload stays in one of its own modes: the mode of the activity before, or of the activity after, as the activity after chooses.

## 3. Describe the panels

The first part of `power_system.yaml` is the panels:

```yaml
cell_efficiency: 30 %
loss_factor: 0.80
panels:
  wing +y inner: {part: Wing +y inner cells, fill_ratio: 85 %}
  deck: {part: Deck cells, fill_ratio: 80 %}
self_shadowing: {enabled: true, points: 512}
```

- **`cell_efficiency`** is the cells' efficiency at their rated temperature.
- **`loss_factor`** is every loss up to the array's output, as the share of the power left: the cells' temperature, ageing, mismatch between cells, UV, and the array's own wiring. Set it for the year being sized. There is no loss per year and no temperature model.
- **`panels`** names each panel. A panel's `part` is the name of its cells in the 3D model. The part must be flat, and must be the only node of that name. A panel on a wing turns with the wing's articulation in the scenario. `fill_ratio` is the share of the part that the cells cover.
- **`self_shadowing`**, optional, lets the rest of the model shade the panels. Set `enabled: false`, or leave the block out, to switch it off.

A panel can also be typed in, with the direction its cells face in body axes and its area:

```yaml
  side +x: {normal: +x, area: 0.2 m2, fill_ratio: 80 %}
  tilted: {normal: [0, 1, -1], area: 0.1 m2, fill_ratio: 80 %}
```

Use this for a scenario with no model, or to try a panel without editing the model. A typed-in panel stays fixed in body axes, is never shaded and shades nothing. The run notes each one in its output.

Details: [`power_generation_ref.ipynb`](../../power/power_generation_ref.ipynb).

## 4. Write the consumption files

There are two consumption files, one for each part of the spacecraft that has a mode: `payload_consumption.csv` and `platform_consumption.csv`. Each has one row for each piece of equipment of its group that draws power. Leave out the structure, the insulation and anything else that draws none.

Which equipment goes in which file is your choice. The sample puts the mass memory and the X-band transmitter with the payload, as ESA's payload data handling and transmission does. So the payload's `downlink` mode is the data dump, and the platform's `ttc` mode is the TT&C pass.

```csv
equipment_id,equipment_name,subsystem,units_on,eqpt_margin,idle,imaging,downlink,comments
mass_memory,SSDR 2 TB,OBDH,1,10,10 W,30 W,25 W,"Standby, recording, playback"
focal_plane,Focal plane assembly,Payload,1,20,0 W,45 W,0 W,
```

```csv
equipment_id,equipment_name,subsystem,units_on,eqpt_margin,idle,imaging,ttc,slew,comments
obc,SSTL OBC750,OBDH,1,5,10 W,10 W,10 W,10 W,Cold redundant: one of two on
reaction_wheel,Rockwell RSI 45,ADCS,4,5,10 W,12 W,15 W,10 W,
```

Platform equipment that changes with the payload's work takes a platform mode of its own. In the sample, the platform's `imaging` mode holds the solar wings parked and the wheels steadier while the payload images. The scenario's imaging activity sets both: `{payload_mode: imaging, platform_mode: imaging}`.

- **`equipment_id`** is a short name with no spaces, which no other row of the file has.
- **`subsystem`** groups the rows in the plots. A subsystem may appear in both files, such as `Thermal`, and the plots add the two.
- **`units_on`** is how many units draw power, such as one of a cold-redundant pair.
- **`eqpt_margin`** is the equipment's margin in percent: 5 for equipment that has flown, 10 for equipment that needs changes, 20 for new designs.
- **One column for each of the group's modes** gives the power of one unit, averaged over the mode. Every mode the scenario gives a group needs its column in that group's file, the platform's `slew` included. Every cell needs a power, `0 W` included: no mode is assumed to draw what another does.

A column for a mode the scenario does not have, such as `safe`, is allowed. The run notes it as unused. The payload's file needs no `slew` column.

Details: [`power_consumption_ref.ipynb`](../../power/power_consumption_ref.ipynb).

## 5. Size the battery and the conditioning

The rest of `power_system.yaml` is for the budget:

```yaml
battery:
  capacity: 1024 W h
  capacity_factor: 0.80
  max_depth_of_discharge: 30 %
  initial_charge: 100 %
conditioning:
  array_regulator: 0.96
  battery_charge: 0.95
  battery_discharge: 0.95
  distribution: 0.97
system_margin: 5 %
```

- **`capacity`** is what the battery holds when new and full. Write watt-hours as `W h`: astropy does not read `Wh`. From a mass, take the cells it holds: the sample's 12.5 kg of 16 W h cells is 64 cells, 8 in series and 8 in parallel.
- **`capacity_factor`** is the share left in the year being sized, after fade.
- **`max_depth_of_discharge`** is the deepest the battery may go. 30% is a usual limit in low orbit, where it cycles some 5500 times a year.
- **`conditioning`** gives an efficiency for each path the energy takes after the array's output. For a bus fed straight from the battery, with no charge and discharge regulators, give the cells' own efficiencies, about 0.97.
- **`system_margin`** is the margin on all the loads together, on top of each equipment's own.

Details: [`power_budget_ref.ipynb`](../../power/power_budget_ref.ipynb), sections "What the budget needs" and "The losses, in three places".

## 6. Run the budget

The quickest way is the command line:

```bash
python -m quicksat.power winter winter/output
```

It reads the folder's four files and runs the budget. It prints the scenario's summary, any occurrence with a problem, the warnings, the notes on the panels and the loads, and the three checks. Then it writes the viewer into `winter/output/`, and prints the page's path. A check that fails does not stop it, so you can see the failing run in the viewer.

For the tables and the plots, run it in Python or in a notebook instead:

```python
import matplotlib.pyplot as plt

from quicksat.power.budget import run_budget
from quicksat.power.config import PowerSystem
from quicksat.power.consumption import PowerConsumption, run_consumption
from quicksat.power.generation import run_generation
from quicksat.power.plots import balance_plot, charge_plot, panel_power_plot
from quicksat.power.viewer import write_power_viewer
from quicksat.scenario.config import Scenario
from quicksat.scenario.run import run_scenario
from quicksat.utils.plot_helpers import STYLE

plt.style.use(STYLE)

run = run_scenario(Scenario.from_yaml_file("winter/scenario.yaml"))
power_system = PowerSystem.from_yaml_file("winter/power_system.yaml")
generation = run_generation(power_system, run)
consumption = {
    group: PowerConsumption.from_csv(f"winter/{group}_consumption.csv")
    for group in ("payload", "platform")
}
loads = run_consumption(consumption, run)
budget = run_budget(power_system, generation, loads)

print(generation.notes + loads.notes)
budget.checks  # the three checks, each ok or fail, with a sentence
budget.orbit_table  # where the energy goes in each whole orbit
panel_power_plot(generation)  # each panel's power against time
balance_plot(budget)  # the power generated against the power consumed
charge_plot(budget)  # the battery's charge, with the lowest allowed
write_power_viewer(budget, "winter/output")
```

A mistake in a file stops it with an error that says what is wrong, and where. For example, a panel whose part is not flat, or a consumption row with no power for a mode.

Run the scenario for a few orbits at least. The tables count whole orbits from the start of the run, and leave out a cut orbit at the end.

## 7. Check the budget

| Check | What it means | What to do if it fails |
| --- | --- | --- |
| Battery charge | The charge never falls below 1 less the maximum depth of discharge. | A larger battery, or less drawn in eclipse. |
| Energy balance | Each whole orbit has energy to spare: its margin in `orbit_table` is zero or more. | More array: larger panels, wings that track the sun in more modes, or better cells. Or less drawn: fewer loads, shorter activities that draw a lot. |
| Loads met | The battery never runs flat. | Both of the above. |

The energy balance matters as much as the charge. A run that starts with the battery full can keep the charge above its limit for a few orbits while it loses energy every orbit. The orbit's margin shows that at once.

`orbit_table` gives each orbit's energy: generated at the array's output, consumed by the loads, lost in the conditioning, unused once the battery is full, and the charge at the start, the lowest and the end. `loss_table` splits the losses by path.

Run every case the same way, each from its own folder. The sizing must pass every case. The worst case is usually the one with the longest eclipses and the lowest sun on the panels, at the end of life.

## 8. Open and share the viewer

`write_power_viewer` writes three files into the folder you give it, here `winter/output/`. It makes the folder if it does not exist.

- `power_viewer.html` is the page. Double-click it to open it in a browser.
- `scenario.js` holds the run, and `power.js` the budget. The page shows the power only when the two come from the same run.

The page is the scenario viewer, with a Power tab: each panel's power, the loads, the battery's charge and the setup. The Attitude tab shows the body's roll, pitch and yaw, its turn rate and its acceleration, and offers the attitude files for download. The Results tab lists the checks. Write each case to its own output folder, so that one does not replace another.

To share a case, send its whole `output` folder. Whoever gets it opens the page with a double-click, and needs nothing installed.

To pass the attitude to other tools, write it next to the viewer:

```python
from quicksat.scenario.attitude_files import write_attitude_files

write_attitude_files(run, "winter/output")
```

This writes `attitude.ecsv`, with the body's quaternion at each step, and one file for each articulation, such as a solar wing, with its angle. Step 11 of the [scenario guide](../scenario/set_up_a_scenario.md#11-pass-the-attitude-to-other-tools) says what they hold.
