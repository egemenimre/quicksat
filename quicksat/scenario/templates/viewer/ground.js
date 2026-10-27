// ---------------------------------------------------------------- Ground track

const groundView = (() => {
  const viewport = $("#vp-ground");
  const canvas = viewport.querySelector("canvas");
  const context = canvas.getContext("2d");
  const overlay = document.createElement("canvas");
  const night = document.createElement("canvas");
  night.width = 240;
  night.height = 120;
  const nightContext = night.getContext("2d");
  const nightImage = nightContext.createImageData(night.width, night.height);
  // Unit vector of each night cell, in Earth-fixed axes
  const cells = new Float32Array(night.width * night.height * 3);
  for (let row = 0; row < night.height; row++) {
    const lat = (90 - ((row + 0.5) * 180) / night.height) * D2R;
    for (let col = 0; col < night.width; col++) {
      const lon = (((col + 0.5) * 360) / night.width - 180) * D2R;
      const c = 3 * (row * night.width + col);
      cells[c] = Math.cos(lat) * Math.cos(lon);
      cells[c + 1] = Math.cos(lat) * Math.sin(lon);
      cells[c + 2] = Math.sin(lat);
    }
  }
  const sunFixed = new THREE.Vector3();
  const toFixed = new THREE.Quaternion();
  let ratio = 1;
  let map = { x: 0, y: 0, w: 1, h: 1 };
  let cssSize = null;
  const toPixel = (lon, lat) => [map.x + ((lon + 180) / 360) * map.w, map.y + ((90 - lat) / 180) * map.h];

  function drawOverlay() {
    overlay.width = canvas.width;
    overlay.height = canvas.height;
    const c = overlay.getContext("2d");
    c.scale(ratio, ratio);
    c.lineJoin = "round";
    c.strokeStyle = "rgba(124, 196, 255, 0.16)";
    c.lineWidth = 1;
    c.fillStyle = THEME.dim;
    c.font = `10px ${MONO}`;
    for (let lon = -180; lon <= 180; lon += 30) {
      const [x] = toPixel(lon, 0);
      c.beginPath();
      c.moveTo(x, map.y);
      c.lineTo(x, map.y + map.h);
      c.stroke();
      c.textAlign = "center";
      c.fillText(String(lon), x, map.y + map.h + 12);
    }
    for (let lat = -90; lat <= 90; lat += 30) {
      const [, y] = toPixel(0, lat);
      c.beginPath();
      c.moveTo(map.x, y);
      c.lineTo(map.x + map.w, y);
      c.stroke();
      c.textAlign = "right";
      c.fillText(String(lat), map.x - 5, y + 3);
    }
    c.strokeStyle = "rgba(207, 234, 255, 0.7)";
    for (const line of coastlines) {
      c.beginPath();
      for (let j = 0; j < line.length; j += 2) {
        const [x, y] = toPixel(line[j], line[j + 1]);
        if (j === 0) c.moveTo(x, y);
        else c.lineTo(x, y);
      }
      c.stroke();
    }
    // The track, coloured by the chosen row, and broken where it crosses the
    // date line. Each piece runs from the step before its start to the step
    // after its end, so that the pieces join. In the designer, the occurrences
    // of the selected activity are brighter, and the rest of the track dim.
    const selected = state.selected === null ? [] : occurrencesOf(OCCURRENCES, state.selected);
    c.lineWidth = 2;
    c.globalAlpha = selected.length ? 0.3 : 1;
    for (const piece of TRACKS[state.colourBy]) strokeTrack(c, piece.start_s, piece.end_s, colourOf(piece.value));
    c.globalAlpha = 1;
    c.lineWidth = 3;
    for (const occurrence of selected) {
      for (const piece of TRACKS[state.colourBy]) {
        const from = Math.max(piece.start_s, occurrence.start_s);
        const to = Math.min(piece.end_s, occurrence.end_s);
        if (from < to) strokeTrack(c, from, to, colourOf(piece.value));
      }
    }
  }

  /** The track from one time to another, in one colour. */
  function strokeTrack(c, start, end, colour) {
    const from = sampleAt(start)[0];
    const [i, f] = sampleAt(end);
    const to = f > 0 ? i + 1 : i;
    c.strokeStyle = colour;
    c.beginPath();
    for (let k = from; k <= to; k++) {
      const [x, y] = toPixel(LON[k], LAT[k]);
      if (k === from || Math.abs(LON[k] - LON[k - 1]) > 180) c.moveTo(x, y);
      else c.lineTo(x, y);
    }
    c.stroke();
  }
  trackColours.onChange(() => {
    if (cssSize) drawOverlay();
    dirty.ground = true;
  });

  function drawNight() {
    // The sun in Earth-fixed axes: turn back by the Earth's rotation
    sunFixed.copy(state.sun).applyQuaternion(toFixed.copy(state.qEarth).invert());
    const { x: sx, y: sy, z: sz } = sunFixed;
    const data = nightImage.data;
    for (let j = 0, c = 0; j < data.length; j += 4, c += 3) {
      const cosine = cells[c] * sx + cells[c + 1] * sy + cells[c + 2] * sz;
      data[j] = 2;
      data[j + 1] = 6;
      data[j + 2] = 14;
      data[j + 3] = 170 * clamp((0.05 - cosine) / 0.15, 0, 1);
    }
    nightContext.putImageData(nightImage, 0, 0);
    return [sx, sy, sz];
  }

  // In the designer, a toggle that shows the orbit beside the map, or hides it
  // to give the map its width. The browser remembers the choice, where it can.
  if (DESIGNER) {
    let shown = true;
    try {
      shown = localStorage.getItem("quicksat-designer-orbit") !== "0";
    } catch {
      // No storage, as in some private windows: the orbit shows
    }
    addToggles($("#ground-toggles"), [
      {
        label: "3D Orbit View",
        on: shown,
        help: "orbitShown",
        set: (on) => {
          document.body.classList.toggle("no-orbit", !on);
          markAll();
          try {
            localStorage.setItem("quicksat-designer-orbit", on ? "1" : "0");
          } catch {
            // The choice then lasts until the page is loaded again
          }
        },
      },
    ]);
  }

  // The track of each satellite target over its current pass, which is off at first
  let passesShown = false;
  if (targetState.some((item) => item.lats)) {
    addToggles($("#ground-toggles"), [
      {
        label: "Passes",
        on: false,
        help: "passTracks",
        set: (on) => {
          passesShown = on;
          dirty.ground = true;
        },
      },
    ]);
  }

  /**
   * The targets: a satellite target's point below it as a circle, and a ground
   * target as a square, each filled while in view and hollow otherwise. Each
   * name shows while in view, and a ground target's always. With Passes on,
   * each satellite in view has its track over its current pass, from its rise
   * to its set.
   */
  function drawTargets(c) {
    c.save();
    c.font = `10px ${MONO}`;
    c.lineWidth = 1.5;
    for (const item of targetState) {
      c.strokeStyle = c.fillStyle = targetColour(item.target, item.inView);
      if (passesShown && item.inView && item.lats) {
        const pass = passAt(item.target.passes, state.t, T_END);
        const from = sampleAt(pass.start_s)[0];
        const [last, f] = sampleAt(pass.end_s);
        const to = f > 0 ? last + 1 : last;
        c.beginPath();
        for (let k = from; k <= to; k++) {
          const [x, y] = toPixel(item.lons[k], item.lats[k]);
          if (k === from || Math.abs(item.lons[k] - item.lons[k - 1]) > 180) c.moveTo(x, y);
          else c.lineTo(x, y);
        }
        c.stroke();
      }
      const [x, y] = toPixel(item.lon, item.lat);
      c.beginPath();
      if (item.fixed) c.rect(x - 3.5, y - 3.5, 7, 7);
      else c.arc(x, y, 4, 0, 2 * Math.PI);
      if (item.inView) c.fill();
      else c.stroke();
      if (item.inView || item.fixed) c.fillText(item.target.name, x + 7, y - 6);
    }
    c.restore();
  }

  // In the designer, a click near the track moves the time cursor there, and
  // tells the editor which activity is under way then
  if (DESIGNER) {
    canvas.addEventListener("click", (event) => {
      const box = canvas.getBoundingClientRect();
      const [cx, cy] = [event.clientX - box.left, event.clientY - box.top];
      let nearest = -1;
      let best = 10 * 10; // within 10 px
      for (let k = 0; k < N; k++) {
        const [x, y] = toPixel(LON[k], LAT[k]);
        const distance = (x - cx) ** 2 + (y - cy) ** 2;
        if (distance < best) [nearest, best] = [k, distance];
      }
      if (nearest >= 0) pick(T[nearest]);
    });
  }

  /** The terminator: the great circle at right angles to the sun. */
  function drawTerminator(c, sx, sy, sz) {
    const sun = new THREE.Vector3(sx, sy, sz);
    const u = new THREE.Vector3(...(Math.abs(sz) < 0.9 ? [0, 0, 1] : [1, 0, 0])).cross(sun).normalize();
    const w = sun.clone().cross(u);
    c.save();
    c.beginPath();
    c.rect(map.x, map.y, map.w, map.h);
    c.clip();
    c.strokeStyle = "rgba(255, 224, 138, 0.85)";
    c.lineWidth = 1.5;
    c.setLineDash([6, 4]);
    c.beginPath();
    let previous = null;
    for (let k = 0; k <= 360; k++) {
      const a = k * D2R;
      const x = u.x * Math.cos(a) + w.x * Math.sin(a);
      const y = u.y * Math.cos(a) + w.y * Math.sin(a);
      const z = u.z * Math.cos(a) + w.z * Math.sin(a);
      const lon = Math.atan2(y, x) / D2R;
      const [px, py] = toPixel(lon, Math.asin(clamp(z, -1, 1)) / D2R);
      if (previous === null || Math.abs(lon - previous) > 180) c.moveTo(px, py);
      else c.lineTo(px, py);
      previous = lon;
    }
    c.stroke();
    c.restore();
  }

  return {
    /** Draw the track again, after the selected activity changes. */
    retrack() {
      if (cssSize) drawOverlay();
      dirty.ground = true;
    },
    resize(width, height) {
      cssSize = { width, height };
      ratio = Math.min(window.devicePixelRatio, 2);
      canvas.width = Math.round(width * ratio);
      canvas.height = Math.round(height * ratio);
      const box = { left: 36, right: 12, top: 28, bottom: 18 };
      const w = Math.min(width - box.left - box.right, 2 * (height - box.top - box.bottom));
      map = { x: box.left + (width - box.left - box.right - w) / 2, y: box.top, w, h: w / 2 };
      drawOverlay();
    },
    render() {
      const c = context;
      c.setTransform(1, 0, 0, 1, 0, 0);
      c.clearRect(0, 0, canvas.width, canvas.height);
      c.setTransform(ratio, 0, 0, ratio, 0, 0);
      c.fillStyle = "#0a1f3a";
      c.fillRect(map.x, map.y, map.w, map.h);
      const [sx, sy, sz] = drawNight();
      c.imageSmoothingEnabled = true;
      c.drawImage(night, map.x, map.y, map.w, map.h);
      c.setTransform(1, 0, 0, 1, 0, 0);
      c.drawImage(overlay, 0, 0);
      c.setTransform(ratio, 0, 0, ratio, 0, 0);
      drawTerminator(c, sx, sy, sz);
      const [sunX, sunY] = toPixel(Math.atan2(sy, sx) / D2R, Math.asin(clamp(sz, -1, 1)) / D2R);
      c.fillStyle = VECTOR_COLOURS.sun;
      c.beginPath();
      c.arc(sunX, sunY, 5, 0, 2 * Math.PI);
      c.fill();
      drawTargets(c);
      const [x, y] = toPixel(state.lon, state.lat);
      c.lineWidth = 2;
      c.strokeStyle = "#ffffff";
      c.fillStyle = "#ff4d4d";
      c.beginPath();
      c.arc(x, y, 5.5, 0, 2 * Math.PI);
      c.fill();
      c.stroke();
    },
  };
})();
