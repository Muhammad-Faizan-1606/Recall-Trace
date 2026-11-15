// Recording kit: captions, a visible cursor, chapter title cards, checked steps and a report.
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const { chromium } = require('playwright');

const BASE = process.env.BASE || 'http://127.0.0.1:8001';
const FAST = !!process.env.FAST;           // debugging: no video, no pauses
const OUT = path.join(__dirname, 'out');
const W = 1440, H = 900;
fs.mkdirSync(OUT, { recursive: true });

const OVERLAY = `
(() => {
  const css = \`
  #__cur{position:fixed;left:0;top:0;width:22px;height:22px;z-index:2147483647;pointer-events:none;transform:translate(-100px,-100px);transition:transform .06s linear}
  #__cur svg{filter:drop-shadow(0 2px 3px rgba(0,0,0,.45))}
  #__ring{position:fixed;width:34px;height:34px;margin:-17px 0 0 -17px;border-radius:50%;border:3px solid #ed5b3f;z-index:2147483646;pointer-events:none;opacity:0}
  #__ring.go{animation:__ring .5s ease-out}
  @keyframes __ring{0%{opacity:.9;transform:scale(.4)}100%{opacity:0;transform:scale(1.6)}}
  #__cap{position:fixed;left:50%;bottom:18px;transform:translateX(-50%);z-index:2147483645;pointer-events:none;max-width:86vw;
    background:rgba(17,38,63,.92);color:#fff;border-radius:999px;padding:10px 22px;font:600 17px/1.3 system-ui,sans-serif;box-shadow:0 10px 30px rgba(0,0,0,.3);display:flex;gap:12px;align-items:center}
  #__cap b{color:#6dd1a8;font-weight:700;white-space:nowrap}
  #__cap:empty{display:none}
  #__title{position:fixed;inset:0;z-index:2147483647;display:none;align-items:center;justify-content:center;flex-direction:column;gap:14px;
    background:radial-gradient(120% 120% at 20% 10%,#1a3352 0%,#0b1626 100%);color:#fff;font-family:system-ui,sans-serif;text-align:center}
  #__title .n{color:#ed5b3f;font:700 22px system-ui;letter-spacing:.12em;text-transform:uppercase}
  #__title .t{font:800 56px/1.1 system-ui;max-width:80vw}
  #__title .s{font:500 22px/1.4 system-ui;color:#c5d3e8;max-width:70vw}\`;
  function mount() {
    if (document.getElementById('__cur')) return;
    const st = document.createElement('style'); st.textContent = css; document.documentElement.appendChild(st);
    // Never show authenticator keys or recovery codes on the recording.
    if (location.pathname.startsWith('/security')) { const b = document.createElement('style'); b.textContent = 'main code, main pre, main kbd { filter: blur(8px) !important; }'; document.documentElement.appendChild(b); }
    const cur = document.createElement('div'); cur.id='__cur';
    cur.innerHTML = '<svg width="22" height="22" viewBox="0 0 24 24"><path d="M3 2l7.5 19 2.6-7.6L21 11z" fill="#fff" stroke="#11263f" stroke-width="1.6" stroke-linejoin="round"/></svg>';
    const ring = document.createElement('div'); ring.id='__ring';
    const cap = document.createElement('div'); cap.id='__cap';
    const title = document.createElement('div'); title.id='__title';
    document.documentElement.append(cur, ring, cap, title);
    const p = JSON.parse(sessionStorage.getItem('__mouse') || 'null');
    if (p) cur.style.transform = 'translate(' + p[0] + 'px,' + p[1] + 'px)';
    window.__setCap(sessionStorage.getItem('__cap') || '');
  }
  window.__setCap = (html) => { sessionStorage.setItem('__cap', html); const c = document.getElementById('__cap'); if (c) c.innerHTML = html; };
  window.__title = (n, t, s, show) => { const el = document.getElementById('__title'); if (!el) return;
    el.innerHTML = '<div class="n">' + n + '</div><div class="t">' + t + '</div><div class="s">' + s + '</div>'; el.style.display = show ? 'flex' : 'none'; };
  document.addEventListener('mousemove', e => { const c = document.getElementById('__cur'); if (c) c.style.transform = 'translate(' + e.clientX + 'px,' + e.clientY + 'px)';
    sessionStorage.setItem('__mouse', JSON.stringify([e.clientX, e.clientY])); }, true);
  document.addEventListener('mousedown', e => { const r = document.getElementById('__ring'); if (!r) return; r.style.left = e.clientX + 'px'; r.style.top = e.clientY + 'px';
    r.classList.remove('go'); void r.offsetWidth; r.classList.add('go'); }, true);
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', mount); else mount();
})();`;

