// Playwright tests for Mission Control project list view — phase tree
const { test, expect } = require('@playwright/test');

const MC_URL = 'http://127.0.0.1:8765';
const PROJECT_ID = 'career'; // Career Engine — has phases with assigned cards

test.describe('Project List View — Phase Tree', () => {
  test.setTimeout(60000);

  test.beforeEach(async ({ page }) => {
    await page.goto(`${MC_URL}/#projects/${PROJECT_ID}`, { waitUntil: 'domcontentloaded', timeout: 15000 });
    // Wait for project detail to load (list is default view)
    await page.waitForSelector('.phase-item', { timeout: 15000 });
  });

  test('phases render with task counts', async ({ page }) => {
    const phases = await page.locator('.phase-item').count();
    expect(phases).toBeGreaterThan(0);

    // At least one phase should have a task count badge
    const counts = await page.locator('.phase-task-count').count();
    expect(counts).toBeGreaterThan(0);
    console.log(`${phases} phases rendered, ${counts} with task counts`);
  });

  test('phase children are hidden by default', async ({ page }) => {
    const children = page.locator('.phase-children').first();
    await expect(children).toBeHidden();
  });

  test('clicking a phase expands its children', async ({ page }) => {
    // Find the first expandable phase
    const expandable = page.locator('.phase-item.expandable').first();
    await expect(expandable).toBeVisible();

    // Get the corresponding children container
    const chevron = expandable.locator('.phase-chevron');
    await expect(chevron).toBeVisible();

    // Click to expand
    await expandable.click();

    // Children should now be visible
    const childrenId = await expandable.evaluate(el => el.nextElementSibling?.id);
    const children = page.locator(`#${childrenId}`);
    await expect(children).toBeVisible();

    // Chevron should be rotated (has .expanded class)
    await expect(chevron).toHaveClass(/expanded/);

    // Should contain child items
    const childCount = await children.locator('.phase-child-item').count();
    expect(childCount).toBeGreaterThan(0);
    console.log(`Expanded phase shows ${childCount} tasks`);
  });

  test('clicking an expanded phase collapses it', async ({ page }) => {
    const expandable = page.locator('.phase-item.expandable').first();

    // Expand
    await expandable.click();
    const childrenId = await expandable.evaluate(el => el.nextElementSibling?.id);
    const children = page.locator(`#${childrenId}`);
    await expect(children).toBeVisible();

    // Collapse
    await expandable.click();
    await expect(children).toBeHidden();

    // Chevron should not have expanded class
    const chevron = expandable.locator('.phase-chevron');
    await expect(chevron).not.toHaveClass(/expanded/);
  });

  test('child items show status, id, and title', async ({ page }) => {
    // Expand first phase
    const expandable = page.locator('.phase-item.expandable').first();
    await expandable.click();

    const childrenId = await expandable.evaluate(el => el.nextElementSibling?.id);
    const firstChild = page.locator(`#${childrenId} .phase-child-item`).first();
    await expect(firstChild).toBeVisible();

    // Should have status badge, id, and title
    await expect(firstChild.locator('.related-task-status')).toBeVisible();
    await expect(firstChild.locator('.phase-child-id')).toBeVisible();
    await expect(firstChild.locator('.phase-child-title')).toBeVisible();
  });

  test('expanded phase stays open after polling interval', async ({ page }) => {
    // Expand first phase
    const expandable = page.locator('.phase-item.expandable').first();
    await expandable.click();

    const childrenId = await expandable.evaluate(el => el.nextElementSibling?.id);
    const children = page.locator(`#${childrenId}`);
    await expect(children).toBeVisible();

    // Wait longer than the 3s polling interval to ensure auto-refresh doesn't collapse it
    await page.waitForTimeout(5000);

    // Phase children should still be visible
    await expect(children).toBeVisible();

    // Chevron should still be expanded
    const chevron = expandable.locator('.phase-chevron');
    await expect(chevron).toHaveClass(/expanded/);

    // Child items should still be present
    const childCount = await children.locator('.phase-child-item').count();
    expect(childCount).toBeGreaterThan(0);
    console.log(`Phase still expanded after poll interval with ${childCount} tasks`);
  });

  test('no separate Related Tasks section exists', async ({ page }) => {
    // The old "Related Tasks" section title should not appear
    const sectionTitles = await page.locator('.project-section-title').allInnerTexts();
    const hasRelatedTasks = sectionTitles.some(t => t.toLowerCase().includes('related tasks'));
    expect(hasRelatedTasks).toBe(false);
    console.log(`Section titles: ${sectionTitles.join(', ')}`);
  });
});
