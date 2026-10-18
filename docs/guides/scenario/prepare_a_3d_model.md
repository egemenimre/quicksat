# How to prepare a 3D model

This guide takes a model of your spacecraft from a CAD tool or Blender to a GLB file that quicksat can use. The viewer draws the model as the spacecraft. The articulations turn its parts, such as solar wings. The power budget takes each solar panel's area and direction from its part, and lets the rest of the model shade it.

The power sample's model, `sample/power/data/spacecraft.glb`, is a working example. It has 18 nodes and about 150 triangles. Each wing is one node, with its panels and their cells as children.

You need quicksat installed first. The README has the steps, under "Install". The guide uses Blender for its examples, because it is free and exports GLB. Any tool that writes glTF 2.0 will do. The Scenario Editor draws the model with its parts, articulations, panels and attitudes. So you can check each step before you run anything.

## 1. Decide what the model must hold

The model needs a part for each thing that quicksat names. Everything else is only drawn.

- **A part that turns,** such as a solar wing or an antenna on a one-axis drive, needs one node of its own. Its origin must lie on the drive axis, and its pieces must be its children.
- **A solar panel** needs its cells as a flat part of their own. The part's front face must face the way the cells do.
- **The rest of the body** can be any shape, in as many parts as you like. It shades the panels when self-shadowing is on.

Keep the model simple. A box for the bus, flat plates for the wings, and a few shapes for the instruments are enough for a first pass. The viewer carries the whole file inside `scenario.js`. Self-shadowing tests each point on the panels against every triangle, so more triangles make it slower.

## 2. Set the axes, the units and the origin

quicksat reads the model in body axes and in metres. The model's x, y and z are the body's x, y and z, and quicksat does not turn or scale them.

- **Axes.** Build the model in the body axes that the attitudes in `scenario.yaml` use. In the sample, the imager looks along +z, the cells face -z, and the wings lie along +y and -y. Blender has +z up, so build in Blender's axes and keep them on export (step 6). Step 9 checks the axes against the attitudes.
- **Units.** Blender's default unit is the metre. A CAD export is often in millimetres, so scale it by 0.001.
- **Origin.** Put the model's origin at the point the body turns about, such as the centre of mass. The attitudes turn the body about this point.

## 3. Bring in a CAD model

Skip this step if you build the model in Blender.

- **If the CAD tool exports glTF or GLB,** use that. It keeps the part names and the tree of parts.
- **Otherwise, export each part that quicksat names as its own file,** in STL or OBJ. An STL file holds one mesh with no names, so a single STL of the whole assembly loses the parts.
- **Import the files into Blender,** scale them into metres, and name each part (step 4).
- **Reduce the detail.** CAD meshes often hold many thousands of triangles for bolts and fillets. Delete what does not change the outline, or use Blender's Decimate modifier.

Check the terms of use of any model you did not make yourself.

## 4. Name the parts

quicksat finds a part by the name of its node. Blender exports each object as a node, with the object's name.

- **Give each part that quicksat names a name that no other node has.** An articulation or a panel needs exactly one node of its name. Parts that nothing names may share a name: the sample has two nodes named `Spider`.
- **Make each turning part one node with children, with its origin on the drive axis.** For a wing, put the 3D cursor on the drive axis, such as on the hinge's edge with **Shift+S › Cursor to Selected**. Add an Empty there, and name it `Wing +y`. Its location is its origin, and the part turns about the axis through it. Then parent the wing's pieces to it: select the pieces, then the Empty, then **Ctrl+P › Object**.
- **Draw a turning part at its zero angle.** quicksat measures its angle from where the model draws it. The sample draws its wings with their cells facing -z, so `point: [-z, sun]` turns them toward the sun.

The sample's tree, with the names that its scenario and power files use:

```text
Bus
Front face
Deck housing
Deck cells
Aperture
Spider
Spider
Secondary mirror
Wing +y                  ← articulation, origin on the +y drive axis
  Wing +y inner
  Wing +y inner cells    ← panel
  Wing +y outer
  Wing +y outer cells    ← panel
Wing -y
  ...
```

## 5. Make each solar panel flat, facing out

A panel's part must be flat, and its front face must face the way the cells do. quicksat takes the panel's direction from the front face.

- **Flat** means that every triangle of the part faces within 1 degree of the others.
- **Separate the cells from their substrate.** A wing modelled as a thin box is not flat, because its faces point both ways. In Edit Mode, select the face that holds the cells, then **P**, **Selection**. Name the new object, such as `Wing +y inner cells`, and parent it to the wing.
- **Check which way the face points.** Turn on **Overlays › Face Orientation**: blue is the front, red the back. A red cell face needs **Mesh › Normals › Flip**. **Recalculate Outside** (**Shift+N**) sets a closed part's faces outward.
- **Each panel turns with one articulation at most.** A panel under two turning nodes is refused.

The cells may cover only part of the face. The power file's `fill_ratio` gives the share they cover, so the face can be the whole panel.

## 6. Export the GLB

In Blender, choose **File › Export › glTF 2.0**, and set:

