// quicksat scenario editor: the satellites in a satellite target's file.
//
// The page reads the names, the catalogue numbers and the epochs of the element
// sets in a TLE or OMM file, so that it can list a group's satellites and say
// how far an epoch is from the run. quicksat.orbit.tle and quicksat.orbit.omm
// read the same files in Python. tests/editor/js/elements.test.js checks this
// file against their answers, in element_cases.json. Nothing here touches the
// page, so that Node can load it. The CSV form uses parseCsv, from open.js.

/** The kind of a satellite target's file, from its name and its text: `tle`, `omm` or `trajectory`. */
function orbitFileKind(name, text) {
  const start = String(text).trimStart();
  if (/\.(ecsv|oem)$/i.test(name) || start.startsWith("CCSDS_OEM_VERS") || start.startsWith("# %ECSV")) return "trajectory";
  const header = start.split(/\r\n|\r|\n/)[0];
  if (start.startsWith("CCSDS_OMM_VERS") || /^[<[{]/.test(start) || header.includes("MEAN_MOTION")) return "omm";
  return "tle";
}

const ALPHA5 = "ABCDEFGHJKLMNPQRSTUVWXYZ";

/** A TLE's catalogue number, in five digits or in the Alpha-5 form, such as A0001 for 100001. */
function catalogueNumber(text) {
  const value = String(text).trim();
  const letter = ALPHA5.indexOf(value[0]);
  return letter >= 0 ? (letter + 10) * 10000 + Number(value.slice(1)) : Number(value);
}

/** A TLE's epoch, its year and day of the year, as UTC text to the millisecond. */
function tleEpoch(field) {
  const twoDigits = Number(field.slice(0, 2));
  const year = twoDigits < 57 ? 2000 + twoDigits : 1900 + twoDigits;
  const ms = Date.UTC(year, 0, 1) + (Number(field.slice(2)) - 1) * 86400000;
  return new Date(Math.round(ms)).toISOString().slice(0, 23);
}

/** An OMM's epoch as UTC text to the millisecond: a date, or a day of the year, such as 2026-274T00:00:00. */
function ommEpoch(text) {
  let value = String(text).trim().replace(/Z$/i, "");
  const ordinal = value.match(/^(\d{4})-(\d{3})(T.*)?$/);
  if (ordinal) value = new Date(Date.UTC(Number(ordinal[1]), 0, Number(ordinal[2]))).toISOString().slice(0, 10) + (ordinal[3] || "T00:00:00");
  const ms = Date.parse(`${value}Z`);
  return Number.isNaN(ms) ? null : new Date(ms).toISOString().slice(0, 23);
}

/**
 * The element sets of a TLE file: each TLE in two lines, or in three with a name
 * line first. The name drops Space-Track's leading `0 `. Null for text that
 * does not read as TLEs.
 */
function tleSets(text) {
  const lines = String(text).split(/\r\n|\r|\n/).filter((line) => line.trim());
  const pair = (i) => i + 1 < lines.length && lines[i].startsWith("1 ") && lines[i + 1].startsWith("2 ");
  const sets = [];
  for (let i = 0; i < lines.length; i += 2) {
    let name = null;
    if (!pair(i)) {
      if (!pair(i + 1)) return null;
      name = lines[i].trim();
      if (name.startsWith("0 ")) name = name.slice(2).trim();
      i += 1;
    }
    sets.push({ name, number: catalogueNumber(lines[i].slice(2, 7)), epoch: tleEpoch(lines[i].slice(18, 32)) });
  }
  return sets.length ? sets : null;
}

/** One OMM element set's fields, as text by name, in its name, number and epoch. */
function ommSet(fields) {
  const field = (key) => String(fields[key] ?? "").trim();
  return { name: field("OBJECT_NAME") || null, number: Number(field("NORAD_CAT_ID") || 0), epoch: ommEpoch(field("EPOCH")) };
}

/**
 * The element sets of an OMM file, in KVN, XML, JSON or CSV, as quicksat.orbit.omm
 * tells them apart. Null for text that is none of them.
 */
function ommSets(text) {
  const start = String(text).trimStart();
  try {
    if (start.startsWith("CCSDS_OMM_VERS")) {
      const fields = {};
      for (const line of start.split(/\r\n|\r|\n/)) {
        const at = line.indexOf("=");
        if (at > 0 && !line.trim().startsWith("COMMENT")) fields[line.slice(0, at).trim()] = line.slice(at + 1).trim();
      }
      return [ommSet(fields)];
    }
    if (start.startsWith("<")) {
      const tag = (block, key) => (block.match(new RegExp(`<${key}>([^<]*)</${key}>`)) || [])[1];
      const blocks = [...start.matchAll(/<omm\b[^>]*>([\s\S]*?)<\/omm>/g)].map((match) => match[1]);
      return blocks.map((block) => ommSet({ OBJECT_NAME: tag(block, "OBJECT_NAME"), NORAD_CAT_ID: tag(block, "NORAD_CAT_ID"), EPOCH: tag(block, "EPOCH") }));
    }
    if (start.startsWith("[") || start.startsWith("{")) {
      const data = JSON.parse(start);
      return (Array.isArray(data) ? data : [data]).map(ommSet);
    }
    const [header, ...rows] = parseCsv(start).filter((row) => row.some((cell) => cell.trim()));
    if (header && header.includes("MEAN_MOTION")) return rows.map((row) => ommSet(Object.fromEntries(header.map((key, i) => [key.trim(), row[i]]))));
  } catch {
    return null;
  }
  return null;
}

/** The element sets in a satellite target's file, or null for a trajectory or a file that does not read. */
function elementSets(name, text) {
  const kind = orbitFileKind(name, text);
  if (kind === "trajectory") return null;
  return kind === "omm" ? ommSets(text) : tleSets(text);
}

/** An element set's name and catalogue number, as quicksat's messages give them. */
const elementSetLabel = (set) => (set.name ? `${set.name} (${set.number})` : `catalogue number ${set.number}`);

/**
 * The element set a target takes from its file, as the run picks it: the one
 * that `object` names, by name or catalogue number; without `object`, the only
 * one, or else the one named as the target. Gives `{set}`, or `{problem}`.
 */
function pickedElementSet(sets, object, targetName) {
  const wanted = object !== "" ? object : sets.length > 1 ? targetName : "";
  if (wanted === "") return sets.length === 1 ? { set: sets[0] } : { problem: "the file holds no element set" };
  const tidy = (text) => String(text).split(/\s+/).filter(Boolean).join(" ").toLowerCase();
  const key = tidy(wanted);
  const found = sets.filter((set) => (/^\d+$/.test(key) && Number(key) === set.number) || (set.name !== null && tidy(set.name) === key));
  if (found.length === 1) return { set: found[0] };
  if (found.length > 1) return { problem: `the file holds ${found.length} element sets for "${wanted}"` };
  return { problem: `the file holds no element set named or numbered "${wanted}"` };
}
