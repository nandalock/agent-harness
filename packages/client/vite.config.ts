import path from 'node:path';
import { fileURLToPath } from 'node:url';

import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

import { clientModules } from './vite-plugin-client-modules';

const root = path.dirname(fileURLToPath(import.meta.url));
const legacy = path.resolve(root, 'legacy');
const backend = process.env.BACKEND_URL || process.env.VITE_BACKEND_URL || 'http://127.0.0.1:8000';
const publicBackend = process.env.VITE_PUBLIC_BACKEND_URL || backend;

const proxy = {
  '/api/ws': {
    target: backend.replace(/^http/, 'ws'),
    ws: true,
  },
  '/api': {
    target: backend,
    changeOrigin: true,
  },
};

export default defineConfig({
  plugins: [react(), clientModules()],
  resolve: {
    dedupe: ['react', 'react-dom'],
    alias: [
      { find: '@app/host', replacement: path.resolve(root, 'shell/host-api.ts') },
      { find: 'next/navigation', replacement: path.resolve(root, 'shell/shims/next-navigation.tsx') },
      { find: 'next/link', replacement: path.resolve(root, 'shell/shims/next-link.tsx') },
      { find: 'next/dynamic', replacement: path.resolve(root, 'shell/shims/next-dynamic.tsx') },
      { find: /^@\//, replacement: `${legacy}/` },
    ],
  },
  define: {
    'process.env.NEXT_PUBLIC_API_URL': JSON.stringify(publicBackend),
  },
  server: {
    port: 4100,
    strictPort: true,
    proxy,
    fs: {
      allow: [path.resolve(root, '../..')],
    },
  },
  preview: {
    port: 4100,
    strictPort: true,
    proxy,
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
  },
});
