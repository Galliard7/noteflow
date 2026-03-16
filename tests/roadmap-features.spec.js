const { test, expect } = require('@playwright/test');
const MC_URL = 'http://127.0.0.1:8765';
const PROJECT_ID = 'career';

test.describe('Roadmap Features', () => {
  test.setTimeout(60000);

  test.beforeEach(async ({ page }) => {
    await page.goto(`${MC_URL}/#projects/${PROJECT_ID}/roadmap`, { waitUntil: 'domcontentloaded', timeout: 15000 });
    await page.waitForSelector('#roadmap-container canvas', { timeout: 20000 });
    await page.waitForFunction(() => typeof cyInstance !== 'undefined' && cyInstance && cyInstance.nodes().length > 0, { timeout: 10000 });
    await page.waitForTimeout(500);
  });

  test('edge creation: API call fires and persists', async ({ page }) => {
    // Monitor network requests
    const apiCalls = [];
    page.on('request', req => {
      if (req.url().includes('/api/board/cards/') && req.method() === 'PUT') {
        apiCalls.push({ url: req.url(), body: JSON.parse(req.postData() || '{}') });
      }
    });
    const apiResponses = [];
    page.on('response', res => {
      if (res.url().includes('/api/board/cards/') && res.request().method() === 'PUT') {
        res.json().then(j => apiResponses.push({ url: res.url(), status: res.status(), body: j })).catch(() => {});
      }
    });

    const container = page.locator('#roadmap-container');
    const containerBox = await container.boundingBox();

    // Find two close unconnected nodes
    const pair = await page.evaluate(() => {
      const cards = cyInstance.nodes('[type="card"]').toArray();
      let bestPair = null, bestDist = Infinity;
      for (let i = 0; i < cards.length; i++) {
        for (let j = i + 1; j < cards.length; j++) {
          const a = cards[i], b = cards[j];
          const connected = cyInstance.edges().some(e =>
            (e.data('source') === a.id() && e.data('target') === b.id()) ||
            (e.data('source') === b.id() && e.data('target') === a.id())
          );
          if (connected) continue;
          const dist = Math.sqrt(
            Math.pow(a.renderedPosition().x - b.renderedPosition().x, 2) +
            Math.pow(a.renderedPosition().y - b.renderedPosition().y, 2)
          );
          if (dist < bestDist) { bestDist = dist; bestPair = { a, b, dist }; }
        }
      }
      if (!bestPair) return null;
      const { a, b } = bestPair;
      return {
        source: { id: a.id(), slug: a.data('slug'), pos: a.renderedPosition(), bb: a.renderedBoundingBox() },
        target: { id: b.id(), slug: b.data('slug'), pos: b.renderedPosition(), bb: b.renderedBoundingBox() },
        initialEdgeCount: cyInstance.edges().length,
      };
    });
    console.log(`Source: ${pair.source.slug}, Target: ${pair.target.slug}`);

    // Hover source → get handle
    await page.mouse.move(containerBox.x + pair.source.pos.x, containerBox.y + pair.source.pos.y);
    await page.waitForTimeout(300);
    const handlePos = await page.evaluate(() => {
      const h = cyInstance.nodes('.eh-handle');
      return h.length ? h[0].renderedPosition() : null;
    });
    expect(handlePos).not.toBeNull();

    // Drag handle to target
    const hx = containerBox.x + handlePos.x, hy = containerBox.y + handlePos.y;
    const tx = containerBox.x + pair.target.pos.x, ty = containerBox.y + pair.target.pos.y;
    await page.mouse.move(hx, hy);
    await page.waitForTimeout(100);
    await page.mouse.down();
    for (let i = 1; i <= 20; i++) {
      await page.mouse.move(hx + (tx - hx) * (i / 20), hy + (ty - hy) * (i / 20));
      await page.waitForTimeout(30);
    }
    await page.mouse.up();
    await page.waitForTimeout(3000); // Wait for async complete callback

    console.log('PUT requests:', JSON.stringify(apiCalls, null, 2));
    console.log('PUT responses:', JSON.stringify(apiResponses, null, 2));

    // Verify API was called with correct depends_on
    expect(apiCalls.length).toBeGreaterThan(0);
    const depCall = apiCalls.find(c => c.url.includes(pair.target.slug));
    if (depCall) {
      console.log(`API called for target ${pair.target.slug} with depends_on: ${JSON.stringify(depCall.body.depends_on)}`);
      expect(depCall.body.depends_on).toContain(pair.source.slug);
    } else {
      // Maybe depends_on was set on source (direction check)
      const srcCall = apiCalls.find(c => c.url.includes(pair.source.slug));
      console.log(`API called for source ${pair.source.slug} with depends_on: ${JSON.stringify(srcCall?.body?.depends_on)}`);
    }

    // Check toast appeared
    const toastText = await page.evaluate(() => {
      const t = document.querySelector('.roadmap-toast');
      return t ? t.textContent : null;
    });
    console.log(`Toast: ${toastText}`);

    // Verify graph has new edge
    const newEdgeCount = await page.evaluate(() => cyInstance.edges().length);
    console.log(`Edges: ${pair.initialEdgeCount} → ${newEdgeCount}`);
    expect(newEdgeCount).toBe(pair.initialEdgeCount + 1);

    // REFRESH and verify persistence
    await page.goto(`${MC_URL}/#projects/${PROJECT_ID}/roadmap`, { waitUntil: 'domcontentloaded', timeout: 15000 });
    await page.waitForSelector('#roadmap-container canvas', { timeout: 20000 });
    await page.waitForFunction(() => typeof cyInstance !== 'undefined' && cyInstance && cyInstance.nodes().length > 0, { timeout: 10000 });
    await page.waitForTimeout(500);

    const afterRefresh = await page.evaluate(() => cyInstance.edges().length);
    console.log(`Edges after refresh: ${afterRefresh}`);
    expect(afterRefresh).toBe(pair.initialEdgeCount + 1);

    // Cleanup
    await page.evaluate(async (data) => {
      const res = await fetch(`/api/board`, { method: 'GET' });
      const board = await res.json();
      const card = board.cards.find(c => c.slug === data.targetSlug);
      if (card) {
        const newDeps = (card.depends_on || []).filter(d => d !== data.sourceSlug);
        await fetch(`/api/board/cards/${data.targetSlug}`, {
          method: 'PUT', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ depends_on: newDeps }),
        });
      }
    }, { targetSlug: pair.target.slug, sourceSlug: pair.source.slug });
    console.log('Cleaned up');
  });

  test('+ Task: creates card on roadmap in correct phase', async ({ page }) => {
    const initialState = await page.evaluate(() => ({
      nodeCount: cyInstance.nodes('[type="card"]').length,
      edgeCount: cyInstance.edges().length,
    }));
    console.log(`Initial: ${initialState.nodeCount} nodes, ${initialState.edgeCount} edges`);

    const testTitle = `PW-Test-Card-${Date.now()}`;

    // Click + Task
    await page.click('button:has-text("+ Task")');
    await page.waitForSelector('#roadmapAddCardModal.show', { timeout: 3000 });

    // Verify project is pre-linked (no project selector in the modal)
    const hasProjectField = await page.evaluate(() => !!document.querySelector('#roadmapAddCardModal #newCardProjectCombo'));
    expect(hasProjectField).toBe(false);

    // Read available phases
    const phases = await page.evaluate(() =>
      Array.from(document.getElementById('roadmapNewCardPhase').options).map(o => ({ value: o.value, text: o.text, selected: o.selected }))
    );
    console.log('Phase options:', JSON.stringify(phases));
    expect(phases.length).toBeGreaterThan(0);

    // Select a specific phase
    const targetPhase = phases[1]?.value || phases[0].value; // pick 2nd phase if available
    await page.selectOption('#roadmapNewCardPhase', targetPhase);

    // Fill form
    await page.fill('#roadmapNewCardTitle', testTitle);
    await page.fill('#roadmapNewCardDesc', 'Playwright test card - will be deleted');
    await page.selectOption('#roadmapNewCardStatus', 'pending');

    // Submit
    const [createResponse] = await Promise.all([
      page.waitForResponse(r => r.url().includes('/api/board/cards') && r.request().method() === 'POST'),
      page.click('#roadmapAddCardModal .btn-primary'),
    ]);
    const createJson = await createResponse.json();
    const createResult = createJson.card || createJson;
    console.log('Create response:', JSON.stringify(createResult));
    expect(createResult.id).toBeTruthy();
    expect(createResult.slug).toBeTruthy();
    expect(createResult.project).toBe(PROJECT_ID);
    expect(createResult.phase).toBe(targetPhase);

    // Wait for re-render
    await page.waitForTimeout(2000);

    // Verify card appears on graph
    const afterCreate = await page.evaluate((title) => {
      const nodes = cyInstance.nodes('[type="card"]');
      const found = nodes.filter(n => n.data('fullTitle') === title);
      return {
        nodeCount: nodes.length,
        found: found.length > 0,
        nodeId: found.length > 0 ? found[0].id() : null,
        nodeSlug: found.length > 0 ? found[0].data('slug') : null,
        parentId: found.length > 0 ? found[0].data('parent') : null,
      };
    }, testTitle);
    console.log(`After create: ${afterCreate.nodeCount} nodes, found=${afterCreate.found}, parent=${afterCreate.parentId}`);
    expect(afterCreate.found).toBe(true);
    expect(afterCreate.nodeCount).toBe(initialState.nodeCount + 1);

    // Verify it's in the correct phase compound node
    if (afterCreate.parentId) {
      const phaseLabel = await page.evaluate((parentId) => {
        const phaseNode = cyInstance.getElementById(parentId);
        return phaseNode ? phaseNode.data('label') : null;
      }, afterCreate.parentId);
      console.log(`Card placed in phase: "${phaseLabel}", expected: "${targetPhase}"`);
      expect(phaseLabel).toBe(targetPhase);
    }

    // Verify modal closed
    const modalVisible = await page.evaluate(() =>
      document.getElementById('roadmapAddCardModal').classList.contains('show')
    );
    expect(modalVisible).toBe(false);

    // Verify toast
    const toast = await page.evaluate(() => {
      const t = document.querySelector('.roadmap-toast');
      return t ? t.textContent : null;
    });
    console.log(`Toast: ${toast}`);

    // REFRESH and verify persistence
    await page.goto(`${MC_URL}/#projects/${PROJECT_ID}/roadmap`, { waitUntil: 'domcontentloaded', timeout: 15000 });
    await page.waitForSelector('#roadmap-container canvas', { timeout: 20000 });
    await page.waitForFunction(() => typeof cyInstance !== 'undefined' && cyInstance && cyInstance.nodes().length > 0, { timeout: 10000 });
    await page.waitForTimeout(500);

    const afterRefresh = await page.evaluate((title) => {
      const found = cyInstance.nodes('[type="card"]').filter(n => n.data('fullTitle') === title);
      return { found: found.length > 0, nodeCount: cyInstance.nodes('[type="card"]').length };
    }, testTitle);
    console.log(`After refresh: found=${afterRefresh.found}, nodes=${afterRefresh.nodeCount}`);
    expect(afterRefresh.found).toBe(true);

    // Also verify card appears on Tasks board
    await page.goto(`${MC_URL}/#tasks`, { waitUntil: 'domcontentloaded', timeout: 15000 });
    await page.waitForTimeout(1000);
    const onTaskBoard = await page.evaluate((title) => {
      return document.body.innerText.includes(title);
    }, testTitle);
    console.log(`Visible on Tasks board: ${onTaskBoard}`);
    expect(onTaskBoard).toBe(true);

    // Cleanup
    await page.evaluate(async (slug) => {
      await fetch(`/api/board/cards/${slug}`, { method: 'DELETE' });
    }, createResult.slug);
    console.log(`Cleaned up: ${createResult.slug}`);
  });

  test('+ Task: empty title prevents creation', async ({ page }) => {
    await page.click('button:has-text("+ Task")');
    await page.waitForSelector('#roadmapAddCardModal.show', { timeout: 3000 });

    // Leave title empty, click create
    await page.click('#roadmapAddCardModal .btn-primary');
    await page.waitForTimeout(500);

    // Modal should still be open (no API call)
    const modalOpen = await page.evaluate(() =>
      document.getElementById('roadmapAddCardModal').classList.contains('show')
    );
    expect(modalOpen).toBe(true);
    console.log('Empty title correctly prevented creation');
  });

  test('+ Task: card with default phase selection', async ({ page }) => {
    await page.click('button:has-text("+ Task")');
    await page.waitForSelector('#roadmapAddCardModal.show', { timeout: 3000 });

    // Check which phase is pre-selected (should be first active or first pending)
    const selectedPhase = await page.evaluate(() => {
      const sel = document.getElementById('roadmapNewCardPhase');
      return sel.value;
    });
    console.log(`Default phase: "${selectedPhase}"`);
    expect(selectedPhase).toBeTruthy();

    // Verify it's a real phase from the project
    const projectPhases = await page.evaluate(() => {
      const proj = board.projects.find(p => p.id === 'career');
      return proj ? proj.phases.map(p => p.name) : [];
    });
    console.log(`Project phases: ${JSON.stringify(projectPhases)}`);
    expect(projectPhases).toContain(selectedPhase);
  });

  test('edge deletion via Delete key works and persists', async ({ page }) => {
    const initialEdges = await page.evaluate(() => cyInstance.edges().length);
    if (initialEdges === 0) { test.skip('No edges'); return; }

    // Get first edge info
    const edgeInfo = await page.evaluate(() => {
      const e = cyInstance.edges()[0];
      const src = cyInstance.getElementById(e.data('source'));
      const tgt = cyInstance.getElementById(e.data('target'));
      return {
        sourceSlug: src.data('slug'),
        targetSlug: tgt.data('slug'),
        sourceId: e.data('source'),
        targetId: e.data('target'),
      };
    });
    console.log(`Deleting edge: ${edgeInfo.sourceSlug} → ${edgeInfo.targetSlug}`);

    // Select edge and press Delete
    await page.evaluate(() => { cyInstance.edges()[0].select(); });
    await page.keyboard.press('Delete');
    await page.waitForTimeout(2000);

    const afterDelete = await page.evaluate(() => cyInstance.edges().length);
    console.log(`Edges: ${initialEdges} → ${afterDelete}`);
    expect(afterDelete).toBe(initialEdges - 1);

    // Refresh and verify persistence
    await page.goto(`${MC_URL}/#projects/${PROJECT_ID}/roadmap`, { waitUntil: 'domcontentloaded', timeout: 15000 });
    await page.waitForSelector('#roadmap-container canvas', { timeout: 20000 });
    await page.waitForFunction(() => typeof cyInstance !== 'undefined' && cyInstance && cyInstance.nodes().length > 0, { timeout: 10000 });
    await page.waitForTimeout(500);

    const afterRefresh = await page.evaluate(() => cyInstance.edges().length);
    console.log(`Edges after refresh: ${afterRefresh}`);
    expect(afterRefresh).toBe(initialEdges - 1);

    // Restore edge
    await page.evaluate(async (data) => {
      const res = await fetch('/api/board', { method: 'GET' });
      const board = await res.json();
      const card = board.cards.find(c => c.slug === data.targetSlug);
      if (card) {
        const deps = [...(card.depends_on || []), data.sourceSlug];
        await fetch(`/api/board/cards/${data.targetSlug}`, {
          method: 'PUT', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ depends_on: deps }),
        });
      }
    }, edgeInfo);
    console.log('Restored edge');
  });
});
