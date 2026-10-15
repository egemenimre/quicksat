# How to edit, run and view a scenario

This guide takes you round the loop of the scenario and power work. You edit the input files in the editor, run them, read the results, and look at the run in the viewer. Then you change something, and go round again.

The loop is the same for a scenario folder and for a power folder. A power folder holds its own copy of the scenario, so its editor edits the scenario, the power system and the consumption together.

You need quicksat installed first. The README has the steps. What each field of the files means is in the other two guides: [how to set up and run a scenario](set_up_a_scenario.md) and [how to set up and run a power budget](../power/set_up_a_power_budget.md).

## 1. Pick a folder

To try the loop, use a sample folder: `sample/scenario/data/` or `sample/power/data/`. Their editor pages are written already, so you can skip step 2. When you are done, `git restore sample/` puts the samples back as they were.

For real work, copy a sample folder into your own project folder, outside quicksat, as the other guides say:

```bash
cp -r path/to/quicksat/sample/power/data my_project/winter
```

The steps below use `my_project/winter`.

## 2. Write the editor page

```bash
python -m quicksat.editor my_project/winter my_project/winter/editor
```

This writes `my_project/winter/editor/editor.html`. Python reads the folder's files and puts them inside the page, with the 3D model and any orbit file that the scenario names. It also reads the files with quicksat's own loaders: the full check.

The page needs no Python and no server. Double-click it to open it in a browser.

A page you have already can open the folder instead: click **Open a folder…** on its first Setup step, and pick `my_project/winter`. The page reads every file it knows there, and fills every step. quicksat's loaders do not read a folder opened this way, so its files have only the page's simple check, and their full check shows *not run*.

## 3. Edit

The page has two ways in, and both edit the same data:

- **Setup** takes you through every file, step by step, from the orbit to the consumption. The small **i** by a step's title opens its explanation: why the fields matter, the options and what follows from them. Each card on the other tabs has the same sign, and a section's explanation stays open or closed in both places. Back and Next are at the top.
- **The other tabs** hold the same fields by theme: orbit and time, spacecraft, operations, activities, power and consumption. Use them to change one thing without going through every step. A bar at the top of each tab names its file, says where it came from and whether you have changed it, and has **Open** and **download** for that file.

The first Setup step lists the folder's files: where each came from, whether it has changed, and two checks. The **simple check** is the page's own, on names, units and ranges, as you type. The **full check** is what quicksat's loaders said when Python wrote the page. The Files tab shows both under each file.

Names are chosen from lists. An activity picks its attitude and its mode, and an articulation picks its part of the model. Renaming an attitude, a target or a mode changes every use of it. Deleting one that is in use asks again, and says what uses it.

**Show 3D**, at the top right, opens the 3D panel. It shows the model, its parts and the body axes. Click a row, such as a panel, an articulation or an attitude, to see it there: a panel's normal and area, an articulation's axis with a slider to turn it, or an attitude's two axes. The panel starts open on the steps that need it, and you can hide it on any step or tab.

The chip at the top right counts the problems that the page finds: a missing value, a name that does not exist, a percentage out of range. Click it for the list. A red count on a tab, or a red step number, shows where each problem is. The page cannot tell whether a trigger ever comes, or whether the battery lasts. Only the run can.

The page keeps no draft. Save before you close it or reload it, or your changes are lost.

## 4. Move your `#` comments into `comments` fields

Saving rewrites each file. It writes the editor's own help as `#` lines, and drops every other `#` comment. Your notes are kept only in the `comments` fields that every block of a file has.

If the files hold `#` comments that the editor did not write, a banner under the header says so. Click **review them**, or open the Files tab. Each comment is listed with its file, its line, and the block it belongs to:

- **move** puts it in that block's `comments` field;
- **drop** lets it go;
- **move all** and **drop all** do the same for every comment left.

Do this before you first save a file that you wrote by hand. The samples' explanations show up here too: they are `#` comments. Each comment goes to the block below it, so write your own `#` comments on the lines above what they describe.

## 5. Save, and put the files back

Open the Files tab to see each file as it will be written. Then save, from there or from the last Setup step:

- **download the zip** gives the whole folder in one file;
- **download** next to a file, or on a tab's bar, gives that file alone.

A saved file shows as *downloaded* until you change it again.

The browser puts the downloads in its downloads folder. Copy the files over the ones in `my_project/winter/`. Check their names: a browser can add a number, such as `scenario (1).yaml`, to a file it has downloaded before.

## 6. Run

Run the folder from the command line. For a power folder:

```bash
python -m quicksat.power my_project/winter my_project/winter/output
```

For a scenario folder, with no power files, use `python -m quicksat.scenario` in the same way. Either prints the results, writes the viewer into the output folder, and prints the page's path. A file that quicksat cannot read stops the run with an error that names the problem, and nothing is written. Fix it in the editor, and save again.

For the tables and the plots, run a notebook instead. For a sample folder, that is [`sample/scenario/scenario.ipynb`](../../../sample/scenario/scenario.ipynb), or [`sample/power/power_budget.ipynb`](../../../sample/power/power_budget.ipynb) for the power. For your own folder, run the code in step 8 of the [scenario guide](set_up_a_scenario.md#8-run-the-scenario), or in step 6 of the [power guide](../power/set_up_a_power_budget.md#6-run-the-budget), with your folder's path.

## 7. Read the results

- **The scenario:** the summary line and the `status` column of the activity table. Every status should be `ok`, or `cut at end` for the last activity. Step 9 of the [scenario guide](set_up_a_scenario.md#9-check-the-activities) says what to do about each other status.
- **The power:** the three checks, and each orbit's energy in `orbit_table`. Step 7 of the [power guide](../power/set_up_a_power_budget.md#7-check-the-budget) says what to do when a check fails.

## 8. Open the viewer

The run writes the viewer's page into the output folder you gave it: `scenario_viewer.html` for a scenario, and `power_viewer.html` for a power budget. Double-click it. It shows the run in 3D, with the ground track, the timeline and the activity table, and the power if there is one. Its Attitude tab shows the roll, pitch and yaw, the turn rate and the acceleration, and the warnings, and offers the attitude files for download.

If the page is open already, reload it after each run. It then reads the new run.

## 9. Go round again

If the page is still open, keep editing: it holds your changes. If you closed it, open it again and click **Open a folder…** to read the folder's files as they are now. Or write the page again, to have quicksat's loaders check the files too:

```bash
python -m quicksat.editor my_project/winter my_project/winter/editor
```

Then reload the page in the browser. One round is then: edit, save, put the files back, run, read, view, and open the folder again.
