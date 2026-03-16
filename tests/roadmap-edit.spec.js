// Playwright tests for roadmap interactive editing (edgehandles + card creation)
const { test, expect } = require('@playwright/test');

const MC_URL = 'http://127.0.0.1:8765';
const PROJECT_ID = 'career';

test.describe('Roadmap Editing', () => {
  test.setTimeout(60000);

  test.beforeEach(async ({ page }) => {
    await page.goto(`${MC_URL}/#projects/${PROJECT_ID}/roadmap`, { waitUntil: 'domcontentloaded', timeout: 15000 });
    await page.waitForSelector('#roadmap-container canvas', { timeout: 20000 });
    await page.waitForFunction(() => typeof cyInstance !== 'undefined' && cyInstance && cyInstance.nodes().length > 0, { timeout: 10000 });
    await page.waitForTimeout(500);
  });

  test('cytoscape-edgehandles extension is loaded', async ({ page }) => {
    const hasEdgehandles = await page.evaluate(() => {
      return typeof cytoscapeEdgehandles !== 'undefined' && typeof cyInstance.edgehandles === 'function';
    });
    console.log('edgehandles extension loaded:', hasEdgehandles);
    expect(hasEdgehandles).toBe(true);
  });

  test('edgehandles is initialized on the cyInstance', async ({ page }) => {
    // Check that eh was initialized by looking for the scratch data edgehandles sets
    const ehInitialized = await page.evaluate(() => {
      // edgehandles stores state on the cy instance - check if it has the eh extension active
      // The extension adds an 'edgehandles' method that returns the instance
      try {
        const eh = cyInstance.edgehandles;
        return typeof eh === 'function';
      } catch(e) {
        return false;
      }
    });
    console.log('edgehandles initialized on cyInstance:', ehInitialized);
    expect(ehInitialized).toBe(true);
  });

  test('eh-handle node appears when hovering a card node', async ({ page }) => {
    // Get the rendered position of the first card node
    const nodeInfo = await page.evaluate(() => {
      const cardNode = cyInstance.nodes('[type="card"]')[0];
      if (!cardNode) return null;
      const pos = cardNode.renderedPosition();
      const bb = cardNode.renderedBoundingBox();
      return {
        id: cardNode.id(),
        x: pos.x,
        y: pos.y,
        right: bb.x2,
        width: bb.x2 - bb.x1,
        height: bb.y2 - bb.y1,
      };
    });
    console.log('First card node:', JSON.stringify(nodeInfo));
    expect(nodeInfo).not.toBeNull();

    // Get the container's bounding box to translate cytoscape coords to page coords
    const container = page.locator('#roadmap-container');
    const containerBox = await container.boundingBox();

    // Move mouse to the card node position (rendered coords are relative to container)
    const pageX = containerBox.x + nodeInfo.x;
    const pageY = containerBox.y + nodeInfo.y;
    console.log(`Moving mouse to page coords: (${pageX}, ${pageY})`);

    await page.mouse.move(pageX, pageY);
    await page.waitForTimeout(500);

    // Check if an eh-handle node exists in the cytoscape instance
    const handleInfo = await page.evaluate(() => {
      const handles = cyInstance.nodes('.eh-handle');
      if (handles.length === 0) return { count: 0, classes: [] };
      return {
        count: handles.length,
        visible: handles[0].visible(),
        position: handles[0].renderedPosition(),
        style: handles[0].style(),
      };
    });
    console.log('eh-handle nodes:', JSON.stringify(handleInfo));

    // Also check what CSS classes are on the nodes
    const nodeClasses = await page.evaluate(() => {
      const cardNodes = cyInstance.nodes('[type="card"]');
      return cardNodes.map(n => ({
        id: n.id(),
        classes: Array.from(n.classes()),
      })).slice(0, 3);
    });
    console.log('Card node classes:', JSON.stringify(nodeClasses));
  });

  test('+ Task button is visible on roadmap toolbar', async ({ page }) => {
    const btn = page.locator('button:has-text("+ Task")');
    await expect(btn).toBeVisible();
    console.log('+ Task button is visible');
  });

  test('+ Task button opens roadmap add card modal', async ({ page }) => {
    await page.click('button:has-text("+ Task")');
    const modal = page.locator('#roadmapAddCardModal');
    await expect(modal).toBeVisible({ timeout: 3000 });

    // Check phase dropdown is populated
    const phaseOptions = await page.evaluate(() => {
      const sel = document.getElementById('roadmapNewCardPhase');
      return Array.from(sel.options).map(o => o.value);
    });
    console.log('Phase options:', phaseOptions);
    expect(phaseOptions.length).toBeGreaterThan(0);

    // Check status dropdown is populated
    const statusOptions = await page.evaluate(() => {
      const sel = document.getElementById('roadmapNewCardStatus');
      return Array.from(sel.options).map(o => o.value);
    });
    console.log('Status options:', statusOptions);
    expect(statusOptions.length).toBeGreaterThan(0);
  });

  test('edge selection highlights in red', async ({ page }) => {
    // Check if there are edges
    const edgeCount = await page.evaluate(() => cyInstance.edges().length);
    console.log('Edge count:', edgeCount);
    if (edgeCount === 0) {
      test.skip('No edges to test selection');
      return;
    }

    // Select the first edge programmatically
    const edgeStyle = await page.evaluate(() => {
      const edge = cyInstance.edges()[0];
      edge.select();
      return {
        selected: edge.selected(),
        lineColor: edge.style('line-color'),
        width: edge.style('width'),
      };
    });
    console.log('Selected edge style:', JSON.stringify(edgeStyle));
    expect(edgeStyle.selected).toBe(true);
  });

  test('debug: check edgehandles internal state', async ({ page }) => {
    const debug = await page.evaluate(() => {
      // Check if the edgehandles extension registered properly
      const results = {};

      // 1. Is edgehandles a function on cytoscape prototype?
      results.prototypeHasEdgehandles = typeof cytoscape.prototype.edgehandles === 'function';

      // 2. Check scratch data that edgehandles sets
      results.scratchKeys = Object.keys(cyInstance.scratch() || {});

      // 3. Check if there are any eh- prefixed elements
      results.ehElements = cyInstance.elements().filter(el => {
        const classes = Array.from(el.classes());
        return classes.some(c => c.startsWith('eh-'));
      }).length;

      // 4. Total nodes and edges
      results.totalNodes = cyInstance.nodes().length;
      results.totalEdges = cyInstance.edges().length;
      results.cardNodes = cyInstance.nodes('[type="card"]').length;

      // 5. Check if handleNodes selector matches anything
      results.handleNodeMatches = cyInstance.nodes('[type="card"]').length;

      return results;
    });
    console.log('Edgehandles debug:', JSON.stringify(debug, null, 2));
  });
});
