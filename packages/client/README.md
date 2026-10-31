# Web plugin shell (`packages/client`)

DSH-style browser-side plugin shell. All existing Next.js pages are now served through this
shell as independent client plugins. Their source lives in `legacy/`; the root
`frontend/` directory has been removed.

Reference implementation: `D:\jk\Code\github\deepseek-harness` (MIT), especially
`packages/client/modules`, `packages/client/web`, `packages/client/ui-slots`,
`packages/host/webserver`.

## Run

```bash
# repo root: backend + web plugin shell (dev)
python minidsh.py web

# repo root: build + serve the shell (production preview)
python minidsh.py web --prod

# standalone shell development
cd packages/client
npm install
npm run dev          # http://localhost:4100, /api -> 127.0.0.1:8000
```

The backend alone:

```bash
python minidsh.py dev --backend-only
```

Production build/preview for the shell:

```bash
python minidsh.py build          # runs packages/client: tsc --noEmit && vite build
python minidsh.py start          # serves packages/client/dist
```

## Frontend manifest

`package.json` declares the package as a runnable frontend, analogous to DSH's
`dsh.client` / `dsh.bundle` package declarations:

```json
"dsh": {
  "frontend": {
    "install": "npm ci --no-audit --no-fund",
    "dev": "npm run dev -- --host 127.0.0.1 --port {port}",
    "build": "npm run build",
    "start": "npm run preview -- --host 127.0.0.1 --port {port}",
    "dist": "dist",
    "requiresNode": true
  }
}
```

`minidsh` scans `packages/*/package.json` for this field. Select another package with
`python minidsh.py web --profile <dir-or-package-name>`, or point outside the repo with
`python minidsh.py web --dir D:/jk/Code/web2`.

## How it works

```
index.html
  └─ window.__DSH_BOOT__          composed by vite-plugin-client-modules.ts
       entries[]                  { id, url, rev, inject, immediately }
       batches[]                  combo script descriptors
  └─ shell/main.tsx
       └─ kernel/boot.ts          install platform modules, load bundles, run setup()
            ├─ kernel/module-loader.ts   lazy CommonJS table + window.__ModuleLoader__
            ├─ kernel/slots.tsx          typed slot registry + <Slot name="...">
            ├─ kernel/router.tsx         history router, dynamic params, <RouterOutlet>
            └─ shell/host-api.ts           the `@app/host` platform module
```

Each plugin is a package under `plugins/<name>/`:

```json
{
  "name": "@app/plugin-example",
  "private": true,
  "version": "0.1.0",
  "dsh": {
    "client": {
      "platform": "web",
      "inject": ["@app/plugin-shell"],
      "immediately": true
    }
  }
}
```

```tsx
// plugins/example/src/client.tsx
import { definePlugin } from '@app/host';
import type { PluginContext } from '@app/host';

export default definePlugin({
  id: '@app/plugin-example',
  setup(ctx: PluginContext) {
    ctx.router.add('/dashboard/example', ExamplePage);
    // or: ctx.slots.register('root', 'example', ExampleWidget);
  },
});
```

The Vite plugin scans `plugins/*/package.json`, builds each `src/client.tsx` with esbuild,
serves it as `/plugins/<dir>/client.js` (cached per dev-server session), and injects the boot
graph. Bundles are lazy CJS: loading a script only registers a factory; the module body runs
when materialized. CSS imported by a page is inlined as a `<style data-plugin="...">` at
bundle load.

Platform modules available to plugin bundles (esbuild externals):

- `react`, `react-dom`, `react-dom/client`, `react/jsx-runtime`, `react/jsx-dev-runtime`
- `@tanstack/react-query` — shared so `Providers` and page plugins use one QueryClient
- `@app/host` — `definePlugin`, `Slot`, `registerSlot`, `RouterOutlet`, `useRoute`,
  `useParams`, `usePathname`, `useSearchParams`, `useRouter`, `navigate`, `registerRoute`,
  `api`, auth helpers, `T`, `S`, `React`.

## Page migration

`@/` resolves to the legacy frontend source, and Next.js APIs are shimmed:

| Next.js import | Shim | Purpose |
| --- | --- | --- |
| `next/navigation` | `shell/shims/next-navigation.tsx` | delegates to the shared `@app/host` router |
| `next/link` | `shell/shims/next-link.tsx` | SPA navigation with modifier-key handling |
| `next/dynamic` | `shell/shims/next-dynamic.tsx` | `React.lazy` + `Suspense` |

Migrated routes:

| Plugin | Routes |
| --- | --- |
| `shell` | root layout, dashboard/agents layouts, `/` and `/login` redirect to `/dashboard`, 404 |
| `dashboard` | `/dashboard` |
| `chat` | `/dashboard/chat` |
| `agents` | `/dashboard/agents`, `/agents/[id]`, `/agents/router/[key]` |
| `knowledge` | `/dashboard/knowledge` |
| `integrations` | `/dashboard/integrations` |
| `mcp` | `/dashboard/mcp`, `/dashboard/mcp/[id]`, `/dashboard/mcp/tool/[name]` |
| `memory` | `/dashboard/memory`, `/dashboard/memory/users`, `/dashboard/memory/users/[user_id]`, `/dashboard/memory/debug` |
| `workflow` | `/dashboard/workflow`, `/dashboard/workflow/list`, `/dashboard/workflow/[id]` |
| `workspace` | `/dashboard/workspace` |

The shell reuses the existing `legacy/app/dashboard/layout.tsx` and
`legacy/app/agents/layout.tsx`, so the sidebar, chat keep-alive, full-bleed pages, and
agent navigation behave the same as the old Next.js app.

## No login

- The shell has no login page, logout button, cookie, or route guard.
- Opening `/` (or `/login`) redirects directly to `/dashboard`.
- API calls use the absolute backend URL from `BACKEND_URL` (default
  `http://127.0.0.1:8000`), with CORS allowing the shell port.
- The backend still exposes `POST /api/auth/login` as an optional API, but the frontend
  does not call it.

## Limitations

- Page components live in `legacy/` and still use a few Next.js APIs through shims;
  they can be refactored into normal React components incrementally.
- Plugin bundles are cached per dev-server session. Editing plugin/legacy source requires
  restarting `npm run dev` (or `python minidsh.py web`); Vite HMR only covers the shell itself.
- CSS imports are inlined; CSS Modules, image/font assets, and HMR for plugin bundles are not
  implemented yet.
- `legacy/app/dashboard/agents/page.tsx` uses `<style jsx global>`; it renders correctly
  but emits React warnings because styled-jsx is not present.
- Docker Compose builds this shell with `packages/client/Dockerfile` and serves it via
  `vite preview`; Vite preview is a local production preview, not a hardened public server.
