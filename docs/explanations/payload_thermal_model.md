# The payload's thermal model

**Agreed on 2026-10-24, and built on 2026-10-25.** The reference is [`payload_thermal_ref.ipynb`](../power/payload_thermal_ref.ipynb), which gives every key and formula, and the worked example is [`sample/power/payload_thermal.ipynb`](../../sample/power/payload_thermal.ipynb).

This explains how quicksat sizes the payload's radiators and heaters, and why the model is built the way it is. It covers the heat the payload dissipates, the heat its surfaces absorb and radiate, and how they meet over a scenario run. It is a sub-domain of [the power model](power_model.md), and cannot exist without it. Its code is in `quicksat.thermal`, and its files sit in the power folder.

## What it answers

Does each activity, mode and orbit bring in or lose too much heat? The model answers this for the payload only, and sizes its radiators and its heaters. It does not size the platform's thermal control.

It works over a scenario run, as power does, and not on fixed figures, as the sizing budgets do. The heat in changes with the activities: the payload's modes set the dissipation, and the attitude sets the sun on each radiator. A run shows which activity brings in too much heat, and which mode needs a heater.

## The payload's boundary

The payload is wrapped in MLI, and the model takes the MLI as a perfect insulator. No heat crosses it. So heat crosses the payload's boundary in four places only:

1. **Dissipation:** the payload's equipment inside the MLI.
2. **Heaters:** the payload's heater lines, together in one row.
3. **Heat flows:** fixed powers in or out, such as through the interface with the platform.
4. **Surfaces:** the radiators, and an aperture if there is one.

Every term is positive when heat goes into the payload. So a surface's emission is the one term that is always negative.

## Dissipation and heaters

**Dissipation.** Each row of `payload_consumption.csv` gets a `thermal` column. A row marked `inside_mli` dissipates all its power inside the payload, at its power in each payload mode. A row marked `outside_mli` dissipates outside, and the model leaves it out.

**Heaters.** One row, marked `heater`, holds all the payload's heater lines together. Its power in each payload mode is the total of every heater line in that mode. It also dissipates inside the MLI. The file may have one heater row at most, since a mode's balancing heater power, below, is one figure. The heater powers stay in the consumption file, so power and thermal read one number.

