// Factory Suite chapters (Lahore Knit Mills, fictional): every factory section and operation.
const path = require('path');
const { execSync } = require('child_process');

async function factoryHome(t, page) {
  const F = t.co('factory');
  await t.step('Switch company: Lahore Knit Mills', async () => {
    await t.go('/'); await page.locator('.directory a', { hasText: 'Lahore' }).click(); await page.waitForLoadState('networkidle');
  });
  await t.step('Home: big tiles for each job', async () => { await t.nav('Home'); await t.scroll(300); await t.scroll(-300); });
  await t.step('Preview as a floor supervisor: only their screens', async () => {
    await t.press('Floor supervisor'); await t.pause(1500); await t.hover('.sidebar'); await t.scroll(300);
  });
  await t.step('Preview as a maintenance technician', async () => {
    await t.press('Back to my own view'); await t.press('Maintenance technician'); await t.pause(1500);
  });
  await t.step('Back to my own view', async () => { await t.press('Back to my own view'); });
  await t.step('Team: one person, one job role', async () => { await t.go(`${F}/team`); await t.scroll(400); });
}
factoryHome.start = 'factory'; factoryHome.startPath = '/home';

async function factoryMap(t, page) {
  const F = t.co('factory');
  await t.step('Factory map: the whole mill in 3D, live', async () => { await t.go(`${F}/factory/map`); await t.pause(2500); });
  await t.step('Tap the dyeing building for its details', async () => {
    await page.locator('.iso-building[data-key="dyeing"]').click(); await t.pause(2000);
  });
  await t.step('Tap the sewing building', async () => {
    await page.locator('.iso-building[data-key="sewing"]').click(); await t.pause(2000);
    await page.locator('[data-iso-close]').click().catch(() => {});
  });
  await t.step('Sewing floor: drag a bundle from cutting onto a line', async () => {
    await page.locator('.floor-section').scrollIntoViewIfNeeded(); await t.pause(800);
    const box = page.locator('[data-pile="buffer"] .bundle-box').first();
    const line = page.locator('.floor-line').nth(1);
    const b = await box.boundingBox(); const l = await line.boundingBox();
    await page.mouse.move(b.x + b.width / 2, b.y + b.height / 2); await page.mouse.down();
    await page.mouse.move(b.x + 40, b.y + 30, { steps: 8 });
    await page.mouse.move(l.x + l.width / 2, l.y + l.height / 2, { steps: 25 });
    await page.mouse.up(); await t.pause(1800);
    await t.see('issued to the line', '[data-toast]');
  });
  await t.step('Move work from one line to another (keyboard works too)', async () => {
    const onLine = page.locator('.floor-line').nth(1).locator('.bundle-box').first();
    await onLine.focus(); await page.keyboard.press('Enter'); await t.pause(600);
    await page.locator('.floor-line').nth(2).focus(); await page.keyboard.press('Enter'); await t.pause(1800);
    await t.see('moved to the line', '[data-toast]');
  });
  await t.step('Drag a finished bundle onto Sewn', async () => {
    const box = page.locator('.floor-line').nth(2).locator('.bundle-box').first();
    const dock = page.locator('.floor-dock');
    await box.scrollIntoViewIfNeeded(); await t.pause(500);
    const b = await box.boundingBox(); const d = await dock.boundingBox();
    await page.mouse.move(b.x + b.width / 2, b.y + b.height / 2); await page.mouse.down();
    await page.mouse.move(b.x + 30, b.y - 20, { steps: 8 });
    await page.mouse.move(d.x + d.width / 2, d.y + d.height / 2, { steps: 25 });
    await page.mouse.up(); await t.pause(1800);
    await t.see('marked sewn', '[data-toast]');
  });
  await t.step('Department cards below the scene', async () => { await t.scroll(1600); await t.pause(800); });
}
factoryMap.start = 'factory';

