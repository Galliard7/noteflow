// Playwright tests for Mission Control roadmap view
// Run: npx playwright test tests/roadmap.spec.js --headed
const { test, expect } = require('@playwright/test');

const MC_URL = 'http://127.0.0.1:8765';
const PROJECT_ID = 'career'; // Career Engine — has nodes + deps + phases

test.describe('Roadmap Graph', () => {
  test.setTimeout(60000);

  test.beforeEach(async ({ page }) => {
    // Navigate directly to roadmap view via hash
    await page.goto(`${MC_URL}/#projects/${PROJECT_ID}/roadmap`, { waitUntil: 'domcontentloaded', timeout: 15000 });
    // Wait for Cytoscape to render (canvas appears when graph is drawn)
    await page.waitForSelector('#roadmap-container canvas', { timeout: 20000 });
    // Wait for cyInstance to be populated with nodes
    await page.waitForFunction(() => typeof cyInstance !== 'undefined' && cyInstance && cyInstance.nodes().length > 0, { timeout: 10000 });
    // Give layout a moment to settle
    await page.waitForTimeout(500);
  });

  test('graph renders with nodes', async ({ page }) => {
    const canvas = page.locator('#roadmap-container canvas');
    await expect(canvas.first()).toBeVisible();

    const nodeCount = await page.evaluate(() => cyInstance.nodes().length);
    expect(nodeCount).toBeGreaterThan(0);
    console.log(`Graph rendered with ${nodeCount} nodes`);
  });

  test('zoom level persists across polling cycles', async ({ page }) => {
    const initialZoom = await page.evaluate(() => cyInstance.zoom());

    await page.evaluate(() => {
      cyInstance.zoom({ level: cyInstance.zoom() * 1.8, renderedPosition: { x: 400, y: 300 } });
    });
    const zoomedLevel = await page.evaluate(() => cyInstance.zoom());
    expect(zoomedLevel).toBeGreaterThan(initialZoom * 1.3);

    await page.waitForTimeout(5000);

    const afterPollZoom = await page.evaluate(() => cyInstance.zoom());
    expect(afterPollZoom).toBeCloseTo(zoomedLevel, 2);
    console.log(`Zoom held: ${afterPollZoom.toFixed(3)} (expected ${zoomedLevel.toFixed(3)})`);
  });

  test('zoom via mouse wheel persists', async ({ page }) => {
    const container = page.locator('#roadmap-container');
    const box = await container.boundingBox();
    const cx = box.x + box.width / 2;
    const cy = box.y + box.height / 2;
    const initialZoom = await page.evaluate(() => cyInstance.zoom());

    await page.mouse.move(cx, cy);
    for (let i = 0; i < 5; i++) {
      await page.mouse.wheel(0, -120);
      await page.waitForTimeout(100);
    }

    const zoomedLevel = await page.evaluate(() => cyInstance.zoom());
    expect(zoomedLevel).toBeGreaterThan(initialZoom);

    await page.waitForTimeout(5000);

    const afterPollZoom = await page.evaluate(() => cyInstance.zoom());
    expect(afterPollZoom).toBeCloseTo(zoomedLevel, 2);
    console.log(`Wheel zoom held: ${afterPollZoom.toFixed(3)}`);
  });

  test('node drag positions persist', async ({ page }) => {
    const initial = await page.evaluate(() => {
      const node = cyInstance.nodes('[type="card"]')[0];
      return { id: node.id(), pos: { ...node.position() } };
    });

    // Simulate drag: move position then trigger state save
    const newX = initial.pos.x + 100;
    const newY = initial.pos.y + 50;
    await page.evaluate(({ id, x, y }) => {
      const node = cyInstance.getElementById(id);
      node.position({ x, y });
      saveCyState();
    }, { id: initial.id, x: newX, y: newY });

    await page.waitForTimeout(5000);

    const afterPoll = await page.evaluate((id) => {
      return { ...cyInstance.getElementById(id).position() };
    }, initial.id);
    expect(afterPoll.x).toBeCloseTo(newX, 0);
    expect(afterPoll.y).toBeCloseTo(newY, 0);
    console.log(`Node ${initial.id} position held: (${afterPoll.x.toFixed(0)}, ${afterPoll.y.toFixed(0)})`);
  });

  test('positions persist after navigating away and back', async ({ page }) => {
    const initial = await page.evaluate(() => {
      const node = cyInstance.nodes('[type="card"]')[0];
      return { id: node.id(), pos: { ...node.position() } };
    });

    const newX = initial.pos.x + 150;
    await page.evaluate(({ id, x }) => {
      const node = cyInstance.getElementById(id);
      node.position({ x, y: node.position().y });
      saveCyState();
    }, { id: initial.id, x: newX });

    // Switch to list view and back
    await page.click('button.roadmap-toggle-btn:text("List")');
    await page.waitForTimeout(500);
    await page.click('button.roadmap-toggle-btn:text("Roadmap")');
    await page.waitForSelector('#roadmap-container canvas', { timeout: 10000 });
    await page.waitForTimeout(1000);

    const restored = await page.evaluate((id) => {
      return { ...cyInstance.getElementById(id).position() };
    }, initial.id);
    expect(restored.x).toBeCloseTo(newX, 0);
    console.log(`Position restored: x=${restored.x.toFixed(0)} (expected ${newX.toFixed(0)})`);
  });

  test('zoom persists after navigating away and back', async ({ page }) => {
    await page.evaluate(() => {
      cyInstance.zoom({ level: 2.0, renderedPosition: { x: 400, y: 300 } });
    });
    const customZoom = await page.evaluate(() => cyInstance.zoom());

    await page.click('button.roadmap-toggle-btn:text("List")');
    await page.waitForTimeout(500);
    await page.click('button.roadmap-toggle-btn:text("Roadmap")');
    await page.waitForSelector('#roadmap-container canvas', { timeout: 10000 });
    await page.waitForTimeout(1000);

    const restoredZoom = await page.evaluate(() => cyInstance.zoom());
    expect(restoredZoom).toBeCloseTo(customZoom, 1);
    console.log(`Zoom restored: ${restoredZoom.toFixed(3)} (expected ${customZoom.toFixed(3)})`);
  });

  test('reset layout button restores default positions', async ({ page }) => {
    // Record default positions
    const defaultPositions = await page.evaluate(() => {
      const positions = {};
      cyInstance.nodes('[type="card"]').forEach(n => {
        positions[n.id()] = { ...n.position() };
      });
      return positions;
    });
    const defaultZoom = await page.evaluate(() => cyInstance.zoom());

    // Move a node and change zoom
    const nodeId = Object.keys(defaultPositions)[0];
    await page.evaluate(({ id }) => {
      const node = cyInstance.getElementById(id);
      node.position({ x: node.position().x + 200, y: node.position().y + 200 });
      cyInstance.zoom({ level: 2.5, renderedPosition: { x: 400, y: 300 } });
      saveCyState();
    }, { id: nodeId });

    // Verify the node moved
    const movedPos = await page.evaluate((id) => ({ ...cyInstance.getElementById(id).position() }), nodeId);
    expect(movedPos.x).toBeCloseTo(defaultPositions[nodeId].x + 200, 0);

    // Click reset
    await page.click('.roadmap-reset-btn');
    await page.waitForTimeout(500);

    // Positions should be back to dagre layout defaults
    const resetPos = await page.evaluate((id) => ({ ...cyInstance.getElementById(id).position() }), nodeId);
    // After reset, positions should match original dagre layout (approximately)
    expect(resetPos.x).toBeCloseTo(defaultPositions[nodeId].x, 0);
    expect(resetPos.y).toBeCloseTo(defaultPositions[nodeId].y, 0);
    console.log(`Reset restored node ${nodeId}: (${resetPos.x.toFixed(0)}, ${resetPos.y.toFixed(0)})`);

    // Zoom should be reset too (fit to view)
    const resetZoom = await page.evaluate(() => cyInstance.zoom());
    expect(resetZoom).toBeCloseTo(defaultZoom, 1);
    console.log(`Zoom reset: ${resetZoom.toFixed(3)} (was 2.500, default ${defaultZoom.toFixed(3)})`);
  });
});