- **Format:** glTF Binary (`.glb`).
- **Include › Transform › +Y Up:** unticked. Ticked, Blender turns the axes, and +z in Blender becomes +y in the file.
- **Data › Mesh › Apply Modifiers:** ticked, so that the mirrors and decimations are exported as you see them.
- **Data › Compression:** off. The viewer cannot decode Draco or meshopt compression, and quicksat refuses the file.

Plain colours are enough. Textures in Basis Universal are refused, for the same reason as compression.

## 7. Check the model

Check the size, the axes and the parts before you use the model. The Scenario Editor shows the model in 3D, so it is the quickest check. Python gives the figures.

**In the Scenario Editor.** Open the editor, as [how to edit, run and view a scenario](edit_and_view_a_scenario.md) shows. On the **Spacecraft** tab, click **choose GLB…** in the 3D model section. The 3D panel draws the model, with arrows along the body axes, and lists its parts:

- **`flat, 0.4026 m²`** is a part that can be a panel, with its area.
- **`not flat`** cannot be a panel. Select it to see by how much its faces differ.
- **`2 nodes`** is a name that two nodes share. No articulation or panel may name it.
- **`4 children`** is a node with no mesh of its own, such as a wing's node.

Select a part to see it highlighted. A flat part also shows an arrow along its front face's direction.

- **Wrong axes** show against the axis arrows: the wings of the sample lie along y, and its aperture faces +z. Wings along z mean the axes turned on export.
- **Wrong units** do not show in the drawing, because the page moves the camera to fit any model. They show in the areas: the sample's wing panel would read 402600 m² in millimetres, in place of 0.4026 m².

**From Python.** `read_model` places every part as the scenario will, in body axes:

```python
from pathlib import Path

import numpy as np

from quicksat.scenario.spacecraft import read_model

model = read_model(Path("my_scenario/spacecraft.glb"))
corners = np.concatenate([part.triangles for part in model.parts]).reshape(-1, 3)
print("from", corners.min(axis=0).round(3), "to", corners.max(axis=0).round(3), "m")
for part in model.parts:
    print(part.name, len(part.triangles))
```

For the sample, it prints the extent first, then each part and its triangle count:

```text
from [-0.35 -1.56 -0.42] to [0.35  1.56  0.302] m
Bus 12
Front face 2
...
```

An extent in the thousands means the model is in millimetres.

## 8. Use it in the scenario and the power files

Put the file in your scenario folder, and name it in `scenario.yaml`, with the articulations:

```yaml
3d_model:
  file: spacecraft.glb
  articulations:
    wing +y: {part: Wing +y, axis: +y, point: [-z, sun], park: {imaging: 0 deg}}
```

Name the cells in `power_system.yaml`:

```yaml
panels:
  wing +y inner: {part: Wing +y inner cells, fill_ratio: 85 %}
```

Check them on the editor's **Spacecraft** tab, which lists the articulations and the panels beside the parts. Select an articulation to see its drive axis and the axis it points, and drag its slider to turn the part. Select a panel to see its part highlighted, with its normal, its area and the area of its cells. A name that matches no part, or more than one, shows in red.

quicksat checks each name again when it loads the files. A missing or shared name gives an error such as `the model has no node named 'Wing +y' in its scene, and an articulation needs exactly one`. A panel part that fails gives `is not flat` or `faces no one way, like a closed box`, with what to change.

Details: [how to set up and run a scenario](set_up_a_scenario.md), step 6, and [how to set up and run a power budget](../power/set_up_a_power_budget.md), step 3. The references explain the model, the articulations and the panels in full: [`scenario_ref.ipynb`](../../scenario/scenario_ref.ipynb), sections "The spacecraft's 3D model" and "Articulations", and [`power_generation_ref.ipynb`](../../power/power_generation_ref.ipynb).

## 9. Check the body axes against the attitudes

The model's axes must agree with the attitudes. A sign error is easy to make, and quicksat cannot catch it, because it does not know which face holds the imager. The imager could look at space, or the panels face away from the sun. The run then shows only poor results, such as too little power.

Check it on the editor's **Operations** tab. Click **Show 3D**, since the 3D panel is hidden on this tab at first. Then select an attitude. The panel draws two arrows on the model, each labelled with its body axis and its direction:

- **The pointed axis,** such as `+z → nadir`, in cyan.
- **The constrained axis,** such as `-y → orbit normal`, in orange.

Check that each arrow leaves the model on the side you mean:

- **An imaging attitude,** such as the sample's `nadir`, `{point: [+z, nadir], ...}`, must have its pointed arrow come out of the imager's aperture. Then the imager looks down.
- **A sun-pointing attitude,** such as the sample's `sun pointing`, `{point: [-z, sun], ...}`, must have its pointed arrow come out of the face with the cells. Then the panels face the sun, and not away from it. The panel's normal arrow, on the **Spacecraft** tab, must point the same way.
- **A tracking attitude,** such as `track Svalbard`, must have its arrow come out of the face with the antenna.

An arrow on the wrong side means a sign error, in the attitude or in the model. Change the attitude's axis, such as `-z` for `+z`, or turn the model and export it again. The arrows show the axes before any `offset`. The text under the 3D view names the offset.

An articulation needs the same check. On the **Spacecraft** tab, its pointing arrow, such as `-z → sun`, must point the same way as its cells' normal arrow. Otherwise the wing turns its cells away from the sun.
