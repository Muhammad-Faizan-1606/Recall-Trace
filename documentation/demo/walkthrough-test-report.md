# RecallTrace full walkthrough: test report

Recorded 2026-11-15 20:15 UTC on a fresh local database seeded with fictional demo data (Harbourline Foods (demo) and Lahore Knit Mills (demo)).

**221 of 221 checked steps passed.** A step passes only when the server accepted the action: no error message, no form error, no HTTP error status and no browser error; many steps also check the expected result on the page.

| # | Chapter | Starts at | Steps passed |
|---|---|---|---|
| 1 | Sign in and find your way around | 0:05 | 11/11 |
| 2 | Catalog | 0:34 | 8/8 |
| 3 | Master data | 1:16 | 15/15 |
| 4 | Operations | 2:37 | 17/17 |
| 5 | Quality | 4:07 | 14/14 |
| 6 | Evidence, imports and exports | 5:14 | 9/9 |
| 7 | Team, roles and access | 5:44 | 6/6 |
| 8 | An independent reviewer joins | 6:13 | 5/5 |
| 9 | Recall investigation | 6:38 | 12/12 |
| 10 | Independent approval | 7:26 | 7/7 |
| 11 | Customer notice and recovery | 7:54 | 4/4 |
| 12 | Notice approval | 8:15 | 2/2 |
| 13 | Delivery and acknowledgement | 8:30 | 4/4 |
| 14 | Closing the investigation | 8:49 | 4/4 |
| 15 | Factory: home and job roles | 9:10 | 6/6 |
| 16 | Factory map | 9:35 | 7/7 |
| 17 | Dashboard and alerts | 10:06 | 5/5 |
| 18 | Clients | 10:26 | 5/5 |
| 19 | Styles and work content | 10:49 | 8/8 |
| 20 | Production orders | 11:30 | 7/7 |
| 21 | Planning board | 12:04 | 11/11 |
| 22 | Line balancing | 12:48 | 7/7 |
| 23 | Capacity and machines | 13:16 | 6/6 |
| 24 | Shop floor | 13:46 | 8/8 |
| 25 | Batch cards | 14:23 | 13/13 |
| 26 | Maintenance | 15:19 | 7/7 |
| 27 | Factory setup | 15:50 | 7/7 |
| 28 | From yarn to carton | 16:29 | 6/6 |

## 1. Sign in and find your way around

- ✅ Open the sign-in page
- ✅ Sign in as the company owner
- ✅ Company directory: one account, two companies
- ✅ Open the Harbourline Foods workspace
- ✅ Recall overview: open investigations, holds and tasks
- ✅ Search across lots, investigations and items
- ✅ Switch to dark theme and back
- ✅ Collapse the menu to icons, then expand it
- ✅ Notification settings: choose which events show
- ✅ Account security: two-factor sign-in status
- ✅ Your sessions: every device signed in

## 2. Catalog

- ✅ Units of measure
- ✅ Create a unit: kilogram
- ✅ Create a unit to remove later: box
- ✅ Delete the unused unit
- ✅ Create an item: LED driver board
- ✅ Edit the item name
- ✅ Create a variant (SKU) in its base unit
- ✅ Variants list

## 3. Master data

- ✅ Master data overview
- ✅ Add a site
- ✅ Add a warehouse at the new site
- ✅ Add a quarantine location
- ✅ Add a storage location at plant 2
- ✅ Add a supplier partner
- ✅ Give the partner the supplier role
- ✅ Add a partner contact (.test address)
- ✅ Add a partner address
- ✅ Add a carrier with a tracking link
- ✅ Add an item category under Electrical parts
- ✅ Register a supplier lot
- ✅ Register a finished lamp lot (made here)
- ✅ Edit the carrier name
- ✅ Delete an unused category

## 4. Operations

- ✅ Operations overview
- ✅ Purchase order: draft for 500 LED drivers
- ✅ Edit the draft reference
- ✅ Confirm the purchase order
- ✅ Goods receipt: receive the supplier lot into stock
- ✅ Post the receipt: stock, journal and balance in one step
- ✅ Transfer: move 120 drivers to plant 2
- ✅ Production: 100 drivers go into lamp lot LAMP-2611-B
- ✅ Post production: genealogy links the driver lot to the lamp lot
- ✅ Sales order: 60 lamps for Northside Home Stores
- ✅ Confirm the sales order
- ✅ A draft order can be deleted
- ✅ Shipment: dispatch 60 lamps from lot LAMP-2611-B
- ✅ Post the shipment
- ✅ Record carrier events: in transit, then delivered
- ✅ Stock journal: every posting, newest first
- ✅ Open a posting to see its lines and balances

