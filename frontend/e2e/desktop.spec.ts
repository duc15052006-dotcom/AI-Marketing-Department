import { test, expect, Page } from '@playwright/test';

async function fixture(page: Page, native = true, empty = false) {
  const state = { calls: [] as { path: string; body: any }[], status: 'APPROVAL_REQUIRED', defer: false, deferProposal: false,
    release: null as null | (() => void), sessions: empty ? [] : [
      { chat_id: 'a', title: 'Chat A', messages: [], status: 'ACTIVE' },
      { chat_id: 'b', title: 'Chat B', messages: [], status: 'ACTIVE' }] };
  const api = async (method: string, path: string, raw: string | null) => {
    const body = raw ? JSON.parse(raw) : {};
    state.calls.push({ path, body });
    if (path === 'review_pending_approval') {
      if (state.defer) await new Promise<void>(resolve => { state.release = resolve; });
      return { approval_token: 'fixture-human-approved-token' };
    }
    if (path === '/api/chat/sessions') {
      if (method === 'POST') { const s = { chat_id: 'new', title: 'New desktop chat', messages: [], status: 'ACTIVE' }; state.sessions.push(s); return s; }
      return { sessions: state.sessions };
    }
    if (path === '/api/desktop/options') return { windows: [{ hwnd: 10, title: 'Owned test window' }], providers: [{ provider_id: 'fixture', model_id: 'vision', endpoint: 'http://localhost/v1' }] };
    if (path === '/api/desktop/propose' && state.deferProposal) await new Promise<void>(resolve => { state.release = resolve; });
    if (path === '/api/desktop/propose') return { ticket: 'ticket1', pending_approval_id: 'pending_appr_fixture', status: 'APPROVAL_REQUIRED' };
    if (path === '/api/desktop/start') { state.status = 'STARTING'; return { status: 'SUCCESS' }; }
    if (path === '/api/desktop/stop') { state.status = 'STOPPED'; return { status: 'STOPPED' }; }
    if (path.startsWith('/api/desktop/status?')) return { status: state.status, terminal: state.status === 'STOPPED', frame: null, events: [] };
    return {};
  };
  await page.exposeFunction('__fixtureApi', api);
  if (native) await page.addInitScript(() => {
    (window as any).__TAURI_INTERNALS__ = { invoke: async (command: string, input: any) => {
      const value = command === 'review_pending_approval'
        ? await (window as any).__fixtureApi('POST', command, JSON.stringify(input.args))
        : await (window as any).__fixtureApi(input.args.method, input.args.path, input.args.body);
      return { status: 200, body: JSON.stringify(value), headers: { 'Content-Type': 'application/json' } };
    } };
  });
  await page.route('**/api/**', async route => {
    const req = route.request(); const url = new URL(req.url());
    await route.fulfill({ json: await api(req.method(), url.pathname + url.search, req.postData()) });
  });
  await page.goto('/');
  await page.getByRole('button', { name: /Điều khiển máy tính/ }).click();
  await page.getByLabel('Nhiệm vụ máy tính').fill('Nhập bản nháp thử nghiệm');
  await page.getByLabel('Cửa sổ đích').selectOption('10');
  await page.getByLabel('Model quan sát từ Settings').selectOption('fixture');
  return state;
}

test('native chat path proposes before approval and can stop', async ({ page }) => {
  const s = await fixture(page);
  await page.getByRole('button', { name: 'Giao nhiệm vụ cho agent' }).click();
  await expect(page.getByRole('button', { name: 'Duyệt quyền một lần và bắt đầu' })).toBeVisible();
  expect(s.calls.filter(c => c.path === '/api/desktop/start')).toHaveLength(0);
  await page.getByRole('button', { name: 'Duyệt quyền một lần và bắt đầu' }).click();
  await expect.poll(() => s.calls.filter(c => c.path === '/api/desktop/start').length).toBe(1);
  expect(s.calls.find(c => c.path === '/api/desktop/start')?.body.approval_token).toBe('fixture-human-approved-token');
  await page.getByRole('button', { name: 'DỪNG', exact: true }).click();
  await expect.poll(() => s.calls.some(c => c.path === '/api/desktop/stop')).toBe(true);
});

test('browser mode cannot approve computer input', async ({ page }) => {
  const s = await fixture(page, false);
  await page.getByRole('button', { name: 'Giao nhiệm vụ cho agent' }).click();
  await page.getByRole('button', { name: 'Duyệt quyền một lần và bắt đầu' }).click();
  await expect(page.getByRole('alert')).toContainText('hộp thoại native');
  expect(s.calls.filter(c => c.path === '/api/desktop/start')).toHaveLength(0);
});

test('switching chat during delayed native approval must not start old task', async ({ page }) => {
  const s = await fixture(page); s.defer = true;
  await page.getByRole('button', { name: 'Giao nhiệm vụ cho agent' }).click();
  await page.getByRole('button', { name: 'Duyệt quyền một lần và bắt đầu' }).click();
  await expect.poll(() => !!s.release).toBe(true);
  await page.getByText('Chat B', { exact: true }).click();
  await expect.poll(() => s.calls.some(c => c.path === '/api/desktop/stop')).toBe(true);
  s.release!();
  await expect(page.getByRole('button', { name: 'Giao nhiệm vụ cho agent' })).toBeVisible();
  expect(s.calls.filter(c => c.path === '/api/desktop/start')).toHaveLength(0);
});

test('first computer task creates a chat and scopes proposal to it', async ({ page }) => {
  const s = await fixture(page, true, true);
  await page.getByRole('button', { name: 'Giao nhiệm vụ cho agent' }).click();
  await expect(page.getByRole('button', { name: 'Duyệt quyền một lần và bắt đầu' })).toBeVisible();
  expect(s.calls.find(c => c.path === '/api/desktop/propose')?.body.chat_id).toBe('new');
  expect(s.calls.filter(c => c.path === '/api/desktop/start')).toHaveLength(0);
});

test('switching chat while proposal is pending cancels the late proposal', async ({ page }) => {
  const s = await fixture(page); s.deferProposal = true;
  await page.getByRole('button', { name: 'Giao nhiệm vụ cho agent' }).click();
  await expect.poll(() => !!s.release).toBe(true);
  await page.getByText('Chat B', { exact: true }).click();
  s.release!();
  await expect.poll(() => s.calls.some(c => c.path === '/api/desktop/stop')).toBe(true);
  await expect(page.getByRole('button', { name: 'Duyệt quyền một lần và bắt đầu' })).toHaveCount(0);
});

test('background chat refresh preserves the active desktop conversation', async ({ page }) => {
  const s = await fixture(page);
  await page.getByText('Chat B', { exact: true }).click();
  await page.getByRole('button', { name: 'Giao nhiệm vụ cho agent' }).click();
  await page.getByRole('button', { name: 'Duyệt quyền một lần và bắt đầu' }).click();
  await expect.poll(() => s.calls.filter(c => c.path === '/api/desktop/start').length).toBe(1);
  // The app's real background refresh runs every 8 seconds. It must not switch
  // to the first conversation and stop a task belonging to the selected one.
  await page.waitForTimeout(8500);
  expect(s.calls.filter(c => c.path === '/api/desktop/stop')).toHaveLength(0);
});
