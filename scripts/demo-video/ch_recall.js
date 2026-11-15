// Access, an independent approver, the recall investigation, notices and recovery.
const fs = require('fs');
const path = require('path');
const ROOT = path.resolve(__dirname, '..', '..');
const MAILDIR = path.join(ROOT, 'instance', process.env.ACCOUNT_MAIL_DIR || 'video-mail');
const APPROVER = { email: 'reviewer@video-demo.test', password: process.env.DEMO_REVIEWER_PASSWORD, name: 'Imran Qureshi' };

function latestCode() {
  const files = fs.readdirSync(MAILDIR).map(f => path.join(MAILDIR, f)).sort((a, b) => fs.statSync(b).mtimeMs - fs.statSync(a).mtimeMs);
  for (const f of files) {
    let text = fs.readFileSync(f, 'utf8');
    try { const m = JSON.parse(text); text = m.body || ''; } catch (e) { /* plain text */ }
    const m = text.match(/one-time code:\s*([A-Za-z0-9_-]{30,})/);
    if (m) return m[1];
  }
  throw new Error('no invitation code found in ' + MAILDIR);
}

async function access(t, page) {
  const C = t.co('recall');
  await t.step('Company access: members, roles and invitations', async () => { await t.go(`${C}/access`); await t.scroll(300); });
  await t.step('Create a role: Recall reviewer', async () => {
    await t.link('New role');
    await t.type('code', 'recall-reviewer'); await t.type('name', 'Recall reviewer');
    const perms = ['case.approve', 'case.close', 'notice.approve', 'quality.release', 'catalog.read', 'trace.run', 'evidence.read'];
    await page.locator('main select[name=permissions]').selectOption(perms);
    await t.press('Save role');
  });
  await t.step('Invite an independent reviewer', async () => {
    await t.go(`${C}/access/invitations/new`);
    await t.type('email', APPROVER.email); await t.pick('role_id', 'Recall reviewer'); await t.pick('partner_id', 'Internal');
    await t.press('Send invitation');
    t.state.inviteCode = latestCode();
  });
  await t.step('Audit log: every access change is recorded', async () => { await t.go(`${C}/audit`); await t.scroll(300); });
  await t.step('Team screen: add the ready-made job roles', async () => {
    await t.go(`${C}/team`); await t.press('Add job roles');
  });
  await t.step('Preview the app as a quality inspector', async () => {
    await t.go(`${C}/home`);
    await t.press('Quality inspector'); await t.pause(1200); await t.scroll(300);
    await t.press('Back to my own view');
  });
}
access.start = 'recall';

async function approverJoins(t, page) {
  await t.step('The reviewer opens the invitation and pastes the one-time code', async () => {
    await t.go('/invitations/accept');
    await t.type('token', t.state.inviteCode, 'form'); await t.type('display_name', APPROVER.name, 'form');
    await page.locator('main input[name=password]').pressSequentially(APPROVER.password, { delay: 12 });
    await t.press('Accept invitation');
  });
  await t.step('Sign in as the reviewer', async () => {
    if (/login/.test(page.url()) || await page.locator('main input[name=email]').count()) {
      await t.type('email', APPROVER.email, 'form');
      await page.locator('main input[type=password]').pressSequentially(APPROVER.password, { delay: 12 });
      await t.press('Sign in', 'form');
    }
    await t.see('Harbourline');
  });
  await t.step('Turn on two-factor sign-in (authenticator app)', async () => {
    await t.go('/security'); await t.link('~/security/enroll');
    await page.locator('main input[name=password]').pressSequentially(APPROVER.password, { delay: 12 });
    await t.press('Begin enrollment');
    t.state.approverSecret = (await page.locator('main code').first().textContent()).trim();
    await t.pause(1500);
  });
  await t.step('Confirm with a code from the authenticator', async () => {
    await page.locator('main input[name=code]').pressSequentially(await t.freshCode(t.state.approverSecret), { delay: 40 });
    await t.press('Confirm enrollment');
    await t.pause(1500);
    await t.see('recovery');
  });
  await t.step('Sign out', async () => {
    await page.locator('.topbar-user button, form[action="/logout"] button').first().click();
    await page.waitForLoadState('networkidle');
    t.state.approverHome = '/login';
  });
}