## 5. Quality

- ✅ Quality workspace
- ✅ New inspection template for incoming drivers
- ✅ Criterion: output voltage between 11.4 and 12.6 V
- ✅ Criterion: label legible (yes/no)
- ✅ Publish the template (criteria are frozen)
- ✅ Inspect the driver lot
- ✅ Record observations: 13.1 V is out of range
- ✅ Complete the inspection (now frozen)
- ✅ Report a quality issue against the lot
- ✅ Edit the open issue
- ✅ Place the lot on hold
- ✅ Held stock cannot move: a transfer is refused
- ✅ Delete the refused draft
- ✅ Quality workspace shows the hold and the issue

## 6. Evidence, imports and exports

- ✅ Evidence and reports
- ✅ Upload a photo privately
- ✅ Rename the display filename
- ✅ Ask the scanner to check it (not configured here: it stays quarantined)
- ✅ Import items from CSV: validate and preview first
- ✅ Commit all rows
- ✅ The imported items are in the catalog
- ✅ Create a CSV export of stock balances
- ✅ Notifications: the export and other events

## 7. Team, roles and access

- ✅ Company access: members, roles and invitations
- ✅ Create a role: Recall reviewer
- ✅ Invite an independent reviewer
- ✅ Audit log: every access change is recorded
- ✅ Team screen: add the ready-made job roles
- ✅ Preview the app as a quality inspector

## 8. An independent reviewer joins

- ✅ The reviewer opens the invitation and pastes the one-time code
- ✅ Sign in as the reviewer
- ✅ Turn on two-factor sign-in (authenticator app)
- ✅ Confirm with a code from the authenticator
- ✅ Sign out

## 9. Recall investigation

- ✅ Investigations
- ✅ Open a new investigation
- ✅ Add the source lot with its quality issue
- ✅ Compute the downstream trace from recorded postings
- ✅ Open the trace: lots, shipments and evidence paths
- ✅ Back to the investigation
- ✅ Assign a mandatory task
- ✅ Complete the task with evidence
- ✅ Discuss in the comments
- ✅ Comments are never edited: append a correction
- ✅ Edit the investigation title
- ✅ Submit for independent approval

## 10. Independent approval

- ✅ The reviewer signs in: password, then authenticator code
- ✅ Open the submitted investigation
- ✅ Approve: a recent authenticator check is required
- ✅ Independently verify the completed task
- ✅ Quality: the holds placed by the approval
- ✅ Review the manual hold placed by the quality team
- ✅ Release the manual hold (the recall hold stays in force)

## 11. Customer notice and recovery

- ✅ Customer notices
- ✅ Prepare a notice for the affected customer
- ✅ Edit the draft wording
- ✅ Record the verified recovery: 60 lamps returned

## 12. Notice approval

- ✅ The reviewer signs in again
- ✅ Independently approve the notice

## 13. Delivery and acknowledgement

- ✅ Queue the approved notice for delivery
- ✅ The background worker delivers it (to the local development mailbox only)
- ✅ Record the customer acknowledgement
- ✅ Resolve the quality issue after the hold review

## 14. Closing the investigation

- ✅ The reviewer signs in for the closure review
- ✅ Check the closure conditions on the case
- ✅ Record the reviewed closure
- ✅ Overview: the investigation is closed, history preserved

## 15. Factory: home and job roles

- ✅ Switch company: Lahore Knit Mills
- ✅ Home: big tiles for each job
- ✅ Preview as a floor supervisor: only their screens
- ✅ Preview as a maintenance technician
- ✅ Back to my own view
- ✅ Team: one person, one job role

## 16. Factory map

- ✅ Factory map: the whole mill in 3D, live
- ✅ Tap the dyeing building for its details
- ✅ Tap the sewing building
- ✅ Sewing floor: drag a bundle from cutting onto a line
- ✅ Move work from one line to another (keyboard works too)
- ✅ Drag a finished bundle onto Sewn
- ✅ Department cards below the scene

## 17. Dashboard and alerts

- ✅ Factory dashboard
- ✅ Alerts: run the checks now
- ✅ Acknowledge an alert and take ownership
- ✅ Resolve an alert with what was done
- ✅ Resolved alerts keep their history

