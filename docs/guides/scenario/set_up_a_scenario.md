# How to set up and run a scenario

This guide takes you from the sample files to a scenario of your own. You write one file that holds the orbit and the activities. Then you run it, check the results, and open the viewer.

The sample flies a 510 km sun-synchronous orbit for three orbits. It is a working example, so it gives you correct keys, triggers and units to start from.

You need quicksat installed first. The README has the steps, under "Installation".

## 1. Copy the sample data

Copy the `sample/scenario/data` folder and give the copy your own name:

```bash
cp -r sample/scenario/data my_scenario
```

Then edit `my_scenario/scenario.yaml`. Do not edit `sample/scenario/data/` itself. The sample notebook reads it, and the figures in it depend on its contents.

The folder can go anywhere. The code below assumes it is called `my_scenario` and sits in the folder you run Python from.

The scenario does not read the sizing domain's `mission.yaml`. It needs a real orbit, with an epoch and a node, so it has its own.

## 2. Define the orbit

`orbit` takes exactly one of four keys:

- **`sso`** builds a sun-synchronous orbit from an altitude and a local time of the ascending node, as in `sso: {altitude: 510 km, ltan: "13:30"}`. Write the time in quotes, because YAML reads an unquoted `13:30` as a number. The orbit's epoch is the start of the run.
- **`tle_file`** names a file that holds exactly one TLE. A relative path is taken from the folder of `scenario.yaml`. Use a TLE whose epoch is close to the start. A run more than 7 days from the epoch gets a warning, because SGP4 loses accuracy away from it.
- **`omm_file`** names a file that holds exactly one OMM element set: the same elements as a TLE, at full precision. It may be KVN, XML, JSON or CSV, as CelesTrak and Space-Track give them.
- **`trajectory_file`** names a file of positions and velocities, such as from a propagator: ECSV, or a CCSDS OEM in KVN. quicksat tells them apart by their first line. The frame must be centred on the Earth, such as ITRS or EME2000. Space the samples 60 s apart in low orbit, and let the file reach a few samples past the run at each end. If the orbit has a manoeuvre, give it as an OEM with a new segment from the manoeuvre on.

Details: [`scenario_ref.ipynb`](../../scenario/scenario_ref.ipynb), section "The orbit".

## 3. Set the period of the run

- **`start`** is a UTC time, such as `2026-10-01T09:00:00`.
- **`duration`** is a time, such as `5 h`, or a number of orbits, such as `3 orbits`.
- **`step`** is the time step of the grid, 10 s by default.

Keep the run short: an orbit to a day or two. The sun hardly moves in that time. For the seasons, write one scenario for each, such as winter and summer.

The events are located between the steps, to 1 ms. A shadow shorter than one step can still be missed. So do not make the step longer than your shortest shadow.

Details: [`scenario_ref.ipynb`](../../scenario/scenario_ref.ipynb), section "The period of the run".

## 4. Define the attitudes

Define the attitudes your activities use: `nadir`, `sun pointing`, or both. Each names two body axes, written with their sign, such as `+z` or `-y`.

```yaml
attitudes:
  nadir: {nadir_axis: +z, orbit_normal: -y}
  sun pointing: {sun_axis: -z, constrain_to_orbit_normal: -y}
```

- **`nadir`** points `nadir_axis` at the centre of the Earth. It keeps `orbit_normal` along the orbit normal.
- **`sun pointing`** points `sun_axis` at the sun, and takes exactly one second axis. `constrain_to_orbit_normal` keeps the body still over an orbit. `constrain_to_nadir` keeps that axis facing the Earth. But then the body spins fast when the sun is close to the nadir line.

Details: [`scenario_ref.ipynb`](../../scenario/scenario_ref.ipynb), section "The attitudes".

## 5. Add the slews, if you want them

Without a `slew` block, attitude changes are instant. With one, the body turns into each new attitude before the activity that needs it starts:

```yaml
slew:
  max_rate: 0.7 deg/s
  max_acceleration: 0.08 deg/s2
  settling_time: 20 s
```

Nothing reads these values from the agility budget, so copy them across by hand. The agility budget gives them for each axis, as `max_rate()` and `max_acceleration()`. Take the slower of roll and pitch. Then the timeline does not count on more agility than the satellite has. In the sizing sample, roll gives 0.74 deg/s and 0.083 deg/s2, and pitch gives 0.77 deg/s and 0.087 deg/s2. The settling time is in the agility file too.

Details: [`scenario_ref.ipynb`](../../scenario/scenario_ref.ipynb), section "Slews".

## 6. Add a 3D model, if you have one

The viewer draws the spacecraft from a GLB file, the binary form of glTF. Put the file in `my_scenario/`, and name it in `scenario.yaml`:

```yaml
3d_model: spacecraft.glb
```

