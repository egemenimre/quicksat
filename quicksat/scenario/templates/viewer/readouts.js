// ---------------------------------------------------------------- Live values

const readouts = (() => {
  const bodyValues = power ? PANELS.map(() => element("b")) : ["x", "y", "z"].map(() => element("b"));
  $("#body-readout").dataset.help = power ? "panels" : "sunBody";
  $("#body-readout").replaceChildren(
    element("div", { class: "head", text: power ? "Sun on panels" : "Sun in body axes" }),
    ...(power
      ? PANELS.map((panel, k) => element("div", {}, [`${panel.name} `, bodyValues[k]]))
      : ["x", "y", "z"].map((name, k) => element("div", {}, [`${name} `, bodyValues[k]]))),
  );
  const ground = $("#ground-readout");
  const orbit = $("#orbit-readout");
  const slider = $("#slider");
  slider.max = String(N - 1);
  const sunBody = new THREE.Vector3();
  const inverse = new THREE.Quaternion();
  const rows = $("#activity-rows").children; // live, so it sees the rows added later
  let current = null;
  // The time from the start, and the orbits since the start, at the top
  const timeValue = element("span");
  const orbitsValue = element("span");
  $("#now").append(
    element("dt", { text: "Time", "data-help": "time" }),
    element("dd", { "data-help": "time" }, [timeValue]),
    element("dt", { text: "Orbits", "data-help": "orbits" }),
    element("dd", { "data-help": "orbits" }, [orbitsValue]),
  );
  // The title of the activity under way, above the timeline rows' values
  const titleValue = element("span");
  $("#now").append(element("dt", { text: "Activity", "data-help": "title" }), element("dd", { "data-help": "title" }, [titleValue]));
  // The current data: the value of each timeline row at the time cursor, with
  // its colour from the timeline
  const now = [
    ["payload_mode", "Payload"],
    ["platform_mode", "Platform"],
    ["attitude", "Attitude"],
    ["illumination", "Illumination"],
  ].map(([key, label]) => {
    const fill = element("span", { class: "fill" });
    const value = element("span");
    $("#now").append(element("dt", { text: label, "data-help": key }), element("dd", { "data-help": key }, [fill, value]));
    return { key, fill, value };
  });
  // The fraction of the sun seen, under the illumination: a sun-coloured square
  // that fades with it, and the percentage
  const sunFill = element("span", { class: "fill", style: `background:${VECTOR_COLOURS.sun}` });
  const sunValue = element("span");
  $("#now").append(element("dt", { text: "Sunlight", "data-help": "light" }), element("dd", { "data-help": "light" }, [sunFill, sunValue]));
  // The targets in view, by name, under the sunlight
  const inViewValue = element("span");
  if (TARGETS.length) {
    $("#now").append(element("dt", { text: "In view", "data-help": "inView" }), element("dd", { "data-help": "inView" }, [inViewValue]));
  }
  // The Targets page: each target, whether it is in view, its range, and
  // whether the body or a part points at it
  const targetRows = targetState.map((item) => {
    const fill = element("span", { class: "fill", style: `background:${targetColour(item.target)}` });
    const value = element("dd");
    $("#targets-now").append(element("dt", {}, [fill, item.target.name]), value);
    return { item, fill, value };
  });
  const passRows = $("#pass-rows").children; // live, so it sees the rows added later
  // The angle of each articulation, and whether it is parked
  // The Power page's current power: the total generated with each panel under
  // it, the consumed, the net and the battery's charge. Each colour matches
  // the line on the charts.
  const watts = (value) => `${value.toFixed(1)} W`;
  const powerNow = [];
  if (power) {
    const grid = power.grid;
    const line = (label, colour, data, format, sub = false) => {
      const value = element("dd", { class: sub ? "sub" : "" });
      $("#power-now").append(
        element("dt", { class: sub ? "sub" : "" }, [element("span", { class: "fill", style: `background:${colour}` }), label]),
        value,
      );
      powerNow.push([value, data, format]);
    };
    line("Generated", THEME.generated, grid.generated_w, watts);
    grid.panel_w.forEach((data, j) => line(PANELS[j].name, panelColour(j), data, watts, true));
    line("Consumed", THEME.consumed, grid.consumed_w, watts);
    line("Net", THEME.netSwatch, NET_W, (value) => `${value >= 0 ? "+" : ""}${value.toFixed(1)} W`);
    line("Battery", THEME.soc, grid.soc, (value) => `${(100 * value).toFixed(1)} %`);
  }
  // The Attitude page's current attitude, each line in its chart's colour
  const attitudeNow = [];
  const attitudeName = element("dd");
  $("#attitude-now").append(element("dt", { text: "Attitude" }), attitudeName);
  const attitudeLine = (label, colour, data, format) => {
    const value = element("dd");
    $("#attitude-now").append(element("dt", {}, [element("span", { class: "fill", style: `background:${colour}` }), label]), value);
    attitudeNow.push([value, data, format]);
  };
  const degrees = (value) => `${value.toFixed(1)}°`;
  const orDash = (format) => (value) => (value === null ? "—" : format(value));
  // the designer has no Attitude page, and no joint angles
  if (!DESIGNER) {
    attitudeLine("Roll", AXIS_COLOURS[0], ATTITUDE.roll_deg, degrees);
    attitudeLine("Pitch", AXIS_COLOURS[1], ATTITUDE.pitch_deg, degrees);
    attitudeLine("Yaw", AXIS_COLOURS[2], ATTITUDE.yaw_deg, degrees);
    attitudeLine("Rate", THEME.accent, ATTITUDE.rate_deg_s, orDash((value) => `${value.toFixed(3)} deg/s`));
    attitudeLine("Acceleration", THEME.accent, ATTITUDE.acceleration_deg_s2, orDash((value) => `${value.toFixed(4)} deg/s²`));
  }
  const jointValues = (DESIGNER ? [] : ARTICULATIONS).map((joint) => {
    const value = element("span");
    $("#now").append(element("dt", { text: joint.name, "data-help": "articulation" }), element("dd", { "data-help": "articulation" }, [value]));
    return value;
  });

  return function update() {
    const k = state.k;
    if (power) {
      PANELS.forEach((_, j) => setText(bodyValues[j], power.grid.sun_cos[j][k].toFixed(3)));
      setText(charts.values.net, `${NET_W[k] >= 0 ? "+" : ""}${NET_W[k].toFixed(1)} W`);
      setText(charts.values.soc, `${(100 * power.grid.soc[k]).toFixed(1)} %`);
      for (const [value, data, format] of powerNow) setText(value, format(data[k]));
    }
    setText(attitudeName, pieceText(pieceAt(TRACKS.attitude, state.t)));
    for (const [value, data, format] of attitudeNow) setText(value, format(data[k]));
    if (!power && !DESIGNER) {
      sunBody.copy(state.sun).applyQuaternion(inverse.copy(state.qBody).invert());
      ["x", "y", "z"].forEach((name, j) => setText(bodyValues[j], (sunBody[name] >= 0 ? " " : "") + sunBody[name].toFixed(3)));
    }
    const lat = `${Math.abs(state.lat).toFixed(1)}°${state.lat >= 0 ? "N" : "S"}`;
    const lon = `${Math.abs(state.lon).toFixed(1)}°${state.lon >= 0 ? "E" : "W"}`;
    setText(ground, `${lat}  ${lon}  ${(state.r.length() - R_E).toFixed(0)} km`);
    setText(orbit, `beta ${state.beta.toFixed(1)}°`);
    setText($("#clock"), `T+ ${clockText(state.t)}`);
    setText(timeValue, `T+ ${clockText(state.t)}`);
    setText(orbitsValue, (state.t / PERIOD).toFixed(2));
    $("#readout").innerHTML = `${clockText(state.t)} <span class="dim">/ ${clockText(T_END)} · ${utcText(state.t)} UTC</span>`;

    for (const item of now) {
      const piece = pieceAt(TRACKS[item.key], state.t);
      const value = pieceText(piece);
      if (item.value.textContent !== value) {
        item.value.textContent = value;
        item.fill.style.background = colourOf(piece.value);
      }
    }
    const light = state.light;
    setText(sunValue, light >= 1 ? "100 %" : light <= 0 ? "0 %" : `${(100 * light).toFixed(1)} %`);
    sunFill.style.opacity = String(0.15 + 0.85 * light);
    const mode = pieceAt(TRACKS.platform_mode, state.t).value;
    jointValues.forEach((_, j) => {
      const joint = ARTICULATIONS[j];
      const angle = ((state.joints[j] + 540) % 360) - 180;
      const text = `${angle >= 0 ? "+" : ""}${angle.toFixed(1)}°`;
      setText(jointValues[j], joint.park_modes.includes(mode) ? `${text}, parked` : text);
    });
    if (TARGETS.length) {
      const seen = targetState.filter((item) => item.inView).map((item) => item.target.name);
      setText(inViewValue, seen.length ? seen.join(", ") : "none");
      for (const { item, fill, value } of targetRows) {
        const pointed = state.pointed.has(item.target.name) ? " · pointed at" : "";
        setText(value, `${item.inView ? "" : "out of view · "}${Math.round(item.range).toLocaleString("en")} km${pointed}`);
        fill.style.opacity = item.inView ? "1" : "0.25";
      }
      PASSES.forEach((pass, j) => {
        if (passRows[j]) passRows[j].classList.toggle("current", pass.start_s <= state.t && state.t < pass.end_s);
      });
    }
    const occurrence = activityAt(state.t);
    setText(titleValue, occurrence ? occurrence.title || "" : "unplanned");
    setText(
      $("#now-activity"),
      occurrence ? `Activity ${occurrence.number} of repeat ${occurrence.repeat}` : "No activity: the list has ended",
    );
    if (Number(slider.value) !== k) slider.value = String(k);

    // the designer has no Activities page, so no rows
    const index = occurrence ? OCCURRENCES.indexOf(occurrence) : -1;
    if (current !== index) {
      if (current !== null && rows[current]) rows[current].classList.remove("current");
      if (rows[index]) rows[index].classList.add("current");
      current = index;
    }
  };
})();