async function dashboardAlerts(t, page) {
  const F = t.co('factory');
  await t.step('Factory dashboard', async () => { await t.nav('Dashboard'); await t.scroll(500); await t.scroll(500); await t.scroll(-1000); });
  await t.step('Alerts: run the checks now', async () => { await t.nav('Alerts'); await t.press('Run checks now'); });
  await t.step('Acknowledge an alert and take ownership', async () => {
    const form = page.locator('main form[action$="/acknowledge"]').first();
    const sel = form.locator('select'); await t.reveal(sel);
    await sel.selectOption({ label: 'Company owner' }); await t.press('', form);
  });
  await t.step('Resolve an alert with what was done', async () => {
    const form = page.locator('main form[action$="/resolve"]').first();
    const note = form.locator('input[name=note]'); await t.reveal(note);
    await note.fill('Line supervisor rebalanced two operators; output back on target.');
    await t.press('Resolve', form);
  });
  await t.step('Resolved alerts keep their history', async () => { await t.link('Resolved'); await t.scroll(300); });
}
dashboardAlerts.start = 'factory';

async function clientsChapter(t, page) {
  const F = t.co('factory');
  await t.step('Clients: who we make for', async () => { await t.nav('Clients'); await t.pause(800); });
  await t.step('Add a new client', async () => {
    await t.link('Add a client');
    await t.type('code', 'CKD'); await t.type('name', 'Coastline Kids (demo)'); await t.type('short_name', 'Coastline');
    await page.locator('main input[name=colour]').fill('#7c3aed');
    await t.press('Add client');
  });
  await t.step('Upload the client logo (re-encoded safely)', async () => {
    await page.setInputFiles('main input[name=logo]', path.join(__dirname, 'fixtures', 'coastline-logo.png'));
    await t.press('Upload logo'); await t.pause(1000);
  });
  await t.step('Change the badge colour', async () => {
    await page.locator('main input[name=colour]').fill('#6d28d9'); await t.press('Save changes');
  });
  await t.step('All clients with their logos', async () => { await t.go(`${F}/factory/clients`); await t.pause(1200); });
}
clientsChapter.start = 'factory';

async function styles(t, page) {
  const F = t.co('factory');
  await t.step('Styles and work content', async () => { await t.nav('Styles & SAM'); });
  await t.step('Add a style for the new client', async () => {
    await t.go(`${F}/factory/styles/new`);
    await t.type('code', 'CK-TEE-210'); await t.type('name', 'Kids graphic tee'); await t.pick('product_type', 'Tee');
    await t.type('season', 'SS27'); await t.pick('buyer_id', 'CKD'); await t.press('Save');
  });
  await t.step('Add the body fabric', async () => {
    await t.link('Add fabric');
    await t.type('component', 'Body'); await t.pick('fabric_type', 'Single jersey'); await t.type('composition', '100% combed cotton');
    await t.type('gsm', '160'); await t.type('width_m', '1.8'); await t.type('courses_per_cm', '16');
    await t.type('consumption_kg', '0.19'); await t.type('relaxation_hours', '24'); await t.press('Save');
  });
  await t.step('Open the operation bulletin', async () => {
    await t.go(`${F}/factory/styles`); await t.link('CK-TEE-210');
    await t.press('Start revision 1');
    t.state.bulletin = new URL(page.url()).pathname;
  });
  await t.step('Add the first operation by hand', async () => {
    await t.link('Add operation');
    await t.type('sequence', '10'); await t.type('name', 'Shoulder join'); await t.pick('machine_class_id', 'SEW-OL');
    await t.type('basic_minutes', '0.32'); await t.press('Save operation');
  });
  await t.step('Import the rest of the operations from CSV', async () => {
    await t.go(t.state.bulletin); await t.link('Import from CSV');
    await page.locator('main textarea[name=rows]').fill([
      '20, Neck rib attach, SEW-OL, 0.45', '30, Neck topstitch, SEW-FL, 0.30', '40, Sleeve attach, SEW-OL, 0.62',
      '50, Side seam, SEW-OL, 0.70', '60, Sleeve hem, SEW-FL, 0.40', '70, Bottom hem, SEW-FL, 0.42',
      '80, Care label attach, SEW-LS, 0.25', '90, Trim and inspect, manual, 0.50'].join('\n'));
    await t.pick('mode', 'Keep them'); await t.press('Check and import');
  });
  await t.step('Target output for 12 operators', async () => {
    await t.go(t.state.bulletin);
    await t.type('operators', '12'); await t.press('Recalculate'); await t.scroll(400);
  });
  await t.step('Publish the bulletin (its SAM is now frozen for orders)', async () => {
    await t.press('Publish revision 1'); await t.scroll(300);
  });
}
styles.start = 'factory';

