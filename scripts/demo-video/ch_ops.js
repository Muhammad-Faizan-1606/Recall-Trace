// Operations: purchase → receive → transfer → produce → sell → ship, all posted to the journal.
async function operations(t, page) {
  const C = t.co('recall');
  const draft = async (kind, fill) => { await t.go(`${C}/operations/${kind}/new`); await fill(); await t.press('Save draft'); };
  const line = async (summary, prefix, fill) => {
    await t.open(summary);
    await fill(prefix);
    await t.press('Add line', page.locator('main details', { has: page.locator('summary', { hasText: summary }) }).last());
  };
  await t.step('Operations overview', async () => { await t.nav('Operations'); await t.scroll(400); await t.scroll(-400); });
  await t.step('Purchase order: draft for 500 LED drivers', async () => {
    await draft('purchase-orders', async () => {
      await t.type('reference', 'PO-DRV-001'); await t.pick('supplier_id', 'Lumen'); await t.pick('delivery_site_id', 'Lamp assembly');
    });
    await line('Add line', 'purchase-orders', async (p) => { await t.type(`${p}-quantity`, '500'); await t.pick(`${p}-variant_id`, 'C10-DRIVER-01'); });
  });
  await t.step('Edit the draft reference', async () => {
    await t.link('Edit'); await t.type('reference', 'PO-DRV-0001'); await t.press('Save');
    await t.see('PO-DRV-0001');
  });
  await t.step('Confirm the purchase order', async () => { await t.press('Confirm order'); });
  await t.step('Goods receipt: receive the supplier lot into stock', async () => {
    await draft('receipts', async () => {
      await t.type('reference', 'GR-DRV-0001'); await t.pick('supplier_id', 'Lumen'); await t.pick('warehouse_id', 'Main warehouse');
    });
    await line('Add line', 'receipts', async (p) => {
      await t.type(`${p}-quantity`, '500'); await t.pick(`${p}-purchase_order_line_id`, 'PO-DRV-0001');
      await t.pick(`${p}-lot_id`, 'DRV-2611-01'); await t.pick(`${p}-location_id`, 'Stock room');
    });
  });
  await t.step('Post the receipt: stock, journal and balance in one step', async () => { await t.press('Post document'); });
  await t.step('Transfer: move 120 drivers to plant 2', async () => {
    await draft('transfers', async () => {
      await t.type('reference', 'TR-DRV-0001'); await t.pick('source_warehouse_id', 'Main'); await t.pick('destination_warehouse_id', 'Plant 2');
    });
    await line('Add line', 'transfers', async (p) => {
      await t.type(`${p}-quantity`, '120'); await t.pick(`${p}-lot_id`, 'DRV-2611-01');
      await t.pick(`${p}-source_location_id`, 'Stock room'); await t.pick(`${p}-destination_location_id`, 'Plant 2 shelf A');
    });
    await t.press('Post document');
  });
  await t.step('Production: 100 drivers go into lamp lot LAMP-2611-B', async () => {
    await draft('production', async () => { await t.type('reference', 'PR-LAMP-0001'); await t.pick('site_id', 'Lamp assembly'); });
    await line('Add input', 'production-inputs', async (p) => {
      await t.type(`${p}-quantity`, '100'); await t.pick(`${p}-lot_id`, 'DRV-2611-01'); await t.pick(`${p}-source_location_id`, 'Stock room');
    });
    await line('Add output', 'production-outputs', async (p) => {
      await t.type(`${p}-quantity`, '100'); await t.pick(`${p}-lot_id`, 'LAMP-2611-B'); await t.pick(`${p}-destination_location_id`, 'Stock room');
    });
  });
  await t.step('Post production: genealogy links the driver lot to the lamp lot', async () => { await t.press('Post document'); });
  await t.step('Sales order: 60 lamps for Northside Home Stores', async () => {
    await draft('sales-orders', async () => {
      await t.type('reference', 'SO-NHS-0001'); await t.pick('customer_id', 'Northside'); await t.pick('address_id', 'Distribution centre');
      await t.type('destination', 'Northside DC, bay 4');
    });
    await line('Add line', 'sales-orders', async (p) => { await t.type(`${p}-quantity`, '60'); await t.pick(`${p}-variant_id`, 'C10-LAMP-01'); });
  });
  await t.step('Confirm the sales order', async () => { await t.press('Confirm order'); });
  await t.step('A draft order can be deleted', async () => {
    await draft('sales-orders', async () => { await t.type('reference', 'SO-DRAFT-DELETE'); await t.pick('customer_id', 'Northside'); await t.type('destination', 'Test only'); });
    await t.press('Delete draft');
  });
  await t.step('Shipment: dispatch 60 lamps from lot LAMP-2611-B', async () => {
    await draft('shipments', async () => {
      await t.type('reference', 'SH-NHS-0001'); await t.pick('sales_order_id', 'SO-NHS-0001'); await t.pick('warehouse_id', 'Main');
      await t.pick('carrier_id', 'FastLane'); await t.type('tracking_reference', 'FL123456');
    });
    await line('Add line', 'shipments', async (p) => {
      await t.type(`${p}-quantity`, '60'); await t.pick(`${p}-sales_order_line_id`, 'SO-NHS-0001');
      await t.pick(`${p}-lot_id`, 'LAMP-2611-B'); await t.pick(`${p}-source_location_id`, 'Stock room');
    });
  });
  await t.step('Post the shipment', async () => { await t.press('Post document'); });
  await t.step('Record carrier events: in transit, then delivered', async () => {
    await t.pick('event_type', 'In Transit'); await t.type('note', 'Collected by FastLane'); await t.press('Record event');
    await t.pick('event_type', 'Delivered'); await t.type('note', 'Signed for at Northside DC'); await t.press('Record event');
    await t.see('Signed for');
  });
  await t.step('Stock journal: every posting, newest first', async () => { await t.go(`${C}/operations/journal`); await t.scroll(300); });
  await t.step('Open a posting to see its lines and balances', async () => { await t.link('~/operations/journal/'); await t.scroll(300); });
}
operations.start = 'recall';

module.exports = { CHAPTERS: [
  ['Operations', 'Purchase, receive, transfer, produce, sell and ship, every posting in the stock journal', 'owner', operations],
] };