Without it, the viewer draws a 1 m cube. Build the model in body axes and in metres, with its origin at the point the body turns about. Then the model's x, y and z are the body's. In Blender, untick "+Y Up" when you export it, or the axes turn. Export it without Draco or meshopt compression, because the viewer cannot decode them.

Parts of the model can turn to face the sun, such as solar wings. Make each such part one node, with its origin on its drive axis and its pieces as children. Then list it under `articulations`, with `file` for the model:

```yaml
3d_model:
  file: spacecraft.glb
  articulations:
    wing +y: {part: Wing +y, axis: +y, sun_axis: -z, park: {imaging: 0 deg}}
```

- **`part`** is the node's name in the model.
- **`axis`** is the body axis it turns about.
- **`sun_axis`** is the part's axis to turn to the sun, as the model draws it. It must use a different body axis from `axis`.
- **`range`**, optional, limits the turn, as in `range: [-90 deg, 90 deg]`.
- **`park`**, optional, holds a fixed angle in the modes it names. Each mode must be one that an activity has.

The part tracks the sun at each step, and the viewer turns it.

Details: [`scenario_ref.ipynb`](../../scenario/scenario_ref.ipynb), sections "The spacecraft's 3D model" and "Articulations".

## 7. Write the activities

Each activity is a list: the trigger that ends it, the attitude, the mode, and an optional constraint.

```yaml
activities:
  - [eclipse entry, sun pointing, idle, sunlit]
  - [eclipse exit, nadir, idle, eclipse]
  - [10 min, nadir, downlink]
```

- **The list is one repeat.** The first activity starts at the start of the run. Each later one starts where the one before it ends. The run repeats the list until the duration ends.
- **The trigger** is a time, such as `20 min`, or the next event after the activity starts. The events are the shadow edges, the nodes and latitude crossings. An event can take an offset, such as `eclipse entry - 1 min`.
- **The mode** is any name. Power will say what each mode draws.
- **The constraint** is the illumination the activity expects: `sunlit`, `penumbra`, `umbra`, or `eclipse` for either of the last two.

Use event triggers where you can. Events keep the list in step with the orbit, while fixed times drift against it.

Details: [`scenario_ref.ipynb`](../../scenario/scenario_ref.ipynb), section "The activities", which lists every trigger.

## 8. Run the scenario

```python
import matplotlib.pyplot as plt

from quicksat.scenario.config import Scenario
from quicksat.scenario.plots import gantt_chart, ground_track_map
from quicksat.scenario.run import run_scenario
from quicksat.scenario.viewer import write_scenario_viewer
from quicksat.utils.plot_helpers import STYLE

plt.style.use(STYLE)

scenario = Scenario.from_yaml_file("my_scenario/scenario.yaml")
run = run_scenario(scenario)

print(run.activity_summary)
run.activity_table  # one row for each occurrence of an activity
gantt_chart(run)  # the illumination, the attitude and the mode against time
ground_track_map(run, run.mode, "Ground track by mode")
write_scenario_viewer(run, "my_scenario/output")
```

A mistake in the file stops the load with an error that says what is wrong. For example, a trigger such as `eclipse entri` gets a list of the triggers that work. An activity that names an attitude the file does not define is refused too.

## 9. Check the activities

Start with the summary line, then the `status` column of the activity table. Each occurrence is `ok`, or names one or more problems:

| Status | What to do |
| --- | --- |
| `outside constraint` | The activity spends `outside [s]` seconds in the wrong illumination. End the activity before it at the shadow edge. To change attitude before an eclipse, give that time an activity of its own. |
| `negative duration` | A negative offset ends the activity before it starts. Make the offset smaller, or end the activity at another event. |
| `event never came` | The event does not happen in the run, such as a latitude higher than the orbit reaches. Pick another event, or run longer. |
| `slew starts early` | The slew into this activity takes longer than the activity before it. Lengthen that activity, or raise the slew limits if the satellite allows it. |
| `cut at end` | The activity runs past the end of the run, and is cut there. That is normal for the last one. |

The Gantt chart marks two of the problems in red. A box goes around an activity outside its constraint. A dashed line marks an activity with a negative duration. Edit `scenario.yaml` and run it again, until every status is `ok`, or `cut at end` for the last activity.

Details: [`scenario_ref.ipynb`](../../scenario/scenario_ref.ipynb), section "The statuses".

## 10. Open and share the viewer

`write_scenario_viewer` writes two files into `my_scenario/output/`. It makes the folder if it does not exist.

- `scenario_viewer.html` is the page. Double-click it to open it in a browser.
- `scenario.js` holds the data of the run.

The page shows the run in 3D, with the ground track, the timeline and the activity table. It needs no Python, no server and no network. Keep the two files together, because the page reads `scenario.js` from its own folder.

After you change the scenario, run it again and reload the page. The page then reads the new `scenario.js`.

To share the run, send the whole `output` folder. Whoever gets it opens the page with a double-click, and needs nothing installed.