async function orders(t, page) {
  const F = t.co('factory');
  const exFactory = new Date(Date.now() + 40 * 86400000).toISOString().slice(0, 10);
  await t.step('Production orders: where every order is today', async () => { await t.nav('Production orders'); await t.pause(1500); });
  await t.step('New order for Coastline Kids', async () => {
    await t.link('New production order');
    await t.type('reference', 'PO-28001'); await t.pick('style_id', 'CK-TEE-210'); await t.type('quantity', '6000');
    await t.type('colour', 'Ocean blue'); await page.locator('main input[name=ex_factory_on]').fill(exFactory);
    await t.pick('priority', '3'); await t.type('sewing_lines', '2'); await t.type('prints_per_piece', '1');
    await t.press('Save and plan');
  });
  await t.step('What if: three lines and higher priority?', async () => {
    await t.type('lines', '3'); await t.pick('priority', '2'); await t.press('Preview the plan'); await t.scroll(300);
  });
  await t.step('Apply the change and re-plan everything', async () => { await t.press('Apply this change'); });
  await t.step('Release the order to the floor', async () => { await t.press('Release to the floor'); });
  await t.step('Cancel an order that is no longer needed', async () => {
    await t.go(`${F}/factory/orders/new`);
    await t.type('reference', 'PO-28002'); await t.pick('style_id', 'CK-TEE-210'); await t.type('quantity', '1500');
    await t.type('colour', 'Sunshine yellow'); await page.locator('main input[name=ex_factory_on]').fill(exFactory);
    await t.type('sewing_lines', '1'); await t.type('prints_per_piece', '0'); await t.press('Save and plan');
    await t.press('Cancel order');
  });
  await t.step('Orders list with client badges', async () => { await t.go(`${F}/factory/orders`); await t.scroll(500); });
}
orders.start = 'factory';

async function board(t, page) {
  const F = t.co('factory');
  await t.step('Planning board', async () => { await t.nav('Planning board'); await t.pause(1000); });
  await t.step('Show one client only', async () => {
    await page.locator('[data-plan-lanes]').scrollIntoViewIfNeeded();
    await page.locator('[data-plan-client]', { hasText: 'Northpeak' }).click(); await t.pause(1500);
    await page.locator('[data-plan-client]').first().click(); await t.pause(800);
  });
  await t.step('Find an order by style', async () => {
    await page.locator('[data-plan-search]').pressSequentially('HOOD', { delay: 80 }); await t.pause(1500);
    await page.locator('[data-plan-search]').fill(''); await page.locator('[data-plan-search]').dispatchEvent('input');
  });
  await t.step('Late orders only', async () => {
    await page.locator('[data-plan-late]').check(); await t.pause(1500); await page.locator('[data-plan-late]').uncheck();
  });
  await t.step('Drag a card to a more urgent lane: preview first', async () => {
    const card = page.locator('.plan-lane[data-lane="4"] .plan-card:not(.is-fixed)').first();
    const lane = page.locator('.plan-lane[data-lane="2"]');
    await card.scrollIntoViewIfNeeded();
    const b = await card.boundingBox(); const l = await lane.boundingBox();
    await page.mouse.move(b.x + b.width / 2, b.y + 70); await page.mouse.down();
    await page.mouse.move(b.x + 30, b.y + 90, { steps: 8 });
    await page.mouse.move(l.x + l.width / 2, l.y + 140, { steps: 30 });
    await page.mouse.up(); await t.pause(2500);
    await t.see('Apply and re-plan');
  });
  const apply = async () => {
    await Promise.all([page.waitForEvent('load'), page.locator('[data-drawer-apply]').click()]);
    await page.waitForLoadState('networkidle'); await t.noErrors(); await t.pause(1200);
  };
  await t.step('Apply and re-plan', apply);
  await t.step('One more sewing line on an order (+)', async () => {
    const plus = page.locator('.plan-card:not(.is-fixed) [data-lines-step="1"]').first();
    await plus.scrollIntoViewIfNeeded(); await plus.click(); await t.pause(2500);
    await t.see('Apply and re-plan'); await apply();
  });
  await t.step('Release a planned order from its card', async () => {
    const btn = page.locator('.plan-card-release button').first(); await btn.scrollIntoViewIfNeeded();
    await t.press('Release to floor', page.locator('.plan-card-release').first());
  });
  await t.step('Order timeline and next week', async () => {
    await t.go(`${F}/factory/planning`);
    await page.locator('#gantt-heading').scrollIntoViewIfNeeded(); await t.pause(1500); await t.link('Later week');
  });
  await t.step('Department drill-down: sewing lines day by day', async () => {
    await page.locator('#load-heading').scrollIntoViewIfNeeded(); await t.pause(800); await t.link('Sewing'); await t.scroll(300);
  });
  await t.step('Re-plan every open order', async () => { await t.go(`${F}/factory/planning`); await t.press('Replan all'); });
}
board.start = 'factory';

