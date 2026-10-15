#!/usr/bin/env bash
# Rebuild the files the HTML viewer and the editor inline. Needs Node.js, Python and a
# network connection. The outputs are kept in the package, so this runs only to
# update a library. After a version change, update three.LICENSE and
# uPlot.LICENSE too. js-yaml's licence is copied with it.
#
#   three.min.js       three.js, the parts in three_entry.js, as one global
#   uPlot.iife.min.js  uPlot, as published
#   uPlot.min.css      uPlot's stylesheet, as published
#   js-yaml.min.js     js-yaml, as published, for the editors to read YAML
#   ../../../data/coastlines.json
#                      Natural Earth 1:110m coastlines, as [lon, lat, ...] lines.
#                      quicksat's own maps draw the same file.
set -euo pipefail

THREE_VERSION=0.186.1
UPLOT_VERSION=1.6.32
JS_YAML_VERSION=4.1.1
ESBUILD_VERSION=0.28.2
COASTLINES=https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_110m_coastline.geojson

here="$(cd "$(dirname "$0")" && pwd)"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

cd "$work"
npm init -y > /dev/null
npm install --no-audit --no-fund "three@$THREE_VERSION" "uplot@$UPLOT_VERSION" \
  "js-yaml@$JS_YAML_VERSION" "esbuild@$ESBUILD_VERSION" > /dev/null
cp "$here/three_entry.js" .
./node_modules/.bin/esbuild three_entry.js --bundle --minify --format=iife \
  --global-name=THREE --outfile="$here/three.min.js"
cp node_modules/uplot/dist/uPlot.iife.min.js node_modules/uplot/dist/uPlot.min.css "$here/"
cp node_modules/js-yaml/dist/js-yaml.min.js "$here/"
cp node_modules/js-yaml/LICENSE "$here/js-yaml.LICENSE"

curl -sSL "$COASTLINES" -o coastlines.geojson
python3 - "$here/../../../data/coastlines.json" <<'PYTHON'
import json
import sys

lines = []
for feature in json.load(open("coastlines.geojson"))["features"]:
    geometry = feature["geometry"]
    parts = geometry["coordinates"]
    if geometry["type"] == "LineString":
        parts = [parts]
    for part in parts:
        lines.append([round(value, 2) for point in part for value in point])
with open(sys.argv[1], "w") as file:
    json.dump(lines, file, separators=(",", ":"))
PYTHON
echo "Rebuilt the vendor files in $here"
