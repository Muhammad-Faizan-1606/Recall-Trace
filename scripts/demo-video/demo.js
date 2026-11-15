// Full usage demo of RecallTrace: every section, every operation, each step checked.
// Usage: ./run.sh [chapter numbers...]   (FAST=1 for a quick run without video; see README.md)
const path = require('path');
const fs = require('fs');
const { Run, OUT } = require('./kit');
const core = require('./ch_core');

const CHAPTERS = [
  ['Sign in and find your way around', 'Companies, overview, search, theme, menu, notifications and sessions', 'owner', core.signIn],
  ['Catalog', 'Units, items and variants: create, edit and delete', 'owner', core.catalog],
  ['Master data', 'Sites, warehouses, locations, partners, contacts, carriers, categories and lots', 'owner', core.master],
];
for (const extra of ['ch_ops', 'ch_quality', 'ch_recall', 'ch_factory']) {
  if (fs.existsSync(path.join(__dirname, extra + '.js'))) CHAPTERS.push(...require('./' + extra).CHAPTERS);
}

(async () => {
  const run = new Run();
  const stateFile = path.join(OUT, 'state.json');
  if (fs.existsSync(stateFile)) Object.assign(run.state, JSON.parse(fs.readFileSync(stateFile, 'utf8')));
  run.state.ownerState = path.join(OUT, 'owner.json');
  run.state.approverState = path.join(OUT, 'approver.json');
  run.state.ownerHome = run.state.ownerHome || '/';
  const only = process.argv.slice(2).map(Number);
  await run.start();
  for (let i = 0; i < CHAPTERS.length; i += 1) {
    const [title, sub, who, fn] = CHAPTERS[i];
    if (only.length && !only.includes(i + 1)) { run.chapterNo += 1; continue; }
    await run.chapter(title, sub, who, fn);
    fs.writeFileSync(stateFile, JSON.stringify(run.state, null, 1));
  }
  await run.stop();
  process.exit(run.report() ? 1 : 0);
})();
