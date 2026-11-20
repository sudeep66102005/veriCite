import { test, expect } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import { resolve, sep } from 'node:path';

const origin = 'http://vericite.test';
const dist = resolve('dist');

test.beforeEach(async ({ page, context }) => {
  // Serve the actual production bundle in a browser without third-party network dependencies.
  await context.route('**/*', async (route) => {
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
  for (const tab of [
    'Overview',
    'Document',
    'References',
    'Visual Analytics',
    'Reports',
    'Paper chat',
    'Review history',
  ]) {
    const button = nav.getByRole('button', {
      name: tab === 'Overview' ? /^Overview/ : tab,
      exact: true,
    });
    await button.focus();
    await page.keyboard.press('Enter');
    await expect(button).toHaveAttribute('aria-current', 'page');
    await expect(nav.locator('[aria-current="page"]')).toHaveCount(1);
    const audit = await new AxeBuilder({ page })
      .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'])
      .analyze();
    expect(audit.violations, tab).toEqual([]);
  }
});

test('document input mode communicates its state and exposes a labeled editor', async ({
  page,
}) => {
  await page.getByRole('button', { name: 'Document', exact: true }).click();
  const toggle = page.getByRole('button', { name: 'Paste or import text' });
  await toggle.focus();
  await page.keyboard.press('Space');
  await expect(toggle).toHaveAttribute('aria-pressed', 'true');
  await expect(page.getByRole('button', { name: 'Research PDF' })).toHaveAttribute(
    'aria-pressed',
    'false',
  );
  await expect(page.getByRole('textbox', { name: 'Document text' })).toBeVisible();
});

test('keyboard focus is visible and Escape closes the source disclosure', async ({ page }) => {
  await page.keyboard.press('Tab');
  const skip = page.getByRole('link', { name: 'Skip to workspace' });
  await expect(skip).toBeFocused();
  expect(
    await skip.evaluate((el) => parseFloat(getComputedStyle(el).outlineWidth)),
  ).toBeGreaterThan(0);
  const summary = page.locator('#evidence-reading summary').first();
  await summary.focus();
  await page.keyboard.press('Enter');
  await expect(summary.locator('..')).toHaveAttribute('open', '');
  await page.keyboard.press('Escape');
  await expect(summary.locator('..')).not.toHaveAttribute('open', '');
  await expect(summary).toBeFocused();
});

test('upload manuscript, verify through FastAPI and download report', async ({
  page,
  context,
  request,
}) => {
  test.skip(!process.env.E2E_API_ORIGIN, 'requires the integration backend');
  await context.route('**/api/verify**', async (route) => {
    const incoming = route.request();
    const response = await request.fetch(
      process.env.E2E_API_ORIGIN + new URL(incoming.url()).pathname,
      {
        method: incoming.method(),
        headers: {
          'content-type': 'application/json',
          authorization: incoming.headers().authorization || '',
        },
        data: incoming.postDataBuffer() || undefined,
      },
    );
    await route.fulfill({ response });
  });
  await page.getByRole('button', { name: 'Document', exact: true }).click();
  await page.getByRole('button', { name: 'Paste or import text' }).click();
  const text = 'The telescope counted forty objects [9].';
  await page
    .getByRole('group', { name: 'Document upload' })
    .getByLabel('Choose document')
    .setInputFiles({
      name: 'observations.txt',
      mimeType: 'text/plain',
      buffer: Buffer.from(text),
    });
  await expect(page.getByLabel('Document text')).toHaveValue(text);
  await page.getByRole('button', { name: 'Verify text' }).click();
  await expect(
    page.getByRole('button', { name: /The telescope counted forty objects/ }),
  ).toBeVisible();
  await page.getByRole('button', { name: 'Reports', exact: true }).click();
  await expect(page.getByText('Source availability: no mapped citations.')).toBeVisible();
  const pending = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Download JSON' }).click();
  const stream = await (await pending).createReadStream();
  const chunks = [];
  for await (const chunk of stream) chunks.push(chunk);
  const report = JSON.parse(Buffer.concat(chunks));
  expect(report.mode).toBe('API verification');
  expect(report.claims[0]).toMatchObject({ claim: text, status: 'Unverified' });
});
