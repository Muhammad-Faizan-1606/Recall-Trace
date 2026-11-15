// Core recall chapters: sign in, catalog, master data, operations.
// Passwords come from demo.env.sh, written by reset.sh with fresh random values.
const OWNER = { email: 'owner@video-demo.test', password: process.env.DEMO_OWNER_PASSWORD };

async function signIn(t, page) {
  await t.step('Open the sign-in page', async () => { await t.see('Sign in'); });
  await t.step('Sign in as the company owner', async () => {
    await t.type('email', OWNER.email, 'form');
    await page.locator('input[type=password]').pressSequentially(OWNER.password, { delay: 15 });
    await t.press('Sign in', 'form');
    await t.see('Harbourline Foods (demo)');
  });
  await t.step('Company directory: one account, two companies', async () => {
    const links = await page.$$eval('.directory a', as => as.map(a => [a.textContent, a.getAttribute('href')]));
    t.state.companies = {};
    for (const [text, href] of links) t.state.companies[text.includes('Lahore') ? 'factory' : 'recall'] = href.replace(/\/(overview|home)$/, '');
    await t.hover('.directory a');
  });
  await t.step('Open the Harbourline Foods workspace', async () => {
    await page.locator('.directory a', { hasText: 'Harbourline' }).click();
    await page.waitForLoadState('networkidle');
    await t.see('Overview');
  });
  const C = t.co('recall');
  await t.step('Recall overview: open investigations, holds and tasks', async () => { await t.scroll(500); await t.scroll(-500); });
  await t.step('Search across lots, investigations and items', async () => {
    await page.locator('#global-search').click();
    await page.locator('#global-search').pressSequentially('C10', { delay: 60 });
    await Promise.all([page.waitForLoadState('load'), page.keyboard.press('Enter')]);
    await t.see('C10');
  });
  await t.step('Switch to dark theme and back', async () => {
    await page.click('[data-theme-toggle]'); await t.pause(1400);
    await page.click('[data-theme-toggle]'); await t.pause(800);
  });
  await t.step('Collapse the menu to icons, then expand it', async () => {
    await page.click('[data-sidebar-collapse]'); await t.pause(1400);
    await page.click('[data-sidebar-collapse]'); await t.pause(600);
  });
  await t.step('Notification settings: choose which events show', async () => {
    await t.go(`${C}/notifications`);
    await t.pick('event_type', 'Notice', 'form');
    await t.press('Save preference', 'form');
  });
  await t.step('Account security: two-factor sign-in status', async () => { await t.go('/security'); await t.see('Account security'); });
  await t.step('Your sessions: every device signed in', async () => { await t.go('/account/sessions'); await t.scroll(300); });
  t.saveStateAs = t.state.ownerState;
}

async function catalog(t, page) {
  const C = t.co('recall');
  await t.step('Units of measure', async () => { await t.nav('Catalog'); await t.link('Units'); });
  await t.step('Create a unit: kilogram', async () => {
    await t.link('New record');
    await t.type('code', 'KG'); await t.type('name', 'Kilogram'); await t.type('dimension', 'mass'); await t.type('decimal_places', '3');
    await t.press('Save'); await t.see('Kilogram');
  });
  await t.step('Create a unit to remove later: box', async () => {
    await t.go(`${C}/catalog/units/new`);
    await t.type('code', 'BOX'); await t.type('name', 'Box of 12'); await t.type('dimension', 'count'); await t.type('decimal_places', '0');
    await t.press('Save');
  });
  await t.step('Delete the unused unit', async () => {
    await t.go(`${C}/catalog/units`);
    await t.link('View BOX');
    await t.press('Delete');
    await t.go(`${C}/catalog/units`);
    if (await page.locator('main', { hasText: 'Box of 12' }).count()) throw new Error('BOX still listed');
  });
  await t.step('Create an item: LED driver board', async () => {
    await t.go(`${C}/catalog/items/new`);
    await t.type('code', 'C10-DRIVER'); await t.type('name', 'LED driver board'); await t.pick('kind', 'Component');
    await t.press('Save'); await t.see('LED driver board');
  });
  await t.step('Edit the item name', async () => {
    await t.go(`${C}/catalog/items`); await t.link('View C10-DRIVER');
    await t.link('Edit');
    await t.type('name', 'LED driver board (rev B)');
    await t.press('Save'); await t.see('rev B');
  });
  await t.step('Create a variant (SKU) in its base unit', async () => {
    await t.go(`${C}/catalog/variants/new`);
    await t.type('sku', 'C10-DRIVER-01'); await t.type('revision', 'B');
    await t.type('description', 'Constant-current driver for the desk lamp');
    await t.pick('item_id', 'C10-DRIVER'); await t.pick('base_unit_id', 'EA');
    await t.press('Save'); await t.see('C10-DRIVER-01');
  });
  await t.step('Variants list', async () => { await t.go(`${C}/catalog/variants`); });
}

