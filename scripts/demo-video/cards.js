// Render the intro and closing cards as 1440x900 PNGs.
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');
const results = JSON.parse(fs.readFileSync(path.join(__dirname, 'out', 'results.json'), 'utf8'));
const passed = results.filter(r => r.ok).length, failed = results.length - passed;
const chapters = [...new Set(results.map(r => r.chapter))];
const style = `body{margin:0;width:1440px;height:900px;display:flex;flex-direction:column;justify-content:center;align-items:center;gap:18px;
  background:radial-gradient(120% 120% at 20% 10%,#1a3352 0%,#0b1626 100%);color:#fff;font-family:system-ui,sans-serif;text-align:center}
  .k{color:#ed5b3f;font:700 22px system-ui;letter-spacing:.14em;text-transform:uppercase}.t{font:800 72px/1.05 system-ui}
  .s{font:500 24px/1.45 system-ui;color:#c5d3e8;max-width:1050px}.n{font:800 120px system-ui;color:#6dd1a8;line-height:1}
  .f{position:absolute;bottom:34px;font:500 16px system-ui;color:#8aa0bd}`;
const intro = `<style>${style}</style><div class="k">Full product walkthrough</div><div class="t">RecallTrace</div>
  <div class="s">Batch traceability, controlled recalls and the Factory Suite — every section and every operation,<br>each step checked automatically while it was recorded.</div>
  <div class="s" style="font-size:20px">Fictional companies: Harbourline Foods (demo) and Lahore Knit Mills (demo) · .test addresses · no real messages sent</div>
  <div class="f">${chapters.length} chapters · recorded ${new Date().toISOString().slice(0, 10)}</div>`;
const outro = `<style>${style}</style><div class="k">Walkthrough complete</div><div class="n">${passed} / ${results.length}</div>
  <div class="t" style="font-size:44px">checked steps passed${failed ? ` · ${failed} failed` : ''}</div>
  <div class="s">Every click, form and drag in this video was verified against the server's response.<br>Local demonstration environment: notices were written to a local mailbox, not emailed.</div>`;
(async () => {
  const b = await chromium.launch(); const p = await b.newPage({ viewport: { width: 1440, height: 900 } });
  for (const [name, html] of [['intro', intro], ['outro', outro]]) { await p.setContent(html); await p.screenshot({ path: path.join(__dirname, 'out', name + '.png') }); }
  await b.close();
})();
