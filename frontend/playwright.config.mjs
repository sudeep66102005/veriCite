import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './e2e',
  workers: 1,
  use: {
    browserName: 'chromium',
    reducedMotion: 'reduce',
    launchOptions: {
      executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || undefined,
      args: JSON.parse(process.env.PLAYWRIGHT_CHROMIUM_ARGS || '[]'),
    },
  },
  projects: [
    { name: 'desktop', use: { viewport: { width: 1280, height: 900 } } },
    { name: 'mobile', use: { viewport: { width: 390, height: 844 } } },
  ],
});