function totp(secret) {
  const alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567';
  let bits = '';
  for (const ch of secret.replace(/[\s=]/g, '').toUpperCase()) bits += alphabet.indexOf(ch).toString(2).padStart(5, '0');
  const key = Buffer.from(bits.match(/.{8}/g).map(b => parseInt(b, 2)));
  const counter = Buffer.alloc(8); counter.writeBigUInt64BE(BigInt(Math.floor(Date.now() / 30000)));
  const h = crypto.createHmac('sha1', key).update(counter).digest();
  const o = h[h.length - 1] & 15;
  return String(((h.readUInt32BE(o) & 0x7fffffff) % 1e6)).padStart(6, '0');
}

class Run {
  constructor() { this.results = []; this.state = {}; this.chapterNo = 0; }
  async start() { this.browser = await chromium.launch({ slowMo: FAST ? 0 : 60 }); }
  async stop() { await this.browser.close(); }

  async chapter(title, subtitle, who, fn) {
    this.chapterNo += 1;
    const n = String(this.chapterNo).padStart(2, '0');
    this.chapterTitle = title;
    const opts = { viewport: { width: W, height: H }, bypassCSP: true, acceptDownloads: true };
    if (!FAST) opts.recordVideo = { dir: path.join(OUT, 'raw'), size: { width: W, height: H } };
    const stateFile = this.state[who + 'State'];
    if (stateFile && fs.existsSync(stateFile)) opts.storageState = stateFile;
    const context = await this.browser.newContext(opts);
    await context.addInitScript(OVERLAY);
    const page = await context.newPage();
    page.setDefaultTimeout(FAST ? 8000 : 20000);
    page.on('dialog', d => d.accept().catch(() => {}));
    this.page = page; this.context = context; this.who = who;
    this.consoleErrors = [];
    page.on('pageerror', e => { if (!/Transition was aborted|view transition/i.test(String(e))) this.consoleErrors.push(String(e)); });
    page.on('response', r => {
      if (r.status() >= 500) this.consoleErrors.push(r.status() + ' ' + r.url());
      if (r.request().isNavigationRequest() && r.request().frame() === page.mainFrame()) this.lastStatus = r.status();
    });
    const started = Date.now();
    try {
      const start = fn.start ? this.state.companies[fn.start] + (fn.startPath || '/overview') : (this.state[who + 'Home'] || '/login');
      await page.goto(BASE + start);
      await page.waitForLoadState('networkidle').catch(() => {});
      await this.titleCard(`Chapter ${this.chapterNo}`, title, subtitle);
      await fn(this, page);
    } catch (e) {
      this.results.push({ chapter: title, step: '(chapter aborted)', ok: false, error: e.message.split('\n')[0] });
      await page.screenshot({ path: path.join(OUT, `fail-${n}.png`) }).catch(() => {});
      console.log(`   ✗ chapter aborted: ${e.message.split('\n')[0]}`);
    }
    await this.pause(1200);
    if (who && this.saveStateAs) { await context.storageState({ path: this.saveStateAs }); this.saveStateAs = null; }
    const video = page.video();
    await context.close();
    if (video) {
      const p = await video.path();
      fs.renameSync(p, path.join(OUT, `chapter-${n}.webm`));
    }
    console.log(`Chapter ${n} ${title}: ${Math.round((Date.now() - started) / 1000)} s`);
  }

  async titleCard(n, t, s) {
    if (FAST) return;
    await this.page.evaluate(([a, b, c]) => window.__title && window.__title(a, b, c, true), [n, t, s]);
    await this.pause(2600);
    await this.page.evaluate(() => window.__title && window.__title('', '', '', false));
  }
  async pause(ms) { if (!FAST) await this.page.waitForTimeout(ms); }