async function master(t, page) {
  const C = t.co('recall');
  await t.step('Master data overview', async () => { await t.nav('Master data'); await t.scroll(400); await t.scroll(-400); });
  const create = async (resource, fill, expect) => {
    await t.go(`${C}/master/${resource}/new`);
    await fill();
    await t.press('Save');
    if (expect) await t.see(expect);
  };
  await t.step('Add a site', async () => create('sites', async () => {
    await t.type('code', 'C10-SITE-2'); await t.type('name', 'Second assembly plant (fictional)');
    await t.type('address_text', '12 Example Road, Lahore'); await t.type('country_code', 'PK');
  }, 'Second assembly plant'));
  await t.step('Add a warehouse at the new site', async () => create('warehouses', async () => {
    await t.type('code', 'C10-WH-2'); await t.type('name', 'Plant 2 store'); await t.pick('site_id', 'C10-SITE-2');
  }, 'Plant 2 store'));
  await t.step('Add a quarantine location', async () => create('locations', async () => {
    await t.type('code', 'C10-QA'); await t.type('name', 'Quarantine cage'); await t.pick('kind', 'Quarantine'); await t.pick('warehouse_id', 'C10-WH —');
  }, 'Quarantine cage'));
  await t.step('Add a storage location at plant 2', async () => create('locations', async () => {
    await t.type('code', 'P2-A'); await t.type('name', 'Plant 2 shelf A'); await t.pick('kind', 'Storage'); await t.pick('warehouse_id', 'C10-WH-2');
  }, 'Plant 2 shelf A'));
  await t.step('Add a supplier partner', async () => create('partners', async () => {
    await t.type('code', 'C10-DRV-SUP'); await t.type('name', 'Lumen Drivers (fictional)'); await t.pick('status', 'Active');
  }, 'Lumen Drivers'));
  await t.step('Give the partner the supplier role', async () => {
    await t.go(`${C}/master/partner-roles/new`);
    await t.pick('partner_id', 'C10-DRV-SUP'); await t.pick('role_code', 'Supplier');
    await t.press('Save');
  });
  await t.step('Add a partner contact (.test address)', async () => create('contacts', async () => {
    await t.pick('partner_id', 'C10-DRV-SUP'); await t.type('name', 'Sara Malik'); await t.type('email', 'quality@lumen-drivers.test');
    await t.type('purpose', 'Supplier quality');
  }, 'Sara Malik'));
  await t.step('Add a partner address', async () => {
    await t.go(`${C}/master/addresses/new`);
    await t.pick('partner_id', 'C10-DRV-SUP'); await t.type('label', 'Factory');
    await t.type('address_text', '4 Sample Street, Karachi'); await t.type('country_code', 'PK');
    await t.press('Save');
  });
  await t.step('Add a carrier with a tracking link', async () => create('carriers', async () => {
    await t.type('code', 'C10-FAST'); await t.type('name', 'FastLane Couriers (fictional)');
    await t.type('tracking_url_template', 'https://track.fastlane.test/{tracking}');
  }, 'FastLane'));
  await t.step('Add an item category under Electrical parts', async () => create('categories', async () => {
    await t.type('code', 'DRIVERS'); await t.type('name', 'LED drivers'); await t.pick('parent_id', 'ELECTRICAL-PARTS');
  }, 'LED drivers'));
  await t.step('Register a supplier lot', async () => create('lots', async () => {
    await t.type('lot_code', 'DRV-2611-01'); await t.type('supplier_lot_code', 'LD-77-0412');
    await t.pick('variant_id', 'C10-DRIVER-01'); await t.pick('supplier_id', 'C10-DRV-SUP');
    await t.type('manufactured_at', '2026-11-02T08:00'); await t.type('expires_on', '2029-11-01');
  }, 'DRV-2611-01'));
  await t.step('Register a finished lamp lot (made here)', async () => create('lots', async () => {
    await t.type('lot_code', 'LAMP-2611-B'); await t.pick('variant_id', 'C10-LAMP-01'); await t.pick('supplier_id', 'None');
    await t.type('manufactured_at', '2026-11-14T10:00');
  }, 'LAMP-2611-B'));
  await t.step('Edit the carrier name', async () => {
    await t.go(`${C}/master/carriers`); await t.link('FastLane');
    await t.link('Edit'); await t.type('name', 'FastLane Couriers Ltd (fictional)'); await t.press('Save');
    await t.see('FastLane Couriers Ltd');
  });
  await t.step('Delete an unused category', async () => {
    await t.go(`${C}/master/categories`); await t.link('LED drivers');
    await t.press('Delete');
  });
}

catalog.start = 'recall';
master.start = 'recall';
module.exports = { signIn, catalog, master, OWNER };
