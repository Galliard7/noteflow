// Playwright tests for Stack tab — +Task button and task creation modal
const { test, expect } = require('@playwright/test');

const MC_URL = 'http://127.0.0.1:8765';

test.describe('Stack Tab — +Task Modal', () => {
  test.setTimeout(60000);

  test.beforeEach(async ({ page }) => {
    await page.goto(`${MC_URL}/#stack`, { waitUntil: 'domcontentloaded', timeout: 15000 });
    // Wait for stack toolbar to load
    await page.waitForSelector('.stack-toolbar', { timeout: 15000 });
  });

  test('+Task button is visible and +Lane button is gone', async ({ page }) => {
    const taskBtn = page.locator('.stack-btn', { hasText: '+ Task' });
    await expect(taskBtn).toBeVisible();

    const laneBtn = page.locator('.stack-btn', { hasText: '+ Lane' });
    await expect(laneBtn).toHaveCount(0);
  });

  test('+Task button opens the modal', async ({ page }) => {
    await page.locator('.stack-btn', { hasText: '+ Task' }).click();
    const modal = page.locator('#stackTaskModal');
    await expect(modal).toBeVisible({ timeout: 5000 });

    // Title input should be visible
    await expect(page.locator('#stackTaskTitle')).toBeVisible();

    // Board link toggle should be visible and unchecked
    const toggle = page.locator('#stackTaskLinkBoard');
    await expect(toggle).toBeVisible();
    await expect(toggle).not.toBeChecked();

    // Board fields should be hidden by default
    await expect(page.locator('#stackTaskBoardFields')).toBeHidden();
  });

  test('toggling "Also create a board card" reveals board fields', async ({ page }) => {
    await page.locator('.stack-btn', { hasText: '+ Task' }).click();
    await page.waitForSelector('#stackTaskModal.show', { timeout: 5000 });

    // Toggle on
    await page.locator('#stackTaskLinkBoard').check();
    await expect(page.locator('#stackTaskBoardFields')).toBeVisible();

    // Should show Description, Project, Status fields
    await expect(page.locator('#stackTaskDesc')).toBeVisible();
    await expect(page.locator('#stackTaskProjectCombo')).toBeVisible();
    await expect(page.locator('#stackTaskStatus')).toBeVisible();

    // Toggle off
    await page.locator('#stackTaskLinkBoard').uncheck();
    await expect(page.locator('#stackTaskBoardFields')).toBeHidden();
  });

  test('creating a custom task (no board link) adds it to the stack', async ({ page }) => {
    const taskTitle = 'Test task ' + Date.now();

    await page.locator('.stack-btn', { hasText: '+ Task' }).click();
    await page.waitForSelector('#stackTaskModal.show', { timeout: 5000 });

    await page.locator('#stackTaskTitle').fill(taskTitle);
    await page.locator('#stackTaskModal button', { hasText: 'Create' }).click();

    // Modal should close
    await expect(page.locator('#stackTaskModal')).toBeHidden({ timeout: 5000 });

    // Task should appear on the stack board
    const card = page.locator('.stack-card-title', { hasText: taskTitle });
    await expect(card).toBeVisible({ timeout: 5000 });
  });

  test('creating a task with board link creates both stack item and board card', async ({ page }) => {
    const taskTitle = 'Board-linked task ' + Date.now();

    await page.locator('.stack-btn', { hasText: '+ Task' }).click();
    await page.waitForSelector('#stackTaskModal.show', { timeout: 5000 });

    await page.locator('#stackTaskTitle').fill(taskTitle);
    await page.locator('#stackTaskLinkBoard').check();

    // Fill description
    await page.locator('#stackTaskDesc').fill('Test description');

    // Select a project from the combobox
    const projectInput = page.locator('#stackTaskProject');
    await projectInput.click();
    // Pick the first project from the dropdown
    const firstProject = page.locator('#stackTaskProject-dropdown .combo-option').first();
    await firstProject.waitFor({ state: 'visible', timeout: 5000 });
    await firstProject.click();

    // Status should already default to pending
    const statusVal = await page.locator('#stackTaskStatus').inputValue();
    expect(statusVal).toBe('pending');

    await page.locator('#stackTaskModal button', { hasText: 'Create' }).click();

    // Modal should close
    await expect(page.locator('#stackTaskModal')).toBeHidden({ timeout: 5000 });

    // Task should appear on the stack with "Board" badge
    const card = page.locator('.stack-card', { hasText: taskTitle });
    await expect(card).toBeVisible({ timeout: 5000 });
    const boardBadge = card.locator('.stack-badge.brd');
    await expect(boardBadge).toBeVisible();
  });

  test('modal cancel does not create a task', async ({ page }) => {
    await page.locator('.stack-btn', { hasText: '+ Task' }).click();
    await page.waitForSelector('#stackTaskModal.show', { timeout: 5000 });

    await page.locator('#stackTaskTitle').fill('Should not exist');
    await page.locator('#stackTaskModal button', { hasText: 'Cancel' }).click();

    // Modal closes
    await expect(page.locator('#stackTaskModal')).toBeHidden({ timeout: 5000 });

    // Task should NOT appear
    const card = page.locator('.stack-card-title', { hasText: 'Should not exist' });
    await expect(card).toHaveCount(0);
  });

  test('Push to Board from kebab menu opens modal with full card fields', async ({ page }) => {
    // First create a custom task
    const taskTitle = 'Push test ' + Date.now();
    await page.locator('.stack-btn', { hasText: '+ Task' }).click();
    await page.waitForSelector('#stackTaskModal.show', { timeout: 5000 });
    await page.locator('#stackTaskTitle').fill(taskTitle);
    await page.locator('#stackTaskModal button', { hasText: 'Create' }).click();
    await expect(page.locator('#stackTaskModal')).toBeHidden({ timeout: 5000 });

    // Find the card and open its kebab menu
    const card = page.locator('.stack-card', { hasText: taskTitle });
    await expect(card).toBeVisible({ timeout: 5000 });
    await card.locator('.stack-kebab').click();

    // Click "Push to Board"
    const pushBtn = card.locator('.stack-menu-item', { hasText: 'Push to Board' });
    await expect(pushBtn).toBeVisible();
    await pushBtn.click();

    // Push to Board modal should open with full fields
    const modal = page.locator('#pushBoardModal');
    await expect(modal).toBeVisible({ timeout: 5000 });

    // Title should be pre-filled
    const titleVal = await page.locator('#pushBoardTitle').inputValue();
    expect(titleVal).toBe(taskTitle);

    // All card fields should be visible
    await expect(page.locator('#pushBoardDesc')).toBeVisible();
    await expect(page.locator('#pushBoardProjectCombo')).toBeVisible();
    await expect(page.locator('#pushBoardStatus')).toBeVisible();

    // Cancel
    await page.locator('#pushBoardModal button', { hasText: 'Cancel' }).click();
    await expect(modal).toBeHidden({ timeout: 5000 });
  });

  test('Push to Board converts custom card to board-linked card', async ({ page }) => {
    // Create a custom task
    const taskTitle = 'Convert test ' + Date.now();
    await page.locator('.stack-btn', { hasText: '+ Task' }).click();
    await page.waitForSelector('#stackTaskModal.show', { timeout: 5000 });
    await page.locator('#stackTaskTitle').fill(taskTitle);
    await page.locator('#stackTaskModal button', { hasText: 'Create' }).click();
    await expect(page.locator('#stackTaskModal')).toBeHidden({ timeout: 5000 });

    // Verify it's custom
    const card = page.locator('.stack-card', { hasText: taskTitle });
    await expect(card.locator('.stack-badge.cst')).toBeVisible();

    // Open kebab > Push to Board
    await card.locator('.stack-kebab').click();
    await card.locator('.stack-menu-item', { hasText: 'Push to Board' }).click();
    await page.waitForSelector('#pushBoardModal.show', { timeout: 5000 });

    // Select a project
    const projectInput = page.locator('#pushBoardProject');
    await projectInput.click();
    const firstProject = page.locator('#pushBoardProject-dropdown .combo-option').first();
    await firstProject.waitFor({ state: 'visible', timeout: 5000 });
    await firstProject.click();

    // Push it
    await page.locator('#pushBoardModal button', { hasText: 'Push' }).click();
    await expect(page.locator('#pushBoardModal')).toBeHidden({ timeout: 5000 });

    // Card should now show Board badge instead of Custom
    const updatedCard = page.locator('.stack-card', { hasText: taskTitle });
    await expect(updatedCard).toBeVisible({ timeout: 5000 });
    await expect(updatedCard.locator('.stack-badge.brd')).toBeVisible();
  });
});
