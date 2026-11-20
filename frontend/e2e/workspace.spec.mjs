import { test, expect } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import { resolve, sep } from 'node:path';

const origin = 'http://vericite.test';
const dist = resolve('dist');

test.beforeEach(async ({ page, context }) => {
  // Serve the actual production bundle in a browser without third-party network dependencies.
  await context.route('**/*', async route => {
    const url = new URL(route.request().url());
    if (url.origin !== origin) return route.abort();
    const file = resolve(dist, '.' + (url.pathname === '/' ? '/index.html' : url.pathname));
    if (!file.startsWith(dist + sep)) return route.abort();
    await route.fulfill({ path: file });
  });
  await page.goto(origin);
});

test('keyboard navigation, active page and WCAG checks across the workspace', async ({ page }) => {
  await page.keyboard.press('Tab');
  await expect(page.getByRole('link', { name: 'Skip to workspace' })).toBeFocused();
  await page.keyboard.press('Enter');
  await expect(page.getByRole('main')).toBeFocused();
  const nav = page.getByRole('navigation', { name: 'Workspace navigation' });
  for (const tab of ['Overview', 'Document', 'References', 'Visual Analytics', 'Reports', 'Paper chat', 'Review history']) {
    const button = nav.getByRole('button', { name: tab === 'Overview' ? /^Overview/ : tab, exact: true });
    await button.focus();
    await page.keyboard.press('Enter');
    await expect(button).toHaveAttribute('aria-current', 'page');
    await expect(nav.locator('[aria-current="page"]')).toHaveCount(1);
    const audit = await new AxeBuilder({ page }).withTags(['wcag2a','wcag2aa','wcag21a','wcag21aa']).analyze();
    expect(audit.violations, tab).toEqual([]);
  }
});

test('document input mode communicates its state and exposes a labeled editor', async ({ page }) => {
  await page.getByRole('button', { name: 'Document', exact: true }).click();
  const toggle = page.getByRole('button', { name: 'Paste or import text' });
  await toggle.focus();
  await page.keyboard.press('Space');
  await expect(toggle).toHaveAttribute('aria-pressed', 'true');
  await expect(page.getByRole('button', { name: 'Research PDF' })).toHaveAttribute('aria-pressed', 'false');
  await expect(page.getByRole('textbox', { name: 'Document text' })).toBeVisible();
});