async function balancing(t, page) {
  const F = t.co('factory');
  await t.step('Line balancing: every line as a skyline', async () => { await t.nav('Line balancing'); await t.pause(1500); });
  await t.step('Open a line: stations, operations and the bottleneck', async () => {
    await page.locator('.sky-card').nth(1).click(); await page.waitForLoadState('networkidle'); await t.pause(1500);
  });
  await t.step('Rearrange the line (a draft, the floor keeps running)', async () => {
    await t.press('Rearrange the line'); await t.scroll(400);
  });
  await t.step('Move an operation to another station and see the new balance', async () => {
    const form = page.locator('main form[action$="/move"]', { has: page.locator('select[name=work]') }).first();
    await t.reveal(form.locator('select[name=work]'));
    await form.locator('select[name=work]').selectOption({ index: 1 });
    await form.locator('select[name=to_station]').selectOption({ index: 3 });
    await t.press('', form); await t.scroll(300);
  });
  await t.step('Lay the line out automatically', async () => {
    const form = page.locator('main form[action$="/rebalance"]');
    await t.reveal(form.locator('[name=operators]'));
    await t.press('Lay out automatically', form); await t.scroll(300);
  });
  await t.step('Publish the new balance to the line', async () => { await t.press('Publish to the line'); });
  await t.step('Back to the line view', async () => { await t.go(`${F}/factory/lines`); await t.pause(1200); });
}
balancing.start = 'factory';

async function capacityMachines(t, page) {
  const F = t.co('factory');
  await t.step('Capacity: how full each department is', async () => { await t.nav('Capacity'); await t.pause(1500); await t.scroll(500); await t.scroll(-500); });
  await t.step('Machines: every machine as a light in its room', async () => { await t.nav('Machines'); await t.pause(1500); await t.scroll(400); });
  await t.step('Register a new machine', async () => {
    await t.go(`${F}/factory/machines/new`);
    await t.type('asset_tag', 'PARK-L01-S29'); await t.type('make_model', 'Juki MO-6814S overlock');
    await t.pick('machine_class_id', 'SEW-OL'); await t.pick('work_center_id', 'PARK-L01'); await t.type('rated_value', '1');
    await page.locator('main input[name=commissioned_on]').fill('2026-11-15'); await t.press('Save');
  });
  await t.step('Set the new machine to idle until it is threaded', async () => {
    await t.pick('to_status', 'Idle'); await t.type('reason', 'Waiting for thread stand'); await t.press('Update status');
  });
  await t.step('Edit the machine: its own efficiency', async () => {
    await t.link('Edit'); await t.type('efficiency', '85'); await t.press('Save');
  });
  await t.step('Work centres', async () => { await t.nav('Work centres'); await t.scroll(400); });
}
capacityMachines.start = 'factory';