async function investigate(t, page) {
  const C = t.co('recall');
  await t.step('Investigations', async () => { await t.nav('Investigations'); });
  await t.step('Open a new investigation', async () => {
    await t.link('New investigation');
    await t.type('reference', 'RC-DRV-2611'); await t.type('title', 'Overheating LED drivers in desk lamps');
    await t.type('reason', 'Incoming inspection found driver output above limit; lamps built from lot DRV-2611-01 may overheat.');
    await t.pick('severity', 'High'); await t.press('Save');
  });
  await t.step('Add the source lot with its quality issue', async () => {
    await t.pick('lot_id', 'DRV-2611-01'); await t.pick('nonconformance_id', 'QI-DRV-0001');
    await t.type('note', 'Inspection INSP-DRV-0001 measured 13.1 V against a 12.6 V limit.'); await t.press('Add source evidence');
  });
  await t.step('Compute the downstream trace from recorded postings', async () => {
    await t.pick('direction', 'Downstream'); await t.press('Compute recorded trace');
  });
  await t.step('Open the trace: lots, shipments and evidence paths', async () => {
    if (!/\/cases\/traces\//.test(page.url())) await t.link('~/cases/traces/');
    await t.pause(2500); await t.scroll(500); await t.pause(800); await t.scroll(500); await t.pause(800);
  });
  await t.step('Back to the investigation', async () => { await t.link('Investigation workspace'); });
  await t.step('Assign a mandatory task', async () => {
    const f = 'form[action$="/tasks"]';
    await t.type('title', 'Confirm lamps from lot LAMP-2611-B at Northside', f);
    await t.type('description', 'Ask Northside DC to count and quarantine the 60 lamps shipped on SH-NHS-0001.', f);
    await t.pick('assignee_id', 'Company owner', f); await t.check('mandatory', f); await t.press('Assign task', f);
  });
  await t.step('Complete the task with evidence', async () => {
    const f = 'form[action*="/complete"]';
    await t.type('note', 'Northside confirmed 60 lamps quarantined in bay 4 (call log 15 Nov).', f);
    await t.press('Complete assigned task', f);
  });
  await t.step('Discuss in the comments', async () => {
    const f = 'form[action$="/comments"]';
    await t.type('body', 'Driver supplier notified; replacement lot expected next week.', f); await t.press('Add comment', f);
  });
  await t.step('Comments are never edited: append a correction', async () => {
    await t.link('Append correction');
    await t.type('body', 'Correction: replacement lot expected in two weeks, not one.'); await t.press('Save');
  });
  await t.step('Edit the investigation title', async () => {
    await t.link('Edit investigation');
    await t.type('title', 'Overheating LED drivers in desk lamps (lot DRV-2611-01)'); await t.press('Save');
  });
  await t.step('Submit for independent approval', async () => {
    await t.press('Submit for independent approval'); await t.see('submitted');
    t.state.caseUrl = new URL(page.url()).pathname;
  });
}
investigate.start = 'recall';

async function signInWithCode(t, page) {
  await t.type('email', APPROVER.email, 'form');
  await page.locator('main input[type=password]').pressSequentially(APPROVER.password, { delay: 12 });
  await t.press('Sign in', 'form');
  if (await page.locator('main input[name=code]').count()) {
    await page.locator('main input[name=code]').pressSequentially(await t.freshCode(t.state.approverSecret), { delay: 40 });
    await t.press('', 'form');
  }
}

async function review(t, page) {
  await t.step('The reviewer signs in: password, then authenticator code', async () => {
    await signInWithCode(t, page);
    await t.see('Harbourline');
  });
  await t.step('Open the submitted investigation', async () => {
    await page.locator('.directory a', { hasText: 'Harbourline' }).click(); await page.waitForLoadState('networkidle');
    await t.go(t.state.caseUrl); await t.scroll(400); await t.scroll(-400);
  });
  await t.step('Approve: a recent authenticator check is required', async () => {
    await t.press('Approve current complete scope');
    await t.see('Approved'); await t.scroll(400);
  });
  await t.step('Independently verify the completed task', async () => {
    const f = 'form[action*="/complete"]';
    const verify = page.locator(`main ${f} [name=verify]`);
    if (await verify.getAttribute('type') === 'checkbox') await t.check('verify', f);
    await t.type('note', 'Checked the Northside call log and quarantine photo.', f);
    await t.press('Independently verify task', f);
  });
  await t.step('Quality: the holds placed by the approval', async () => {
    await t.go(t.state.caseUrl.replace(/\/cases\/.*/, '/quality')); await t.scroll(400);
  });
  await t.step('Review the manual hold placed by the quality team', async () => {
    await t.link('Out-of-spec driver voltage');
    await t.scroll(300);
  });
  await t.step('Release the manual hold (the recall hold stays in force)', async () => {
    const form = page.locator('main form', { has: page.locator('button', { hasText: 'Save review' }) });
    const select = form.locator('select').first();
    await select.selectOption({ label: 'Release hold' });
    await form.locator('textarea, input[type=text]').first().fill('Recall RC-DRV-2611 now holds every affected lot; this manual hold is superseded.');
    await t.press('Save review', form);
    await t.scroll(300);
  });
}

async function notices(t, page) {
  const C = t.co('recall');
  await t.step('Customer notices', async () => { await t.nav('Notices'); });
  await t.step('Prepare a notice for the affected customer', async () => {
    await t.link('Prepare notice');
    await t.pick('case_id', 'RC-DRV-2611'); await t.pick('contact_id', 'Bilal');
    await t.press('Prepare draft');
    t.state.noticeUrl = new URL(page.url()).pathname;
    await t.scroll(300);
  });
  await t.step('Edit the draft wording', async () => {
    await t.link('Edit draft');
    const body = page.locator('main textarea[name=body]');
    await body.click(); await page.keyboard.press('Control+End');
    await page.keyboard.type('\n\nPlease quarantine the lamps and reply to recalls@harbourline.test.', { delay: 8 });
    await t.press('Save draft'); await t.see('recalls@harbourline.test');
  });
  await t.step('Record the verified recovery: 60 lamps returned', async () => {
    await t.go(t.state.caseUrl);
    const f = 'form[action$="/recovery"]';
    await t.pickIndex('shipment_line_id', 0, f); await t.type('amount', '60', f); await t.pick('disposition', 'Physically returned', f);
    await t.type('evidence_reference', 'RMA-NHS-0001', f); await t.type('evidence_note', 'All 60 lamps received back at the main warehouse.', f);
    await t.press('Record verified disposition', f);
    await t.scroll(300);
  });
}
notices.start = 'recall';

async function noticeApproval(t, page) {
  await t.step('The reviewer signs in again', async () => { await signInWithCode(t, page); await page.locator('.directory a', { hasText: 'Harbourline' }).click(); await page.waitForLoadState('networkidle'); });
  await t.step('Independently approve the notice', async () => {
    await t.go(t.state.noticeUrl);
    await t.press('Independently approve'); await t.see('Approved'); await t.scroll(300);
  });
}

async function delivery(t, page) {
  await t.step('Queue the approved notice for delivery', async () => {
    await t.go(t.state.noticeUrl);
    await t.press('Queue approved delivery'); await t.scroll(300);
  });
  await t.step('The background worker delivers it (to the local development mailbox only)', async () => {
    const { execSync } = require('child_process');
    // The demo environment (DATABASE_URL, MAIL_MODE=local) is already exported by run.sh.
    execSync('.venv/bin/flask --app wsgi:app outbox-run', { cwd: ROOT, shell: '/bin/bash', stdio: 'pipe' });
    await page.reload(); await page.waitForLoadState('networkidle'); await t.scroll(400);
    await t.see('local');
  });
  await t.step('Record the customer acknowledgement', async () => {
    const form = page.locator('main form', { has: page.locator('button', { hasText: 'Record acknowledgement' }) });
    await form.locator('select').first().selectOption({ label: 'Email' });
    await form.locator('textarea, input[type=text]').first().fill('Reply from recalls@northside-stores.test, 15 Nov 16:40: lamps quarantined.');
    await t.press('Record acknowledgement', form); await t.scroll(300);
  });
  await t.step('Resolve the quality issue after the hold review', async () => {
    await t.go(t.state.caseUrl.replace(/\/cases\/.*/, '/quality')); await t.link('QI-DRV-0001');
    await t.press('Resolve after hold review');
  });
}
delivery.start = 'recall';

async function closure(t, page) {
  await t.step('The reviewer signs in for the closure review', async () => {
    await signInWithCode(t, page); await page.locator('.directory a', { hasText: 'Harbourline' }).click(); await page.waitForLoadState('networkidle');
  });
  await t.step('Check the closure conditions on the case', async () => { await t.go(t.state.caseUrl); await t.scroll(500); });
  await t.step('Record the reviewed closure', async () => {
    const f = 'form[action$="/close"]';
    await t.type('note', 'Trace complete, task verified, 60 of 60 lamps returned, customer acknowledged.', f);
    await t.press('Record reviewed closure', f);
    await t.see('Closed'); await t.scroll(-300);
  });
  await t.step('Overview: the investigation is closed, history preserved', async () => {
    await t.nav('Recall overview'); await t.scroll(300);
  });
}

module.exports = { CHAPTERS: [
  ['Team, roles and access', 'A reviewer role, an invitation, the audit log, job roles and role preview', 'owner', access],
  ['An independent reviewer joins', 'Accept the invitation, set a password and turn on two-factor sign-in', 'approver', approverJoins],
  ['Recall investigation', 'Source lot, recorded trace, tasks, comments and submission for approval', 'owner', investigate],
  ['Independent approval', 'A different person, with two-factor sign-in, approves the case and releases the hold', 'approver', review],
  ['Customer notice and recovery', 'Notify the customer, record what came back, and prepare closure', 'owner', notices],
  ['Notice approval', 'The reviewer independently approves the exact notice text', 'approver', noticeApproval],
  ['Delivery and acknowledgement', 'Queue the notice, let the worker deliver it, and record the customer acknowledgement', 'owner', delivery],
  ['Closing the investigation', 'The reviewer checks every closure condition and closes the case', 'approver', closure],
], APPROVER };