  async step(name, fn) {
    const t0 = Date.now();
    await this.caption(name);
    try {
      await fn();
      this.results.push({ chapter: this.chapterTitle, step: name, ok: true, ms: Date.now() - t0 });
      console.log(`   ✓ ${name}`);
      await this.pause(700);
    } catch (e) {
      const msg = e.message.split('\n')[0];
      this.results.push({ chapter: this.chapterTitle, step: name, ok: false, error: msg });
      console.log(`   ✗ ${name}: ${msg}`);
      const file = path.join(OUT, `fail-${this.chapterNo}-${this.results.length}.png`);
      await this.page.screenshot({ path: file }).catch(() => {});
      if (process.env.DUMP) await this.dump();
    }
  }

  async caption(text) {
    const html = `<b>${this.chapterTitle}</b><span>${text}</span>`;
    await this.page.evaluate(h => window.__setCap && window.__setCap(h), html).catch(() => {});
  }

  // ---------- Navigation and forms ----------
  co(name) { return this.state.companies[name]; }
  async go(p) {
    const r = await this.page.goto(BASE + p);
    await this.page.waitForLoadState('networkidle').catch(() => {});
    if (r && r.status() >= 400) throw new Error(`GET ${p} → ${r.status()}`);
    await this.pause(500);
  }
  async currentCaption() { return this.page.evaluate(() => (document.getElementById('__cap') || {}).textContent || '').catch(() => ''); }
  async nav(text) {   // click a sidebar item like a person would
    const link = this.page.locator('.sidebar .side-link', { hasText: text }).first();
    await link.scrollIntoViewIfNeeded();
    await Promise.all([this.page.waitForLoadState('load'), link.click()]);
    await this.page.waitForLoadState('networkidle').catch(() => {});
    await this.pause(600);
  }
  scope(s) { if (!s) return this.page.locator('main'); if (typeof s !== 'string') return s; return (s === 'body' || s.startsWith('.sidebar') ? this.page.locator(s) : this.page.locator('main').locator(s)).first(); }
  async reveal(el) {
    const closed = await el.evaluate(n => { const d = n.closest('details'); return !!d && !d.open; }).catch(() => false);
    if (closed) { await el.locator('xpath=ancestor::details[1]/summary').click(); await this.pause(350); }
  }
  async type(name, value, scope) {
    const el = this.scope(scope).locator(`[name="${name}"]`).first();
    await this.reveal(el);
    await el.scrollIntoViewIfNeeded();
    await el.click();
    await el.fill('');
    if (FAST || String(value).length > 40) await el.fill(String(value));
    else await el.pressSequentially(String(value), { delay: 18 });
  }
  async pick(name, text, scope) {
    const el = this.scope(scope).locator(`select[name="${name}"]`).first();
    await this.reveal(el);
    await el.scrollIntoViewIfNeeded();
    const value = await el.evaluate((s, t) => {
      const o = [...s.options].find(o => t instanceof RegExp ? false : o.textContent.trim().toLowerCase().includes(String(t).toLowerCase()));
      return o ? o.value : null;
    }, text);
    if (value === null) throw new Error(`no option "${text}" in ${name}`);
    await el.selectOption(value);
  }
  async pickIndex(name, index, scope) {
    const el = this.scope(scope).locator(`select[name="${name}"]`).first();
    await this.reveal(el);
    const value = await el.evaluate((s, i) => s.options[i < 0 ? s.options.length + i : i].value, index);
    await el.selectOption(value);
  }
  async open(summaryText, scope) {
    const sm = this.scope(scope).locator('summary', { hasText: summaryText }).first();
    await sm.scrollIntoViewIfNeeded();
    const isOpen = await sm.evaluate(n => n.parentElement.open);
    if (!isOpen) await sm.click();
    await this.pause(300);
  }
  async check(name, scope) { const el = this.scope(scope).locator(`[name="${name}"]`).first(); await this.reveal(el); await el.scrollIntoViewIfNeeded(); await el.check(); }
  async press(text, scope, { expectError = false } = {}) {
    const btn = this.scope(scope).locator('button, a.btn', { hasText: text }).first();
    await this.reveal(btn);
    await btn.scrollIntoViewIfNeeded();
    await this.pause(250);
    await Promise.all([this.page.waitForLoadState('load').catch(() => {}), btn.click()]);
    await this.page.waitForLoadState('networkidle').catch(() => {});
    if (!expectError) await this.noErrors();
    await this.pause(500);
  }
  async link(text, scope) {
    const a = (typeof text === 'string' && text.startsWith('~'))
      ? this.scope(scope).locator(`a[href*="${text.slice(1)}"]`).first()
      : this.scope(scope).locator('a', { hasText: text }).first();
    await a.scrollIntoViewIfNeeded();
    await Promise.all([this.page.waitForLoadState('load'), a.click()]);
    await this.page.waitForLoadState('networkidle').catch(() => {});
    await this.pause(500);
  }
  async noErrors() {
    const p = this.page;
    if (this.lastStatus >= 400) {
      const body = (await p.locator('main').innerText().catch(() => '')).replace(/\s+/g, ' ').trim();
      const code = this.lastStatus; this.lastStatus = 0;
      throw new Error(`HTTP ${code}: ${body.slice(0, 220)}`);
    }
    const bad = p.locator('.alert-danger[role=status], .invalid-feedback.d-block, .alert-danger:has-text("Please correct")');
    if (await bad.count()) {
      const txt = (await bad.allTextContents()).join(' | ').replace(/\s+/g, ' ').trim();
      throw new Error('page shows error: ' + txt.slice(0, 220));
    }
    const status = await p.evaluate(() => document.title);
    if (/Internal Server Error|Bad Request|Forbidden|Not Found|Unprocessable|Conflict/i.test(status)) throw new Error('page title: ' + status);
    if (this.consoleErrors.length) { const e = this.consoleErrors.join(' | '); this.consoleErrors = []; throw new Error('browser error: ' + e.slice(0, 200)); }
  }
  async see(text, scope) {
    const loc = this.scope(scope || 'body').getByText(text, { exact: false }).first();
    await loc.waitFor({ state: 'visible', timeout: 8000 });
    await loc.scrollIntoViewIfNeeded().catch(() => {});
  }
  async flash(text) { await this.see(text, '.alert-success, .alert-info, .alert-warning, [role=status]'); }
  async scroll(px) { await this.page.mouse.wheel(0, px); await this.pause(500); }
  async hover(sel) { const l = this.page.locator(sel).first(); await l.scrollIntoViewIfNeeded(); await l.hover(); await this.pause(400); }
  async dump() {
    const forms = await this.page.$$eval('main form', fs => fs.map(f => `${f.getAttribute('action') || '(self)'}: ` +
      [...f.elements].filter(e => e.name).map(e => `${e.name}${e.tagName === 'SELECT' ? '{' + [...e.options].slice(0, 5).map(o => o.textContent.trim().slice(0, 25)).join('|') + '}' : ''}`).join(', ') +
      ' [' + [...f.querySelectorAll('button')].map(b => b.textContent.trim().slice(0, 30)).join(' / ') + ']'));
    console.log('     URL', this.page.url()); forms.forEach(f => console.log('     FORM', f.slice(0, 400)));
  }
  totp(secret) { return totp(secret); }
  async freshCode(secret) {
    // Each code works once: wait for a new 30-second window if this one was used.
    const windowNow = () => Math.floor(Date.now() / 30000);
    while (this.lastTotpWindow === windowNow()) await this.page.waitForTimeout(1000);
    this.lastTotpWindow = windowNow();
    return totp(secret);
  }

  report() {
    const passed = this.results.filter(r => r.ok).length;
    const failed = this.results.filter(r => !r.ok);
    console.log(`\n${passed} passed, ${failed.length} failed`);
    failed.forEach(f => console.log(` ✗ [${f.chapter}] ${f.step}: ${f.error}`));
    fs.writeFileSync(path.join(OUT, 'results.json'), JSON.stringify(this.results, null, 1));
    return failed.length;
  }
}

module.exports = { Run, BASE, FAST, OUT, totp };
