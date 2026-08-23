import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

const backendHost = process.env.APP_BACKEND_HOST_DEV || '127.0.0.1';
const backendPort = process.env.APP_BACKEND_PORT_DEV || '8765';
const defaultTarget = `http://${backendHost}:${backendPort}`;

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  clearScreen: false,
  server: {
    port: 3000,
    strictPort: true,
    proxy: {
      '/api': {
        target: process.env.APP_BACKEND_TARGET || defaultTarget,
        changeOrigin: true,
        configure: (proxy, _options) => {
          proxy.on('proxyReq', (proxyReq, req, res) => {
            const url = req.url || '';
            // Security Invariant: Vite dev proxy blocks consequential approval decisions
            if (url.includes('/approve') || url.includes('/reject') || url === '/api/approvals/create') {
              if (res && typeof (res as any).writeHead === 'function') {
                (res as any).writeHead(403, { 'Content-Type': 'application/json' });
                (res as any).end(
                  JSON.stringify({
                    error: 'APPROVAL_DECISION_FORBIDDEN_ON_DEV_PROXY',
                    message:
                      'Consequential human approval decisions require production Tauri native desktop confirmation.',
                  })
                );
                return;
              }
            }

            const devBearer = process.env.APP_BACKEND_BEARER_DEV;
            if (devBearer) {
              proxyReq.setHeader('Authorization', `Bearer ${devBearer}`);
            }
          });
        },
      },
    },
  },
  build: {
    target: ['es2021', 'chrome100', 'safari13'],
    minify: !process.env.TAURI_DEBUG ? 'esbuild' : false,
    sourcemap: !!process.env.TAURI_DEBUG,
  },
});
