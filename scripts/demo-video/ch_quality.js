// Quality: templates, inspections, issues and lot holds; evidence, imports and exports.
const path = require('path');
async function quality(t, page) {
  const C = t.co('recall');
  await t.step('Quality workspace', async () => { await t.nav('Quality'); await t.scroll(300); await t.scroll(-300); });
  await t.step('New inspection template for incoming drivers', async () => {
    await t.link('New template');
    await t.type('code', 'DRIVER-INCOMING'); await t.type('revision', '1'); await t.press('Save');
  });
  await t.step('Criterion: output voltage between 11.4 and 12.6 V', async () => {
    await t.type('sequence', '1'); await t.type('label', 'Output voltage (V)'); await t.pick('value_type', 'Number');
    await t.type('rule', '{"min": 11.4, "max": 12.6}'); await t.press('Add criterion');
  });
  await t.step('Criterion: label legible (yes/no)', async () => {
    await t.type('sequence', '2'); await t.type('label', 'Label legible'); await t.pick('value_type', 'True/false');
    await t.type('rule', '{"equals": true}'); await t.press('Add criterion');
  });
  await t.step('Publish the template (criteria are frozen)', async () => { await t.press('Publish and freeze criteria'); });
  await t.step('Inspect the driver lot', async () => {
    await t.go(`${C}/quality/inspections/new`);
    await t.type('reference', 'INSP-DRV-0001'); await t.pick('lot_id', 'DRV-2611-01'); await t.pick('template_id', 'DRIVER-INCOMING');
    await t.press('Save');
  });
  await t.step('Record observations: 13.1 V is out of range', async () => {
    await t.pick('check_id', 'Output voltage'); await t.type('value', '13.1'); await t.type('comment', 'Sample 3 of 5'); await t.press('Save observation');
    await t.pick('check_id', 'Label legible'); await t.type('value', 'true'); await t.press('Save observation');
  });
  await t.step('Complete the inspection (now frozen)', async () => { await t.press('Complete and freeze inspection'); await t.scroll(300); });
  await t.step('Report a quality issue against the lot', async () => {
    await t.go(`${C}/quality/issues/new`);
    await t.type('reference', 'QI-DRV-0001'); await t.pick('lot_id', 'DRV-2611-01'); await t.pick('inspection_id', 'INSP-DRV-0001');
    await t.type('description', 'Driver output voltage above limit (13.1 V) in incoming inspection.'); await t.pick('severity', 'High');
    await t.press('Save');
  });
  await t.step('Edit the open issue', async () => {
    await t.link('QI-DRV-0001');
    await t.link('Edit open issue');
    await t.type('description', 'Driver output voltage above limit (13.1 V); possible overheating in lamps.'); await t.press('Save');
  });
  await t.step('Place the lot on hold', async () => {
    await t.go(`${C}/quality/holds/new`);
    await t.pick('lot_id', 'DRV-2611-01'); await t.pick('nonconformance_id', 'QI-DRV-0001');
    await t.type('reason', 'Out-of-spec driver voltage: stop all use until reviewed.'); await t.press('Save');
  });
  await t.step('Held stock cannot move: a transfer is refused', async () => {
    await t.go(`${C}/operations/transfers/new`);
    await t.type('reference', 'TR-HELD-TEST'); await t.pick('source_warehouse_id', 'Main'); await t.pick('destination_warehouse_id', 'Plant 2');
    await t.press('Save draft');
    await t.open('Add line');
    await t.type('transfers-quantity', '10'); await t.pick('transfers-lot_id', 'DRV-2611-01');
    await t.pick('transfers-source_location_id', 'Stock room'); await t.pick('transfers-destination_location_id', 'Plant 2 shelf A');
    await t.press('Add line', page.locator('main details').last());
    await t.press('Post document', null, { expectError: true });
    const msg = await page.locator('.alert-danger').first().textContent().catch(() => '');
    if (!/hold/i.test(msg || '')) throw new Error('expected a hold refusal, got: ' + msg);
    await t.pause(1500);
  });
  await t.step('Delete the refused draft', async () => {
    await t.go(`${C}/operations/transfers`); await t.link('TR-HELD-TEST'); await t.press('Delete draft');
  });
  await t.step('Quality workspace shows the hold and the issue', async () => { await t.go(`${C}/quality`); await t.scroll(300); });
}
quality.start = 'recall';

async function evidence(t, page) {
  const C = t.co('recall');
  await t.step('Evidence and reports', async () => { await t.nav('Evidence'); });
  await t.step('Upload a photo privately', async () => {
    await page.setInputFiles('main input[name=file]', path.join(__dirname, 'fixtures', 'driver-photo.png'));
    await t.press('Upload privately');
    await t.see('quarantine');
  });
  await t.step('Rename the display filename', async () => {
    await t.type('original_name', 'driver-LD-77-0412-scorch.png'); await t.press('Rename display filename');
    await t.see('driver-LD-77-0412-scorch.png');
  });
  await t.step('Ask the scanner to check it (not configured here: it stays quarantined)', async () => {
    await t.press('Request scanner check'); await t.scroll(200);
  });
  await t.step('Import items from CSV: validate and preview first', async () => {
    await t.go(`${C}/evidence`);
    await t.type('identifier', 'ITEMS-IMPORT-2611-A');
    await page.setInputFiles('main input[name=file] >> nth=1', path.join(__dirname, 'fixtures', 'items.csv'));
    await t.press('Validate and preview');
    await t.see('C10-CABLE'); await t.scroll(250);
  });
  await t.step('Commit all rows', async () => { await t.press('Commit all rows'); });
  await t.step('The imported items are in the catalog', async () => {
    await t.go(`${C}/catalog/items`); await t.see('C10-CABLE'); await t.see('C10-SHADE');
  });
  await t.step('Create a CSV export of stock balances', async () => {
    await t.go(`${C}/evidence`); await t.pick('kind', 'Stock balances'); await t.press('Create CSV export');
  });
  await t.step('Notifications: the export and other events', async () => { await t.go(`${C}/notifications`); await t.scroll(300); });
}
evidence.start = 'recall';

module.exports = { CHAPTERS: [
  ['Quality', 'Inspection templates, inspections, quality issues and lot holds', 'owner', quality],
  ['Evidence, imports and exports', 'Private uploads held in quarantine, CSV import with preview, CSV exports', 'owner', evidence],
] };
