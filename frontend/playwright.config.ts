import { defineConfig } from '@playwright/test';
export default defineConfig({ testDir: './e2e', workers: 1, timeout: 20000,
  use: { baseURL: 'http://127.0.0.1:4173', headless: true },
  webServer: { command: 'npm run preview -- --host 127.0.0.1 --port 4173 --strictPort', url: 'http://127.0.0.1:4173', reuseExistingServer: false },
});