**No margins.** Power adds each row's equipment margin, and the system margin, since more power is the safe side for power. For the heaters, less dissipation is the safe side, since the payload is then colder. So the thermal model takes each row's power without any margin. For the radiators, this is the optimistic side: with the margins, they would have more heat to give out. So the radiators need a check with the margins too, as [Sizing takes decisions](#sizing-takes-decisions) says.

## Heat flows

A heat flow is a power that crosses the boundary somewhere other than a surface. It is positive into the payload, so `-3 W` means 3 W leaves. A flow is either one power for every mode, or a power for each payload mode:

```yaml
heat_flows:
  platform interface: -3 W
  x-band rf: {idle: 0 W, imaging: 0 W, downlink: -5 W}
```

The first is the conduction through the payload's mounts to the platform. The second is the X-band transmitter's radio output. The transmitter's row draws 55 W in `downlink` and is marked `inside_mli`, so all 55 W count as dissipation. The antenna sends about 5 W of that out as radio waves, and the flow takes those 5 W back out.

A flow given by mode needs a power for every payload mode, `0 W` included, as the consumption columns do. Then no mode is assumed to take another's flow.

## The surfaces

**A surface is defined as a solar panel is.** It names a flat part of the 3D model, or is typed in with a normal and an area. A surface under an articulation turns with it. With the self-shadowing on, the model's other parts shade the sun on it, as they shade a panel. They do not hide the Earth from it.

Each surface also takes three properties, and a fourth that is optional:

- `absorptance`, α: the share of sunlight it absorbs, such as 0.20 for white paint. Set it for the year being sized, as power's `loss_factor` is. White paint's α rises over the mission, from about 0.2 to 0.4 or more.
- `emissivity`, ε: the share of a black body's infrared it emits, such as 0.85. It also absorbs that share of the Earth's infrared.
- `temperature`: its design temperature, such as `273 K`. For a radiator, it is the radiator's own, below the equipment's, as [Kinds of radiator](#kinds-of-radiator) explains.
- `fixed_temperature`: `true` when something else holds the surface at its temperature, such as the telescope's own heaters. Without the key, the surface floats, which matters only for the equilibrium temperature below.

**Temperatures in kelvin.** Write each temperature in kelvin, such as `293 K`, as the samples do. A temperature in Celsius, such as `20 °C`, is accepted too, and turned into kelvin when the file is read. Kelvin is preferred because astropy, which reads the units, handles Celsius less reliably. It treats °C as a unit with an offset, and some ways of writing it do not read. Every computation works in kelvin, and the output gives every temperature in kelvin. A ΔT is a difference, so it is the same in K as in °C.

**An aperture is the opening, not the mirror.** The model's aperture is the opening at the front of the telescope. It is the front of the telescope's baffle, or an opening in the bus's face with a vaned tube behind it, as in the sample. The opening takes in light from the whole hemisphere in front of it. Light near the axis reaches the mirror. Light at a wider angle lands on the baffle's walls or the tube's vanes, which are part of the telescope too. So that heat still enters the payload, and the opening absorbs as a flat plate does. The walls also radiate out through the opening, over the whole hemisphere. So the flat plate's cos θ for the sun, and its view factor to the Earth, suit the opening.

**What to enter for an aperture.** Its area is the opening's. Its absorptance and emissivity are the baffled tube's effective values, not the mirror coating's. A blackened, baffled tube absorbs nearly everything that enters it, so both are about 0.9 to 0.98. An aluminium mirror's own emissivity is about 0.03, which would be the wrong figure here. The sample's 0.90 and 0.90 are in the right range.

**An aperture's temperature.** It is the mean of the parts that show through the opening, each weighted by its share of the view. These are mostly the baffle's walls or the tube's vanes, the secondary mirror and its spider. The vanes see space, so they run colder than the telescope. The mean then lies below the telescope's own temperature. The sample takes 273 K, and fixes it, since the telescope's control holds it. The temperature matters far more than the emissivity: 273 K gives a quarter less emission than 293 K.

**Where the flat plate does not suit an aperture:**

- **The mirror and the focal plane** see only a narrow cone, and the sun reaches them only inside the baffle's cutoff angle. The model cannot separate this, since it keeps one account for the whole payload.
- **A baffle outside the boundary,** outside the MLI or with a radiator of its own, puts the aperture at the mirror. The narrow view then applies, and a flat plate overstates the aperture's heat. The baffle's own heat exchange is then missing from the account.
- **A cold baffle front** usually runs colder than the telescope. The telescope's own temperature then overstates the aperture's emission.
- **An opening deep in the structure** sees less of the Earth than a flat plate does. The model does not shade the Earth, so it overstates the Earth's terms, as "Where it stops" says below.

**A surface radiates at its design temperature.** It gives εσAT⁴ to deep space at each step, with T its design temperature, which stays constant. σ is the Stefan-Boltzmann constant.

**No temperature node, and no heat capacity.** The model does not follow the payload's temperature. The aim of a design is to keep the payload in balance, or to keep any imbalance short. A constant design temperature is then a fair assumption. [How far to trust the figures](#how-far-to-trust-the-figures) gives the sample's swing.

## The heat a surface absorbs

A surface absorbs heat from three sources: the sun, the sunlight that the Earth reflects, and the Earth's own infrared.

**The sun.** At each step, a surface absorbs

Q_sun = Φ × α × A × max(cos θ, 0) × L × ℓ

Φ, θ, L and ℓ are the same as in the power generation: the solar flux, the sun's angle to the surface's normal, the light, and the lit fraction. The output gives each surface's sun angle over the run, and the time and the power of any sun it sees. A radiator should ideally see none.

**The Earth's view factor.** The Earth's two terms depend on how much of the Earth a surface sees. This is the view factor F of a flat plate to a sphere. It has a closed form in two angles: the angle between the surface's normal and nadir, and the Earth's angular radius from the satellite. There are three cases:

- **Full view:** the whole visible disk of the Earth lies in front of the surface. Then F is the cosine of the angle to nadir times the square of the sine of the angular radius.
- **Partial view:** the surface's plane cuts the Earth's disk, and F has a longer closed form.
- **No view:** the Earth lies wholly behind the surface, and F is 0.

**Earth infrared.** At each step, a surface absorbs

Q_IR = q_IR × F × ε × A

q_IR is the Earth's infrared flux, 237 W/m² by default. It does not depend on the sun, so a surface that faces the Earth absorbs it in eclipse too.

**Albedo.** At each step, a surface absorbs

Q_albedo = Φ × a × F × α × A × max(cos ζ, 0)

a is the Earth's albedo, 0.30 by default. ζ is the sun's zenith angle at the point below the satellite. So the albedo falls as the satellite nears the terminator, and is zero over the night side.

The user asked for albedo. Earth infrared is included too, since it is often larger than albedo for a surface that faces the Earth.

**The Earth's values vary.** The defaults, 0.30 and 237 W/m², are means over the whole globe and the year. The local values change with the latitude, the ground below, the clouds and the season. Clouds raise the albedo but lower the infrared, so the two rarely peak together. The shorter the time, the wider the spread. A few minutes over a cloud deck or ice can see much more albedo than the mean, while a whole orbit evens much of it out.

So the right values depend on the scenario: the orbit's inclination, the length of the activities that matter, and the case being sized. NASA TM-2001-211221, *Guidelines for the Selection of Near-Earth Thermal Environment Parameters for Spacecraft Design*, gives hot and cold pairs by inclination and by averaging time. The model takes one pair for the whole run. So a hot case takes higher values throughout, and a cold case lower ones. Taking both high together is on the safe side for the hot case.

The values matter. In the power sample, 0.1 more albedo, or 25 W/m² more infrared, adds about 11 W h to the net heat of the three-orbit run. It also lowers idle's balancing heater by about 2.3 W, or 6 %.

## The account

At each step of the run's grid, the net power into the payload is the heat in less the heat out:

net = dissipation + heaters + heat flows + absorbed − emitted

The model sums the net over each activity, each payload mode and each whole orbit. It gives each sum as a mean power in W, and as an energy in W h.

- **A positive net:** heat builds up. The radiators would run above their design temperature.
- **A negative net:** the payload cools. It needs more heater power, or a smaller radiator.

## By activity, and by mode

The model gives the account by activity and by payload mode, since the two answer different questions.

**The heaters are set per payload mode.** So the table by mode is where the heater powers are set.

**Two activities in one mode can differ.** In the samples, `nadir before eclipse` and `eclipse in nadir` are both in the payload mode `idle`. Only the first is sunlit, so its radiators may absorb sun and albedo. So the table by activity shows where heat builds up.

**A mode's balancing heater power** is the heater power that brings the mode's net energy over the run to zero. It is the mode's deficit before any heater, divided by the run's time in that mode. It is never below zero, since a heater cannot cool. A mode with a surplus even with no heater shows a radiator that is too small.

**The run balancing heater power** brings the run's net energy to zero instead. The heater runs only in the modes that lose heat, and each gets the same share of its own balancing power. The share is the part of their deficit that the modes that gain heat do not cover. So no mode gets more than its balancing power. With one cold mode, as in the sample, it is the run's deficit before any heater, divided by the time in that mode. If the hot modes cover the whole deficit, the share is zero: the run gains heat even with no heater, and the radiator is too small.

## The equilibrium temperature

A W h figure alone does not say whether an imbalance matters. So for each activity and each mode, the model also gives an equilibrium ΔT. It is how far the surfaces would move from their design temperatures if the activity, or the mode, went on forever.

At equilibrium, the heat out equals the heat in, with the mean powers over the activity or the mode:

Σ εᵢσAᵢTᵢ⁴ = dissipation + heaters + heat flows + absorbed

This is one equation, with a temperature for each surface. So the model moves all the floating surfaces by the same ΔT, with Tᵢ = Tᵢ,design + ΔT. It solves for ΔT numerically. Scaling every temperature by one factor also has a closed form, but it moves a hotter surface by more kelvins, which is harder to read. The left side only grows as ΔT grows, so there is at most one answer.

- **A fixed surface** keeps its design temperature, and its emission stays as it is.
- **Every surface fixed:** nothing can move, so there is no ΔT, and the output says so.
- **More heat out than in:** if the heat flows take out more than everything else brings in, no temperature can balance the equation. There is no answer, and the output says so.

## Kinds of radiator

The model treats a radiator as a flat surface at one temperature. A real radiator differs from that, and by how much depends on its kind. A small satellite usually has one of two kinds: a patch, or a panel with heat pipes.

**A radiative patch** is an area of the structure, painted white or covered with optical solar reflectors. The equipment is mounted on the inside, behind it. The heat flows from the box into the panel, and spreads sideways through it. A patch costs almost no mass. But it works only where the equipment sits, so the box's place fixes the radiator's place.

**A radiator panel with heat pipes** is a panel of its own, with heat pipes in it or on it. The pipes carry the heat from the equipment, and spread it across the panel. So the panel can sit on whichever face sees the least sun and Earth, away from the equipment. It costs the mass of the panel and of the pipes.

**The drop to the radiator.** The equipment runs warmer than its radiator, by the drop along the path between them. For a box on a patch, the drop is at the box's mounting interface. For heat pipes, it is mostly at the bolted joints at each end. Either is usually a few kelvin, and more with a poor joint or a long path. A plain aluminium bracket in place of heat pipes can drop 10 K or more: 30 W through 1.7 W/K is 18 K. So the radiator's design temperature is the equipment's, less the drop.

**Fin efficiency.** A panel cools as the heat spreads away from where it enters, so its far parts emit less. The fin efficiency η is the panel's real emission divided by εσAT⁴, with T the temperature where the heat enters. Rough values, for ε = 0.85 near 290 K:

| Radiator | η |
|---|---|
| Panel with heat pipes every 10 to 15 cm | 0.85 to 0.95 |
| Patch on a 1.5 mm aluminium plate, with its edge 30 cm from the box | about 0.65 |
| Patch on a honeycomb panel with 0.3 to 0.5 mm face sheets, edge 30 cm from the box | 0.35 to 0.45 |
| The part of a patch right under the box | close to 1 |

The model has no fin efficiency, and emits from the whole area at the design temperature. For a heat pipe panel, it then overstates the emission by 5 to 20 %. For a patch that spreads far from its box, it can overstate it two or three times.

**How to allow for it.** Enter the design temperature as T × η^¼. The full area then emits what the real panel does, and still absorbs the sun and the Earth over its full area. For example, a radiator at 273 K is entered at 266 K for η = 0.9, and at 217 K for η = 0.4. The output then gives that temperature, not the radiator's. A smaller area would give the same emission, but would understate the heat the radiator absorbs.

**Variable conductance and diode heat pipes.** A variable conductance heat pipe shuts part of the radiator off as the payload cools. A diode heat pipe stops heat from flowing back into the payload when the radiator is warmer, such as when it sees the sun. The model has neither, and links the whole radiator to the payload in every mode. So it overstates the heat lost in a cold mode, and the heater needed for it. It also lets the sun's heat on a radiator into the payload. Both are on the safe side: the first for the heaters, the second for the hot case.

**The view to space.** The model emits each surface into the whole hemisphere in front of it, and takes all of it as deep space. A radiator next to a wing, an antenna or a part of the body has part of that view blocked. It then emits less, and takes in their infrared, and a wing in the sun is warm. The model leaves this out, so keep each radiator's view to space clear.

**What the model does not check.** A heat pipe carries a limited power, so size the pipes for the peak dissipation, not the mean. On the ground, gravity acts on the fluid, so a heat pipe is tested level.

## Sizing takes decisions

The model gives the figures, but it does not size the payload by itself. Sizing takes decisions that the code cannot take. They come from the mission, from systems engineering and from safety. The power budget is the same: the code checks a design, and the user chooses it.

**The two balancing powers answer different questions.** The table by mode gives both, and the Scenario Editor's Thermal tab has a button for each: Balance each mode and Balance the run.

- **Each mode balances: the heater to install.** Each mode's heater is its balancing power. No mode loses heat, but a hot mode still gains heat, since a heater cannot cool. So the run warms from orbit to orbit, and the heaters give more energy than the payload needs. The figure is still the one to install. A thermostat holds the payload at its set point. Once the heat of a hot mode has left, it holds the set point at about the cold mode's balancing power. So that power must be there, for a long stay in the coldest mode too.
- **The run balances: the heater's mean draw.** The heater runs in the modes that lose heat only, and brings the run's net energy to zero. The hot modes heat the payload up a little, and the cold modes take the heat back. This is a thermostat's mean power over the run. After a hot mode, a thermostat stays off until the extra heat has left, and then holds the set point. So its net heat comes back to zero sooner, and then stays flat. Its energy is the same, since the run's balance fixes it. The power budget reads the heater row for the heater's energy, so this is the figure for it.

The model has no thermostat, and keeps one heater power for each mode. So the heater row holds one of the two figures. The sample's row holds the run's: 22.1 W in idle, with 37.6 W to install. The temperature then swings over each orbit. The model has no heat capacity, so the size of the swing is the user's estimate. In the sample, it is under 2 K an orbit, as [How far to trust the figures](#how-far-to-trust-the-figures) shows.

**The radiator's size.** A larger radiator brings the hot modes closer to balance, but the cold modes need more heater power. A smaller one does the reverse. Neither is right by itself. The sample's 0.2 m² lets imaging and downlink heat up a little, for a modest heater in idle. Another systems engineering or safety decision could design the payload colder, with a slightly larger radiator. Imaging and downlink would then come closer to balance, and idle would need more heater power.

**The heater to install.** The coldest mode's balancing power, from Balance each mode, covers the modes of the scenario, which are its nominal operations. It leaves out a safe mode, which may hold another attitude with less equipment on. It also leaves out the redundant heater lines, the lowest bus voltage and any margin. Each of these is a decision of its own.

**The margins.** The account takes the dissipation without margins, which is the safe side for the heaters. For the radiators, it is the optimistic side. So check the radiators against the dissipation with the margins too. The payload should still balance, with the heater lower but above zero.

**The cases.** A folder holds one case. A hot case, with aged coatings, the most dissipation and a high albedo and infrared, sizes the radiators. A cold case, with new coatings, the least dissipation and a low albedo and infrared, sizes the heaters. Each needs a folder of its own. The sample has one case only, as a first pass, with the Earth's global means.

## The files

Both files sit in the power folder, beside the power system file.

**`payload_thermal.yaml`** holds the surfaces, the heat flows and the Earth's two constants:

```yaml
surfaces:
  radiator: {part: Radiator, absorptance: 0.20, emissivity: 0.85, temperature: 273 K}
  aperture:
    part: Aperture
    absorptance: 0.90
    emissivity: 0.90
    temperature: 273 K
    fixed_temperature: true
heat_flows:
  platform interface: -3 W
  x-band rf: {idle: 0 W, imaging: 0 W, downlink: -5 W}
earth: {albedo: 0.30, infrared: 237 W/m2}
```

The file is optional. Without it, the folder sizes power only.

**`payload_consumption.csv`** gets the `thermal` column, with `inside_mli`, `outside_mli` or `heater` in every row. The column is needed only when the folder has the thermal file. The platform's file takes no such column, since the model covers the payload only.

## Where to see it

- **The thermal command,** `python -m quicksat.thermal`, does all that the power command does: it runs the scenario and the power budget, prints the checks and writes the viewer. Then it prints the account's tables by activity and by payload mode, and puts the account in the viewer. Without the thermal file, it says so, and gives the power budget alone.
- **The Scenario Editor's Thermal tab** edits the thermal file, and shows its surfaces in the 3D panel. With the editor's server, its Compute button gives the account. The table by mode edits the heater row. Balance each mode and Balance the run set the heaters to either balancing power. The server keeps the run and the surfaces' heat, so a change to the heaters, the flows or the dissipation is quick to work out again.
- **The viewer's Thermal tab** shows the account as the editor's tab does, without its fields and buttons: the tables by payload mode, by activity and by whole orbit, the net heat since the start over the payload's modes, the surfaces and the notes. The viewer has the tab when the thermal command or the editor's Create the viewer writes it, with the thermal file in the folder. The power command's viewer has no Thermal tab. The Inputs tab shows the thermal file.

## How far to trust the figures

The account adds up exactly what it is given. So its figures are as good as its inputs and its simplifications. The geometry is its strongest part: the sun on each surface comes from the same code as the solar panels, which is checked against Orekit. Its weakest parts are the inputs that a first design can only estimate.

**The inputs that matter most,** roughly from the largest effect down:

- **The radiator's temperature.** The emission follows T⁴. At 273 K, 10 K more or less changes it by about 15 %. The drop to the equipment and the fin efficiency, from [Kinds of radiator](#kinds-of-radiator), both set it.
- **The fin efficiency.** For a patch, it can change the emission two or three times.
- **The absorptance's ageing.** White paint goes from about 0.2 to 0.4 or more, which doubles the sun and the albedo on it. Take the end of life's value for the hot case, and the start of life's for the cold case.
- **The MLI's leak.** The model takes the MLI as a perfect insulator. A real blanket has an effective emittance of about 0.01 to 0.05, more for a small blanket with many seams and cut-outs. With the payload at 273 K, that loses a few watts for each square metre of blanket. In the sample, a few watts would be a large part of idle's 22 W heater. Enter it as a heat flow, such as `-5 W`.
- **The interfaces.** The platform interface is one fixed flow. In reality it follows the difference between the two sides' temperatures, so it changes from case to case. Take the value for each case's own temperatures.
- **The Earth's values.** In the sample, 0.1 of albedo or 25 W/m² of infrared moves idle's heater by about 6 %. Over a short activity, the spread is wider.
- **The dissipation.** The account takes the equipment's powers without their margins. Early estimates of dissipation often grow, so check the radiator with the margins too.

**The equilibrium ΔT is for a long stay.** It is where the payload would settle if an activity went on for days. The payload's heat capacity C is its mass times the specific heat of its materials, such as 900 J/(kg K) for aluminium. A payload of 50 kg, mostly aluminium, has C ≈ 45 kJ/K. Its time constant is C divided by the floating surfaces' extra emission for each kelvin, Σ 4εσAT³. With that C, the sample's time constant is about 16 h. So imaging's equilibrium ΔT of 70 K would take days to reach. One imaging session brings in 8.8 W h, and warms the payload by about 0.7 K: its net energy divided by C.

**The payload is a large heat sink.** With the same C, the sample's payload swings by under 2 K within each orbit. So the account can size the radiator and the heater to the mean over the run, as it does. A small unit on its own radiator swings far more, and the account cannot show it.

**What the figures are good for:**

- The radiator's area, within the uncertainty of its temperature and its fin efficiency. At a first pass, that is tens of percent.
- The radiator's place: which face sees the sun or the Earth, and in which activities.
- The heater power, and the modes that need it.
- The activities and the modes that bring in heat, and how much.

**What they are not for:**

- A unit's temperature, such as the detector's, the cooler's or a box's. The model keeps one account, at the design temperatures.
- A temperature's stability, such as the detector's during imaging.
- A unit on its own radiator, at its own temperature.
- Qualification. A detailed thermal model, with the conduction paths and the nodes, does that later.

**Margins.** A thermal design adds an uncertainty margin to each predicted temperature, and a margin to the heater power. The project's thermal requirements set them. A first pass with this model needs them at least as large as a detailed model would, since it leaves more out.

## Where it stops

- **No heat capacity.** The model gives energies and an equilibrium, not a temperature over time. [How far to trust the figures](#how-far-to-trust-the-figures) says why that is enough for the payload as a whole.
- **No temperature tracking.** Each surface stays at its design temperature through the run.
- **No thermostat.** Each heater line keeps a fixed power for each payload mode.
- **One account for the whole payload.** Two radiators at different temperatures add their emissions to one account. The model cannot say whether a cold focal plane radiator matches the focal plane's own heat.
- **Every surface counts in every mode.** A surface that counts in some modes only, such as an aperture behind a door that opens for imaging, is not modelled.
- **A radiator at one temperature.** The model has no fin efficiency, and no drop to the equipment. [Kinds of radiator](#kinds-of-radiator) shows how to allow for both.
- **A perfect MLI.** Its leak is left out, unless it is entered as a heat flow.
- **A clear view to space.** The model's other parts do not block a surface's view to space, nor send it their infrared.
- **No shading of the Earth.** The model's other parts do not block a surface's view of the Earth. So the model overstates the Earth's heat, which is the safe side for the hot case, but not for the cold case.
- **One albedo and one infrared for the run.** They do not follow the latitude, the ground below or the length of an activity. Each case takes the pair for its own scenario.
- **One case a folder.** A hot case at the end of life and a cold case at the start of life each need a folder of their own, as power's winter and summer cases do.
- **Figures only.** The model gives its figures with no checks at first. Warnings on imbalances may come later.

## Later

**Tracking the temperature until it settles.** This needs four inputs more: the heat capacity C, the coupling between the radiators and the payload, a start temperature, and a run long enough to settle. In the sample, the payload's time constant is about 16 h, as [How far to trust the figures](#how-far-to-trust-the-figures) says. So a run would need days to settle. A first design rarely has these figures.

The reasons behind these choices are in [`decisions.md`](decisions.md), entry 26.
