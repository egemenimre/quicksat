# How to edit and run the sizing files

This guide takes you round the loop of the sizing work. You edit the input files in the Sizing Editor, then run the budgets in their notebooks and read the results. Then you change something, and go round again.

The Sizing Editor edits the files of the five sizing budgets: the mission, mass, data, delta-V and agility. The scenario and power files have an editor of their own: see [how to edit, run and view a scenario](../scenario/edit_and_view_a_scenario.md).

You need quicksat installed first. The README has the steps. What each file holds, and how to load it in Python, is in [how to initialise a satellite for analysis](initialise_a_satellite.md).

## 1. Pick a folder

To try the loop, use the sample folder, `sample/sizing/data/`. Its editor page is written already, so you can skip step 2. When you are done, `git restore sample/` puts the sample back as it was.

For real work, copy the sample folder into your own project folder, outside quicksat:

```bash
cp -r path/to/quicksat/sample/sizing/data my_satellite
```

The steps below use `my_satellite`. The folder need not hold every budget's files. The page starts any that are missing, as new, for you to fill in.

## 2. Write the editor page

```bash
python -m quicksat.editor my_satellite my_satellite/editor
```

This writes `my_satellite/editor/editor.html`. Python reads the folder's files and puts them inside the page. It also reads the files with quicksat's own loaders: the full check. The command picks the editor from the files: a folder with a `scenario.yaml` gets the Scenario Editor, and a folder of sizing files gets the Sizing Editor.

The page needs no Python and no server. Double-click it to open it in a browser.

A page you have already can open the folder instead: click **Open a folder…** on its first Setup step, and pick `my_satellite`. Or drop the folder, or its files, onto the page. A single file dropped on a tab's bar replaces that tab's file. The page reads every sizing file it finds there. quicksat's loaders do not read a folder opened this way, so its files have only the page's simple check, and their full check shows *not run*.

## 3. Edit

The page has two ways in, and both edit the same data:

- **Setup** takes you through every file, step by step: the mission, then each budget in turn. The small **i** by a step's title opens its explanation: why the fields matter, the options and what follows from them. Back and Next are at the top.
- **The other tabs** hold one budget each: Mission, Mass, Equipment, Data, Delta-V and Agility. Use them to change one thing without going through every step. A bar at the top of each tab names its file, says where it came from and whether you have changed it, and has **Open** and **download** for that file.

The first Setup step lists the files by budget. The mission file comes first, because the data, delta-V and agility budgets all read it. Each file shows where it came from, whether it has changed, and two checks. The **simple check** is the page's own, on names, units and ranges, as you type. The **full check** is what quicksat's loaders said when Python wrote the page. The Files tab shows both under each file.

The Mission step, and each budget's first step, have a box for your comments on the file as a whole. They go in the `comments` field at the top of the file.

Some steps work out figures from the fields as you type. The Mission step gives the orbital period, the orbits a day, the orbital speed and the ground track speed. The data generation step gives the data rate after compression. These are first figures only: the notebooks give the budgets' own.

**The Equipment tab** holds the equipment list as a table. The box above it shows only the rows that hold its text, in the id, the name, the location or another column. The location is chosen from the locations of the Mass tab. The totals under the table add the rows by location, as entered and with the equipment margins. The notebook also adds the harness and the system margins, so its totals are larger.

Renaming a location changes every row that uses it. Deleting one that is in use asks again, and says what uses it.

The chip at the top right counts the problems that the page finds: a missing value, a location that does not exist, a percentage out of range. Click it for the list. A red count on a tab, or a red step number, shows where each problem is. The page cannot tell whether the satellite meets its needs. Only the notebooks can.

The page keeps no draft. Save before you close it or reload it, or your changes are lost.

## 4. Move your `#` comments into `comments` fields

Saving rewrites each file. It writes the editor's own help as `#` lines, and drops every other `#` comment. Your notes are kept only in the `comments` fields that every block of a YAML file has. A CSV file has a `comments` column instead, which the page keeps as written.

If the files hold `#` comments that the editor did not write, a banner under the header says so. Click **review them**, or open the Files tab. Each comment is listed with its file, its line, and the block it belongs to:

- **move** puts it in that block's `comments` field;
- **drop** lets it go;
- **move all** and **drop all** do the same for every comment left.

Do this before you first save a file that you wrote by hand. The sample's explanations show up here too: they are `#` comments. Each comment goes to the block below it, so write your own `#` comments on the lines above what they describe.

## 5. Save, and put the files back

Open the Files tab to see each file as it will be written. Then save, from there or from the last Setup step:

- **download my_satellite.zip**, named after the folder, gives the whole folder in one file;
- **download** next to a file, or on a tab's bar, gives that file alone.

The page always saves every budget's files. A saved file shows as *downloaded* until you change it again. To leave out the `#` help lines, untick **write the # help lines** before you save.

The browser puts the downloads in its downloads folder. Copy the files over the ones in `my_satellite/`. Check their names: a browser can add a number, such as `mission (1).yaml`, to a file it has downloaded before.

## 6. Run the budgets

The sizing budgets have no command-line run. Run each one in its notebook:

- [`sample/sizing/mass_budget.ipynb`](../../../sample/sizing/mass_budget.ipynb)
- [`sample/sizing/data_budget.ipynb`](../../../sample/sizing/data_budget.ipynb)
- [`sample/sizing/delta_v_budget.ipynb`](../../../sample/sizing/delta_v_budget.ipynb)
- [`sample/sizing/agility_roll.ipynb`](../../../sample/sizing/agility_roll.ipynb) and [`sample/sizing/agility_pitch.ipynb`](../../../sample/sizing/agility_pitch.ipynb)

Each notebook reads its files from `DATA`, which is `sample/sizing/data` in the samples. For your own folder, copy the notebook into your project, and set `DATA` to your folder's path:

```python
DATA = Path("my_satellite")
```

Or load the budgets in a notebook of your own, with the code in step 3 of [how to initialise a satellite](initialise_a_satellite.md#3-load-the-satellite).

A file that quicksat cannot read stops the notebook with an error that names the file, the row and the field. Fix it in the editor, and save again. Step 4 of [how to initialise a satellite](initialise_a_satellite.md#4-check-that-it-loaded) lists the most common causes.

## 7. Go round again

If the page is still open, keep editing: it holds your changes. If you closed it, open it again and click **Open a folder…** to read the folder's files as they are now. Or write the page again, to have quicksat's loaders check the files too:

```bash
python -m quicksat.editor my_satellite my_satellite/editor
```

Then reload the page in the browser. One round is then: edit, save, put the files back, run the notebooks, read the results, and open the folder again.

[How to close the sizing budgets](close_the_sizing_budgets.md) says which results to carry into the files after each round, and when to stop.
