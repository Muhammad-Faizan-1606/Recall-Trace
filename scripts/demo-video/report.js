// Markdown test report: every chapter, its timestamp in the video, and every checked step.
const fs = require('fs');
const path = require('path');
const out = path.join(__dirname, 'out');
const results = JSON.parse(fs.readFileSync(path.join(out, 'results.json'), 'utf8'));
const toc = fs.existsSync(path.join(out, 'toc.json')) ? JSON.parse(fs.readFileSync(path.join(out, 'toc.json'), 'utf8')) : [];
const at = Object.fromEntries(toc.map(([t, name]) => [name, t]));
const mmss = s => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}`;
const passed = results.filter(r => r.ok).length;
let md = `# RecallTrace full walkthrough: test report\n\n`;
md += `Recorded ${new Date().toISOString().slice(0, 16).replace('T', ' ')} UTC on a fresh local database seeded with fictional demo data `;
md += `(Harbourline Foods (demo) and Lahore Knit Mills (demo)).\n\n`;
md += `**${passed} of ${results.length} checked steps passed.** A step passes only when the server accepted the action: `;
md += `no error message, no form error, no HTTP error status and no browser error; many steps also check the expected result on the page.\n\n`;
md += `| # | Chapter | Starts at | Steps passed |\n|---|---|---|---|\n`;
const chapters = [...new Set(results.map(r => r.chapter))];
chapters.forEach((c, i) => {
  const rows = results.filter(r => r.chapter === c);
  md += `| ${i + 1} | ${c} | ${at[c] !== undefined ? mmss(at[c]) : ''} | ${rows.filter(r => r.ok).length}/${rows.length} |\n`;
});
chapters.forEach((c, i) => {
  md += `\n## ${i + 1}. ${c}\n\n`;
  for (const r of results.filter(r => r.chapter === c)) md += `- ${r.ok ? '✅' : '❌'} ${r.step}${r.ok ? '' : ` — ${r.error}`}\n`;
});
md += `\n## Notes\n\n`;
md += `- Notices were written to a local development mailbox (mail mode \`local\`); nothing was emailed.\n`;
md += `- The malware scanner is not configured locally, so the uploaded photo stays quarantined; the video shows that.\n`;
md += `- The reviewer's authenticator setup key is blurred in the recording.\n`;
fs.writeFileSync(path.join(out, 'RecallTrace-walkthrough-test-report.md'), md);
console.log(md.split('\n').slice(0, 40).join('\n'));