async function shopFloor(t, page) {
  const F = t.co('factory');
  await t.step('Shop floor: the sewing floor, live', async () => { await t.nav('Shop floor'); await t.pause(2000); });
  await t.step('Issue a bundle from the cutting buffer by dragging', async () => {
    const box = page.locator('[data-pile="buffer"] .bundle-box').first();
    const line = page.locator('.floor-line').first();
    await box.scrollIntoViewIfNeeded();
    const b = await box.boundingBox(); const l = await line.boundingBox();
    await page.mouse.move(b.x + b.width / 2, b.y + b.height / 2); await page.mouse.down();
    await page.mouse.move(b.x + 40, b.y + 20, { steps: 8 });
    await page.mouse.move(l.x + l.width * 0.6, l.y + l.height / 2, { steps: 25 });
    await page.mouse.up(); await t.pause(1800); await t.see('issued to the line', '[data-toast]');
  });
  await t.step('Hour-by-hour output for every line', async () => {
    await page.locator('#main .page-head').scrollIntoViewIfNeeded().catch(() => {}); await t.scroll(1400); await t.pause(800);
  });
  await t.step('Open a line to record its hours', async () => { await t.link('~/factory/floor/'); await t.pause(800); });
  await t.step('Record an hour of output', async () => {
    const f = 'form[action$="/output"]';
    await t.pickIndex('hour', 0, f); await t.pickIndex('production_order_id', 0, f);
    await t.type('good_pieces', '58', f); await t.type('rejects', '2', f); await t.type('operators', '26', f); await t.type('minutes', '60', f);
    await t.type('note', 'New operator on station 7', f); await t.press('Save hour', f);
  });
  await t.step('Record a stop: needle change on one machine', async () => {
    const f = 'form[action$="/downtime"]';
    await t.pick('reason_id', 'Needle', f); await t.pickIndex('machine_id', 3, f);
    await t.type('hour', '1', f); await t.type('minutes', '6', f); await t.type('operators_affected', '1', f); await t.press('Save stop', f);
  });
  await t.step('Record an end-line quality check with defects', async () => {
    const f = 'form[action$="/quality"]';
    await t.pick('stage', 'End-line', f); await t.type('hour', '1', f); await t.type('pieces_checked', '40', f); await t.type('defective_pieces', '2', f);
    await t.pickIndex('defect_code_1', 1, f); await t.pickIndex('operation_1', 2, f); await t.type('defect_count_1', '2', f);
    await t.press('Save check', f);
  });
  await t.step('Correct an hour (the original stays in history)', async () => {
    await t.link('Correct');
    await t.type('good_pieces', '60'); await t.type('note', 'Recount at hour end: 60 good'); await t.press('Save correction');
    await t.scroll(400);
  });
}
shopFloor.start = 'factory';

async function batchCards(t, page) {
  const F = t.co('factory');
  const today = new Date().toISOString().slice(0, 10);
  await t.step('Batch cards: knit rolls', async () => { await t.nav('Batch cards'); await t.link('Knit rolls'); });
  for (const [n, kg] of [['R-28001-01', '24.6'], ['R-28001-02', '25.1']]) {
    await t.step(`Record knit roll ${n} from its yarn lot`, async () => {
      await t.type('roll_number', n); await t.pickIndex('machine_id', 0); await t.type('kg', kg); await t.pick('grade', 'A');
      await page.locator('main input[name=knitted_on]').fill(today); await t.pick('yarn_lot_id', 'YRN-2611-A'); await t.pick('production_order_id', 'PO-28001');
      await t.press('Save roll');
    });
  }
  await t.step('Dye house: load a batch with the two rolls', async () => {
    await t.link('Dye batches');
    await t.type('batch_number', 'DB-28001-1'); await t.pickIndex('machine_id', 0); await t.type('colour', 'Ocean blue');
    await t.type('recipe_reference', 'RX-OB-12'); await t.pick('production_order_id', 'PO-28001');
    const rolls = page.locator('main input[name=roll_ids]');
    for (let i = 0; i < await rolls.count(); i += 1) {
      const label = await rolls.nth(i).evaluate(n => (n.closest('label') || n.parentElement).textContent);
      if (/R-28001/.test(label)) await rolls.nth(i).check();
    }
    await t.press('Load batch');
  });
  await t.step('Start dyeing', async () => { await t.press('Start dyeing'); await t.scroll(200); });
  await t.step('Shade passed: the fabric lot is posted for traceability', async () => { await t.press('Shade passed'); await t.scroll(300); });
  await t.step('The dye house picture shows each vessel', async () => { await t.go(`${F}/factory/dye-batches`); await t.pause(2000); });
  await t.step('Cut a lay into numbered bundles', async () => {
    await t.link('Cut bundles');
    await t.pick('production_order_id', 'PO-28001'); await t.pick('dye_batch_id', 'DB-28001-1');
    await t.type('lay_number', 'L-28001-01'); await t.type('bundle_size', '30'); await t.type('sizes', 'S:60, M:90, L:60');
    await t.press('Cut bundles');
  });
  await t.step('Print the bundle tickets with QR codes', async () => {
    await t.link('Print tickets'); await t.pause(1500); await t.scroll(500);
  });
  await t.step('Scan a ticket: the bundle opens', async () => {
    await t.go(`${F}/factory/bundles`);
    await page.locator('main input[name=number]').pressSequentially('PO-28001-0001', { delay: 50 });
    await t.press('Open');
  });
  await t.step('Issue the bundle to a sewing line', async () => {
    await t.pickIndex('line_id', 0); await t.press('Issue bundle');
  });
  await t.step('The line finishes it: mark sewn', async () => { await t.press('Mark sewn'); await t.scroll(200); });
  await t.step('Bundles moving through the floor', async () => { await t.go(`${F}/factory/bundles`); await t.pause(1500); });
}
batchCards.start = 'factory';