## 18. Clients

- ✅ Clients: who we make for
- ✅ Add a new client
- ✅ Upload the client logo (re-encoded safely)
- ✅ Change the badge colour
- ✅ All clients with their logos

## 19. Styles and work content

- ✅ Styles and work content
- ✅ Add a style for the new client
- ✅ Add the body fabric
- ✅ Open the operation bulletin
- ✅ Add the first operation by hand
- ✅ Import the rest of the operations from CSV
- ✅ Target output for 12 operators
- ✅ Publish the bulletin (its SAM is now frozen for orders)

## 20. Production orders

- ✅ Production orders: where every order is today
- ✅ New order for Coastline Kids
- ✅ What if: three lines and higher priority?
- ✅ Apply the change and re-plan everything
- ✅ Release the order to the floor
- ✅ Cancel an order that is no longer needed
- ✅ Orders list with client badges

## 21. Planning board

- ✅ Planning board
- ✅ Show one client only
- ✅ Find an order by style
- ✅ Late orders only
- ✅ Drag a card to a more urgent lane: preview first
- ✅ Apply and re-plan
- ✅ One more sewing line on an order (+)
- ✅ Release a planned order from its card
- ✅ Order timeline and next week
- ✅ Department drill-down: sewing lines day by day
- ✅ Re-plan every open order

## 22. Line balancing

- ✅ Line balancing: every line as a skyline
- ✅ Open a line: stations, operations and the bottleneck
- ✅ Rearrange the line (a draft, the floor keeps running)
- ✅ Move an operation to another station and see the new balance
- ✅ Lay the line out automatically
- ✅ Publish the new balance to the line
- ✅ Back to the line view

## 23. Capacity and machines

- ✅ Capacity: how full each department is
- ✅ Machines: every machine as a light in its room
- ✅ Register a new machine
- ✅ Set the new machine to idle until it is threaded
- ✅ Edit the machine: its own efficiency
- ✅ Work centres

## 24. Shop floor

- ✅ Shop floor: the sewing floor, live
- ✅ Issue a bundle from the cutting buffer by dragging
- ✅ Hour-by-hour output for every line
- ✅ Open a line to record its hours
- ✅ Record an hour of output
- ✅ Record a stop: needle change on one machine
- ✅ Record an end-line quality check with defects
- ✅ Correct an hour (the original stays in history)

## 25. Batch cards

- ✅ Batch cards: knit rolls
- ✅ Record knit roll R-28001-01 from its yarn lot
- ✅ Record knit roll R-28001-02 from its yarn lot
- ✅ Dye house: load a batch with the two rolls
- ✅ Start dyeing
- ✅ Shade passed: the fabric lot is posted for traceability
- ✅ The dye house picture shows each vessel
- ✅ Cut a lay into numbered bundles
- ✅ Print the bundle tickets with QR codes
- ✅ Scan a ticket: the bundle opens
- ✅ Issue the bundle to a sewing line
- ✅ The line finishes it: mark sewn
- ✅ Bundles moving through the floor

## 26. Maintenance

- ✅ Maintenance: machines and their repairs
- ✅ Report a breakdown by asset tag
- ✅ Start the repair
- ✅ Close the ticket: the machine is back in planned capacity
- ✅ Machine history
- ✅ Open a preventive job that is due
- ✅ Do the preventive job and close it

## 27. Factory setup

- ✅ Factory setup: everything capacity is calculated from
- ✅ A new shift pattern: two 8-hour shifts, Monday to Saturday
- ✅ A public holiday at one site
- ✅ A transit time between two sites
- ✅ A downtime reason that does not count against the line
- ✅ A preventive maintenance plan for overlock machines
- ✅ A new work centre using the new shift pattern

## 28. From yarn to carton

- ✅ An order from yarn to carton
- ✅ Traceability: yarn lot → rolls → dye batch → bundles → cartons → shipment
- ✅ Post the packed garments as a garment lot
- ✅ A yarn complaint: open the draft investigation
- ✅ Trace the yarn lot downstream to the shipped garments
- ✅ Sign out

## Notes

- Notices were written to a local development mailbox (mail mode `local`); nothing was emailed.
- The malware scanner is not configured locally, so the uploaded photo stays quarantined; the video shows that.
- The reviewer's authenticator setup key is blurred in the recording.
