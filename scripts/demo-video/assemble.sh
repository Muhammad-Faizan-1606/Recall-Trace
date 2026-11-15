#!/bin/bash
# Join intro + chapters + outro into one MP4 with chapter markers.
set -e
cd "$(dirname "$0")/out"  # run after ./run.sh has recorded the chapters
node ../cards.js
mkdir -p parts && rm -f parts/*.mp4 list.txt
# Sharp screen text at a small size (about 45 MB for the full 17-minute walkthrough).
ENC="-c:v libx264 -preset slow -crf 30 -tune stillimage -pix_fmt yuv420p -r 25 -an"
ffmpeg -loglevel error -y -loop 1 -i intro.png -t 5 -vf "scale=1440:900" $ENC parts/000-intro.mp4
for f in chapter-*.webm; do
  ffmpeg -loglevel error -y -i "$f" -vf "scale=1440:900" $ENC "parts/${f%.webm}.mp4"
done
ffmpeg -loglevel error -y -loop 1 -i outro.png -t 6 -vf "scale=1440:900" $ENC parts/zzz-outro.mp4
# Glob order is the play order: 000-intro, chapter-01 … chapter-28, zzz-outro.
for f in parts/*.mp4; do echo "file '$PWD/$f'" >> list.txt; done
# Chapter markers from each part's duration.
node -e '
const { execSync } = require("child_process"); const fs = require("fs");
const titles = JSON.parse(fs.readFileSync("results.json")).map(r => r.chapter).filter((v, i, a) => a.indexOf(v) === i);
const parts = fs.readFileSync("list.txt", "utf8").trim().split("\n").map(l => l.slice(6, -1));
let t = 0, meta = ";FFMETADATA1\n", toc = []; let c = 0;
for (const p of parts) {
  const d = parseFloat(execSync(`ffprobe -v error -show_entries format=duration -of csv=p=0 "${p}"`).toString());
  const name = p.includes("intro") ? "Introduction" : p.includes("outro") ? "Results" : titles[c++];
  meta += `[CHAPTER]\nTIMEBASE=1/1000\nSTART=${Math.round(t * 1000)}\nEND=${Math.round((t + d) * 1000)}\ntitle=${name}\n`;
  toc.push([t, name]); t += d;
}
fs.writeFileSync("chapters.txt", meta);
fs.writeFileSync("toc.json", JSON.stringify(toc));
'
ffmpeg -loglevel error -y -f concat -safe 0 -i list.txt -i chapters.txt -map_metadata 1 -map_chapters 1 -c copy -movflags +faststart RecallTrace-full-walkthrough.mp4
ls -la RecallTrace-full-walkthrough.mp4
ffprobe -v error -show_entries format=duration -of csv=p=0 RecallTrace-full-walkthrough.mp4