async function maintenance(t, page) {
  const F = t.co('factory');
  await t.step('Maintenance: machines and their repairs', async () => { await t.nav('Maintenance'); await t.pause(1500); });
  await t.step('Report a breakdown by asset tag', async () => {
    const f = 'form[action$="/breakdowns"]';
    await t.type('asset_tag', 'PARK-L02-S05', f); await t.type('description', 'Overlock skipping stitches; looper timing suspected.', f);
    await t.press('Report breakdown', f);
  });
  await t.step('Start the repair', async () => { await t.press('Start work'); });
  await t.step('Close the ticket: the machine is back in planned capacity', async () => {
    await t.type('work_done', 'Reset looper timing and replaced the needle plate.'); await t.type('parts_used', 'Needle plate NP-6814');
    await t.press('Close and return to service');
  });
  await t.step('Machine history', async () => { await t.link('Machine history'); await t.scroll(400); });
  await t.step('Open a preventive job that is due', async () => {
    await t.go(`${F}/factory/maintenance`);
    const form = page.locator('main form[action$="/maintenance/jobs"]').first();
    await form.scrollIntoViewIfNeeded(); await t.press('Open job', form);
  });
  await t.step('Do the preventive job and close it', async () => {
    await t.press('Start work');
    await t.type('work_done', 'Cleaned, oiled and checked belt tension.'); await t.press('Close and return to service');
  });
}
maintenance.start = 'factory';

async function setup(t, page) {
  const F = t.co('factory');
  const holiday = new Date(Date.now() + 20 * 86400000).toISOString().slice(0, 10);
  const create = async (resource, fill) => { await t.go(`${F}/factory/${resource}/new`); await fill(); await t.press('Save'); };
  await t.step('Factory setup: everything capacity is calculated from', async () => { await t.nav('Factory setup'); await t.scroll(400); await t.scroll(-400); });
  await t.step('A new shift pattern: two 8-hour shifts, Monday to Saturday', async () => create('shift-patterns', async () => {
    await t.type('code', 'DAY-2X8'); await t.type('name', 'Two 8-hour shifts, six days'); await t.type('shifts_per_day', '2');
    await t.type('hours_per_shift', '8'); await t.type('break_minutes_per_shift', '30');
    const days = page.locator('main input[name=working_days]');
    for (let i = 0; i < await days.count(); i += 1) { if (i < 6) await days.nth(i).check(); else await days.nth(i).uncheck(); }
  }));
  await t.step('A public holiday at one site', async () => create('calendar', async () => {
    await t.pick('site_id', 'PARK'); await page.locator('main input[name=day]').fill(holiday); await t.pick('kind', 'Holiday');
    await t.type('hours_per_shift', '0'); await t.type('note', 'Public holiday (demo)');
  }));
  await t.step('A transit time between two sites', async () => create('transit', async () => {
    await t.pick('from_site_id', 'SUN'); await t.pick('to_site_id', 'RWD'); await t.type('hours', '3'); await t.type('note', 'Bypass road');
  }));
  await t.step('A downtime reason that does not count against the line', async () => create('downtime-reasons', async () => {
    await t.type('code', 'FIRE-DRILL'); await t.type('name', 'Fire drill'); await t.pickIndex('category', -1); await t.pick('efficiency_rule', 'Off standard');
  }));
  await t.step('A preventive maintenance plan for overlock machines', async () => create('maintenance-plans', async () => {
    await t.type('code', 'OL-MONTHLY'); await t.type('name', 'Overlock monthly service'); await t.pick('machine_class_id', 'SEW-OL');
    await t.type('interval_days', '30'); await t.type('duration_minutes', '25'); await t.type('tasks', 'Clean, oil, check looper timing and belt');
  }));
  await t.step('A new work centre using the new shift pattern', async () => create('work-centers', async () => {
    await t.type('code', 'SUN-L07'); await t.type('name', 'Sewing line 7'); await t.pick('department', 'Sewing');
    await t.pick('site_id', 'SUN'); await t.pick('shift_pattern_id', 'DAY-2X8'); await t.type('target_efficiency', '70');
  }));
}
setup.start = 'factory';

