# quicksat

[![CircleCI](https://dl.circleci.com/status-badge/img/gh/egemenimre/quicksat/tree/master.svg?style=svg)](https://dl.circleci.com/status-badge/redirect/gh/egemenimre/quicksat/tree/master)
[![codecov](https://codecov.io/github/egemenimre/quicksat/graph/badge.svg?token=ANT5QB5UB8)](https://codecov.io/github/egemenimre/quicksat)

A first-pass satellite sizing tool, in two parts:

- **[Sizing](#sizing)** works out the mass, data, delta-V and attitude agility budgets. Each budget is a table, worked out from a few input files and a reference orbit.
- **[Scenario and power](#scenario-and-power-with-the-viewer)** flies the satellite through a timeline of activities on a real orbit, and checks the power: what the solar panels generate, what the equipment draws, and the battery between them. A 3D viewer shows the run.

The two parts share no input files. The budgets use a reference orbit, while the scenario needs a real orbit, with an epoch and a node. quicksat is kept simple on purpose. It gives a first-pass sizing, not a full systems engineering environment. [Quickstart](#quickstart) lists a guide for each task.

![The viewer with the power sample: the orbit, the body, the current data, the ground track, the timeline, the net power and the battery](https://raw.githubusercontent.com/egemenimre/quicksat/master/docs/images/power_viewer.webp)

*The power sample in the viewer, during the downlink to Svalbard. The wings have turned to face the sun.*

## Install

```bash
pip install quicksat
```

Then copy the samples into a folder of your own. They come from GitHub, for the version you installed, with their data, their notebooks, and the viewers and editor pages written from them:

```bash
python -m quicksat init my_satellite
```

The command prints where everything went, and how to start the editor's server. The folder holds `sizing/`, `scenario/` and `power/`, and each of them holds:

- `data/`: the input files, the ones you edit;
- `editor/`: the editor page, written for `data/`;
- `output/`: the viewer, written by a run, for the scenario and the power;
- the notebooks: the worked examples, for Jupyter, such as `pip install jupyterlab`.

Where this page says `sample/`, read `my_satellite/`.

To work on quicksat itself, clone the repository, and install it from there:

```bash
conda env create -f environment.yml
conda activate quicksat
pip install -e .
```

## Quickstart

Each guide takes you through one task, from the samples to files of your own. Pick the one for what you want to do. Or read on: the rest of this page is a short introduction to both parts, with the samples.

| To do this | Read |
|---|---|
| Start the sizing files for your own satellite | [How to initialise a satellite](https://github.com/egemenimre/quicksat/blob/master/docs/guides/sizing/initialise_a_satellite.md) |
| Edit the sizing files in the Sizing Editor, and run the budgets | [How to edit and run the sizing files](https://github.com/egemenimre/quicksat/blob/master/docs/guides/sizing/edit_the_sizing_files.md) |
| Make every sizing budget pass at the same time | [How to close the sizing budgets](https://github.com/egemenimre/quicksat/blob/master/docs/guides/sizing/close_the_sizing_budgets.md) |
| Add a manoeuvre to the delta-V budget | [How to add a manoeuvre](https://github.com/egemenimre/quicksat/blob/master/docs/guides/sizing/add_a_manoeuvre.md) |
| Write a scenario: the orbit, the attitudes and the activities | [How to set up and run a scenario](https://github.com/egemenimre/quicksat/blob/master/docs/guides/scenario/set_up_a_scenario.md) |
| Edit, run and view a scenario in the Scenario Editor | [How to edit, run and view a scenario](https://github.com/egemenimre/quicksat/blob/master/docs/guides/scenario/edit_and_view_a_scenario.md) |
| Build the list of activities in the Activity Designer | [How to plan the activities](https://github.com/egemenimre/quicksat/blob/master/docs/guides/scenario/plan_the_activities.md) |
| Bring your spacecraft's 3D model in from CAD or Blender | [How to prepare a 3D model](https://github.com/egemenimre/quicksat/blob/master/docs/guides/scenario/prepare_a_3d_model.md) |
| Plan a link to a data relay satellite | [How to use a relay satellite](https://github.com/egemenimre/quicksat/blob/master/docs/guides/scenario/use_a_relay_satellite.md) |
| Size the power system: the panels, the consumption and the battery | [How to set up and run a power budget](https://github.com/egemenimre/quicksat/blob/master/docs/guides/power/set_up_a_power_budget.md) |

## Sizing

The sizing sample is a small Earth observation satellite on a 500 km sun-synchronous orbit. Its files are in `sample/sizing/data/`. The workflow:

1. **Edit the files.** Double-click [`sample/sizing/editor/editor.html`](https://github.com/egemenimre/quicksat/blob/master/sample/sizing/editor/editor.html) to open the Sizing Editor in your browser. Its Setup tab takes you through every file, step by step, and the other tabs edit one file or one budget each. Save the files, as a zip or one by one, and put them back in `sample/sizing/data/`. The files are YAML and CSV, with units written out, such as `750 g` or `800 Mbit/s`, so they can be edited by hand too.
2. **See the budgets.** The editor's Budgets tab shows every budget's tables and checks, as quicksat works them out. Its **Export to Excel** button writes them into an .xlsx workbook, a copy to pass on. A page opened from a file shows them as they were when the page was written. To have them follow each change, serve the page, and open the address the server prints:

   ```bash
   python -m quicksat.editor serve sample/sizing/data
   ```

3. **Run the notebooks** in `sample/sizing/`, in the order below, to see each budget step by step. Each reads the files and builds its budget. Delta-V and agility also read the mass budget.
4. **Read the tables.** Each notebook ends with its budget laid out as a document, and the figures that answer the usual questions. The data, delta-V and agility notebooks also check their figures: against the requirements in `requirements.yaml`, and the propellant required against the propellant loaded.

| Budget | What it gives | Sample | Reference |
|---|---|---|---|
| Mission | The reference orbit and the design life, which every budget shares | | [mission](https://github.com/egemenimre/quicksat/blob/master/docs/sizing/mission_ref.ipynb) |
| Requirements | What the mission asks of the satellite: the slews it needs, and the duration without image downlink, which the agility and data budgets check | | [agility](https://github.com/egemenimre/quicksat/blob/master/docs/sizing/agility_ref.ipynb), [data](https://github.com/egemenimre/quicksat/blob/master/docs/sizing/data_budget_ref.ipynb) |
| Mass | Dry and wet mass, by location, subsystem and owner, with two layers of margin | [mass](https://github.com/egemenimre/quicksat/blob/master/sample/sizing/mass_budget.ipynb) | [mass](https://github.com/egemenimre/quicksat/blob/master/docs/sizing/mass_budget_ref.ipynb) |
| Data | Data made against data sent down each day, and the memory needed between passes against the memory flown | [data](https://github.com/egemenimre/quicksat/blob/master/sample/sizing/data_budget.ipynb) | [data](https://github.com/egemenimre/quicksat/blob/master/docs/sizing/data_budget_ref.ipynb) |
| Delta-V | Delta-V by phase and type, and the propellant it needs | [delta-V](https://github.com/egemenimre/quicksat/blob/master/sample/sizing/delta_v_budget.ipynb) | [delta-V](https://github.com/egemenimre/quicksat/blob/master/docs/sizing/delta_v_ref.ipynb) |
| Agility | Slew times about roll and pitch, from the wheels and the inertia, with a wheel failed or not, and the slews the mission needs | [roll](https://github.com/egemenimre/quicksat/blob/master/sample/sizing/agility_roll.ipynb), [pitch](https://github.com/egemenimre/quicksat/blob/master/sample/sizing/agility_pitch.ipynb) | [agility](https://github.com/egemenimre/quicksat/blob/master/docs/sizing/agility_ref.ipynb) |
| Radiator | The payload’s heat account over a scenario run, which sizes its radiators and heaters | [payload thermal](https://github.com/egemenimre/quicksat/blob/master/sample/power/payload_thermal.ipynb) | [payload thermal](https://github.com/egemenimre/quicksat/blob/master/docs/power/payload_thermal_ref.ipynb), [explanation](https://github.com/egemenimre/quicksat/blob/master/docs/explanations/payload_thermal_model.md) |

The sample works one satellite through each budget. The reference explains each input field, how each figure is worked out, and where the budget stops. For your own satellite, see [how to initialise a satellite](https://github.com/egemenimre/quicksat/blob/master/docs/guides/sizing/initialise_a_satellite.md). [How to edit and run the sizing files](https://github.com/egemenimre/quicksat/blob/master/docs/guides/sizing/edit_the_sizing_files.md) goes round the loop in the Sizing Editor. [How to close the sizing budgets](https://github.com/egemenimre/quicksat/blob/master/docs/guides/sizing/close_the_sizing_budgets.md) runs every budget in rounds, until a round passes them all and changes nothing. [How to add a manoeuvre](https://github.com/egemenimre/quicksat/blob/master/docs/guides/sizing/add_a_manoeuvre.md) adds a row to the delta-V budget, and shows its cost.

## Scenario and power, with the viewer

The power sample flies a 510 km sun-synchronous orbit for three orbits, with imaging, a downlink to Svalbard, and wings that turn to the sun. Its files are in `sample/power/data/`: the scenario, the 3D model, the power system, and the consumption tables of the payload and of the platform.

### With the editor's server

The editor's server runs on your computer only. It serves the Scenario Editor, and runs quicksat on the files when you ask for a run or for the viewer.

1. **Start the server,** in a terminal where quicksat is installed:

   ```bash
   python -m quicksat.editor serve sample/power/data sample/power/output
   ```

   The first folder holds the input files, and the second is where the viewer goes. Keep the terminal open while you work.
2. **The editor opens in your browser** by itself. If it does not, open the address that the server prints, such as `http://localhost:8780/quicksat/editor?key=...`.
3. **Edit the files.** The Setup tab takes you through every file, step by step, with an explanation of each choice. The other tabs edit the same data by theme, and a side panel shows the 3D model.
4. **Design the activities.** The Activities tab is the Activity Designer: the run above the list of activities, with the orbit in 3D, the ground track and the timeline. **Generate scenario** runs the list as it is on the page, in a second or two after the first run, and writes nothing. At first the list runs once, and the time after it is grey. **Repeat the list** repeats it until the run ends. Select a row to see where its activity falls, or click the timeline to find the row. [How to plan the activities](https://github.com/egemenimre/quicksat/blob/master/docs/guides/scenario/plan_the_activities.md) walks through it.
5. **Create the viewer.** Click **Create the viewer**, on the Files tab or on the last Setup step, "Save and view". quicksat runs the files as they are on the page, saved or not, in a few seconds. It writes `sample/power/output/power_viewer.html`, and the page shows the results and any problem.
6. **Open the viewer.** Click **Open the viewer**. The viewer opens in a tab of its own: the editor does not open it by itself. It shows the run in 3D, with the ground track, the timeline, the power and the attitude.
7. **Go round again.** Change something, click **Update the viewer**, then **Open the viewer** again, or reload the viewer's tab.
8. **Keep your changes.** Download the files from the page, as a zip or one by one, and put them back in `sample/power/data/`. On the Activities tab, **Save into the folder** writes the scenario file there itself, after a confirm. Nothing else on the page changes the folder's files.
9. **Stop the server** when you are done, with its button at the top right of the page, or with Ctrl+C in its terminal. It also stops by itself after 48 h with no editor page open.

![The editor's Activities tab: the orbit, the ground track, the timeline and the passes over Svalbard above the list of activities, with the downlink selected](https://raw.githubusercontent.com/egemenimre/quicksat/master/docs/images/activity_designer.webp)

*The Activity Designer, with the list run once. The downlink is selected, and the time after the list is grey. Under the list's title, each row says what the run made of it.*

For the scenario sample, start it with `sample/scenario/data sample/scenario/output`. For the sizing sample, start it with `sample/sizing/data` alone: the Sizing Editor writes no viewer.

### By hand, with a notebook or a command

1. **Edit the files.** Double-click [`sample/power/editor/editor.html`](https://github.com/egemenimre/quicksat/blob/master/sample/power/editor/editor.html) to open the editor in your browser. Its Setup tab takes you through every file, step by step, with an explanation of each choice. The other tabs edit the same data by theme, and a side panel shows the 3D model. Change something, such as the battery's capacity or an activity's trigger. Then save the files, as a zip or one by one, and put them back in `sample/power/data/`.
2. **Run the budget.** Run [`sample/power/power_budget.ipynb`](https://github.com/egemenimre/quicksat/blob/master/sample/power/power_budget.ipynb) in Jupyter, or `python -m quicksat.power sample/power/data sample/power/output` from the command line. Either flies the scenario, works out the generation, the loads and the battery, and checks the budget. `python -m quicksat.thermal` with the same folders does the same, then prints the payload's heat account.
3. **Read the results.** The notebook shows each orbit's energy, the battery's charge, and three checks. The command prints the checks only. In the sample, the lowest charge is 84.9%, above its 70% limit, and every orbit has at least 42.2 W h to spare.
4. **See the run in the viewer.** Both write [`sample/power/output/power_viewer.html`](https://github.com/egemenimre/quicksat/blob/master/sample/power/output/power_viewer.html). Double-click it to see the run in 3D, with the ground track, the timeline, the power and the attitude. Its Attitude tab also gives the attitude as files for other tools.

![The editor's Articulations step, with the wing +y selected and turned in the 3D panel](https://raw.githubusercontent.com/egemenimre/quicksat/master/docs/images/file_editor.webp)

*The editor's Articulations step. The selected wing shows in the 3D panel, turned with the slider.*

![The viewer's Power tab: the timeline, the power generated and consumed, the battery's charge, the current power and the power setup](https://raw.githubusercontent.com/egemenimre/quicksat/master/docs/images/power_viewer_power_tab.webp)

*The viewer's Power tab. The power and the battery's charge follow the timeline, with the power setup beside them.*

The scenario sample works the same way, for the timeline alone: [`sample/scenario/editor/editor.html`](https://github.com/egemenimre/quicksat/blob/master/sample/scenario/editor/editor.html), then [`sample/scenario/scenario.ipynb`](https://github.com/egemenimre/quicksat/blob/master/sample/scenario/scenario.ipynb) or `python -m quicksat.scenario sample/scenario/data sample/scenario/output`, then `sample/scenario/output/scenario_viewer.html`.

| Part | What it gives | Sample | Reference |
|---|---|---|---|
| Scenario | The timeline on a real orbit: eclipses, attitudes, slews, and passes over ground stations and relay satellites, checked against each activity's needs | [scenario](https://github.com/egemenimre/quicksat/blob/master/sample/scenario/scenario.ipynb) | [scenario](https://github.com/egemenimre/quicksat/blob/master/docs/scenario/scenario_ref.ipynb) |
| Power generation | Each solar panel's power, with the wings that turn and the model's own shadows | [generation](https://github.com/egemenimre/quicksat/blob/master/sample/power/power_generation.ipynb) | [generation](https://github.com/egemenimre/quicksat/blob/master/docs/power/power_generation_ref.ipynb) |
| Power consumption | What the equipment draws in each of the payload's and the platform's modes | [consumption](https://github.com/egemenimre/quicksat/blob/master/sample/power/power_consumption.ipynb) | [consumption](https://github.com/egemenimre/quicksat/blob/master/docs/power/power_consumption_ref.ipynb) |
| Power budget | The battery's charge through the run, and whether each orbit has energy to spare | [budget](https://github.com/egemenimre/quicksat/blob/master/sample/power/power_budget.ipynb) | [budget](https://github.com/egemenimre/quicksat/blob/master/docs/power/power_budget_ref.ipynb) |

[How to edit, run and view a scenario](https://github.com/egemenimre/quicksat/blob/master/docs/guides/scenario/edit_and_view_a_scenario.md) goes round this loop in full, for the samples or a folder of your own. For what each field means, see [how to set up and run a scenario](https://github.com/egemenimre/quicksat/blob/master/docs/guides/scenario/set_up_a_scenario.md) and [how to set up and run a power budget](https://github.com/egemenimre/quicksat/blob/master/docs/guides/power/set_up_a_power_budget.md). [How to prepare a 3D model](https://github.com/egemenimre/quicksat/blob/master/docs/guides/scenario/prepare_a_3d_model.md) takes your spacecraft's model from CAD or Blender to the viewer and the power budget. [How to use a relay satellite](https://github.com/egemenimre/quicksat/blob/master/docs/guides/scenario/use_a_relay_satellite.md) plans a link to a data relay, from its element sets to the time the antenna tracks it.

**The editors** open with the files of the folder that their page was written for. **Open a folder…**, on the first Setup step, reads any other folder, and **Open** on a tab reads one file. Or drop a folder, or its files, onto the page, and a file onto its tab's bar. Or write a page for a folder of your own. A folder with a `scenario.yaml` gets the Scenario Editor, and a folder of sizing files gets the Sizing Editor:

```bash
python -m quicksat.editor sample/power/data sample/power/editor
```

**Keep your notes in `comments` fields.** Every block of a file can hold one, and so can the file as a whole, in the sizing files too. The editors write their own help as `#` lines, and replace any other `#` comments when they save. When an editor opens a file with such comments, it lists them, and moves each one you choose into a `comments` field. Write a `#` comment on the lines above what it describes, so that it goes to the right block.

## Documentation

The documentation follows the [Diátaxis](https://diataxis.fr/) split. The samples are tutorials, the guides show how to do one task, and the references explain how each part works. The notebooks, their data and the tests are grouped in three domains: `sizing`, `scenario` and `power`. Each set of notebooks reads its own copy of the inputs, so a change to a sample cannot change a figure in a reference.

Two explanations describe a model as a whole, with no code to run: [the power model](https://github.com/egemenimre/quicksat/blob/master/docs/explanations/power_model.md), and [the payload thermal model](https://github.com/egemenimre/quicksat/blob/master/docs/explanations/payload_thermal_model.md).

Two documents cover the project as a whole:

- [`decisions.md`](https://github.com/egemenimre/quicksat/blob/master/docs/explanations/decisions.md) records the decisions that shaped quicksat, and why each was made.
- [`conventions.md`](https://github.com/egemenimre/quicksat/blob/master/docs/reference/conventions.md) holds the rules for the code and the notebooks: units, constants and tests. Read it before changing the code.

## License

GPL-3.0-or-later. See [`LICENSE.md`](https://github.com/egemenimre/quicksat/blob/master/LICENSE.md).