async function traceChain(t, page) {
  const F = t.co('factory');
  await t.step('An order from yarn to carton', async () => {
    await t.go(`${F}/factory/orders`); await t.link('PO-27006'); await t.scroll(500);
  });
  await t.step('Traceability: yarn lot → rolls → dye batch → bundles → cartons → shipment', async () => {
    await t.link('Traceability: yarn to carton'); await t.pause(1500); await t.scroll(500); await t.scroll(500);
  });
  await t.step('Post the packed garments as a garment lot', async () => { await t.press('Post packed garments'); await t.scroll(400); });
  await t.step('A yarn complaint: open the draft investigation', async () => {
    await t.nav('Investigations'); await t.link('RC-YARN-2611-A');
  });
  await t.step('Trace the yarn lot downstream to the shipped garments', async () => {
    await t.pick('direction', 'Downstream'); await t.press('Compute recorded trace');
    await t.pause(2500); await t.scroll(500); await t.pause(1000); await t.scroll(500); await t.pause(1000);
  });
  await t.step('Sign out', async () => {
    await t.go(`${F}/home`);
    await page.locator('.profile-card form button, form[action="/logout"] button').first().click();
    await page.waitForLoadState('networkidle'); await t.see('Sign in');
  });
}
traceChain.start = 'factory';

module.exports = { CHAPTERS: [
  ['Factory: home and job roles', 'Simple home tiles per job, and previewing what each job sees', 'owner', factoryHome],
  ['Factory map', 'The live 3D mill, building details, and dragging bundles between lines', 'owner', factoryMap],
  ['Dashboard and alerts', 'Today at a glance; checks, acknowledgement and resolution', 'owner', dashboardAlerts],
  ['Clients', 'Add a client with logo and colour, used on every factory screen', 'owner', clientsChapter],
  ['Styles and work content', 'A style, its fabric, and the operation bulletin that sets its SAM', 'owner', styles],
  ['Production orders', 'Plan an order, preview a change, release it, and cancel another', 'owner', orders],
  ['Planning board', 'Filter, drag orders between priority lanes, add lines, release and re-plan', 'owner', board],
  ['Line balancing', 'Every line at a glance, then rearrange one by dragging operations', 'owner', balancing],
  ['Capacity and machines', 'Department tanks, the machine register, and machine status', 'owner', capacityMachines],
  ['Shop floor', 'Issue bundles, record hourly output, stops and quality checks, and correct an hour', 'owner', shopFloor],
  ['Batch cards', 'Knit rolls, dye batches, cutting into bundles, tickets and scanning', 'owner', batchCards],
  ['Maintenance', 'Report a breakdown, repair it, and run a preventive job', 'owner', maintenance],
  ['Factory setup', 'Shifts, holidays, transit times, downtime reasons, maintenance plans and work centres', 'owner', setup],
  ['From yarn to carton', 'Every factory step posts real lots, so the recall trace follows a garment back to its yarn', 'owner', traceChain],
] };
