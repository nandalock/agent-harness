import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';

import { build } from 'esbuild';
import type { Plugin } from 'vite';

interface DiscoveredEntry {
  id: string;
  dirName: string;
  dir: string;
  entryFile: string;
  inject: string[];
  immediately: boolean;
  plugin?: string;
}

interface PluginEntry extends DiscoveredEntry {
  rev: string;
}

interface BootEntry {
  id: string;
  url: string;
  rev: string;
  inject: string[];
  immediately: boolean;
  plugin?: string;
}

interface BootBatch {
  phase: 'application';
  url: string;
  rev: string;
  entries: string[];
}

const EXTERNALS = [
  'react',
  'react-dom',
  'react-dom/client',
  'react/jsx-runtime',
  'react/jsx-dev-runtime',
  '@app/host',
  // Shared context: Providers and page plugins must use the same QueryClient.
  '@tanstack/react-query',
];

function scanPlugins(root: string): DiscoveredEntry[] {
  const pluginsDir = path.join(root, 'plugins');
  if (!fs.existsSync(pluginsDir)) return [];

  const entries: DiscoveredEntry[] = [];
  for (const dirent of fs.readdirSync(pluginsDir, { withFileTypes: true })) {
    if (!dirent.isDirectory()) continue;
    const dir = path.join(pluginsDir, dirent.name);
    const manifestPath = path.join(dir, 'package.json');
    if (!fs.existsSync(manifestPath)) continue;

    const manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf8')) as {
      name?: string;
      dsh?: {
        plugin?: string;
        client?: { platform?: string; inject?: string[]; immediately?: boolean; plugin?: string };
      };
    };
    const client = manifest.dsh?.client;
    if (!manifest.name || !client || client.platform !== 'web') continue;

    const entryFile = path.join(dir, 'src/client.tsx');
    if (!fs.existsSync(entryFile)) {
      throw new Error(`client-modules: ${manifest.name} declares dsh.client but has no src/client.tsx`);
    }
    entries.push({
      id: manifest.name,
      dirName: dirent.name,
      dir,
      entryFile,
      inject: client.inject ?? [],
      immediately: Boolean(client.immediately),
      ...(manifest.dsh?.plugin || client.plugin
        ? { plugin: manifest.dsh?.plugin || client.plugin }
        : {}),
    });
  }

  if (entries.length === 0) {
    throw new Error('client-modules: no plugins with dsh.client platform "web" found');
  }
  return entries;
}

function sortEntries(entries: PluginEntry[]): PluginEntry[] {
  const byId = new Map(entries.map((entry) => [entry.id, entry]));
  const indegree = new Map(entries.map((entry) => [entry.id, 0]));
  const outgoing = new Map<string, string[]>(entries.map((entry) => [entry.id, []]));

  for (const entry of entries) {
    for (const dependency of entry.inject) {
      if (!byId.has(dependency)) continue;
      indegree.set(entry.id, (indegree.get(entry.id) ?? 0) + 1);
      outgoing.get(dependency)!.push(entry.id);
    }
  }

  const ready = entries.filter((entry) => indegree.get(entry.id) === 0).map((entry) => entry.id);
  const result: PluginEntry[] = [];
  const order = new Map(entries.map((entry, index) => [entry.id, index]));

  while (ready.length > 0) {
    ready.sort((a, b) => (order.get(a) ?? 0) - (order.get(b) ?? 0));
    const id = ready.shift()!;
    result.push(byId.get(id)!);
    for (const dependent of outgoing.get(id) ?? []) {
      const next = (indegree.get(dependent) ?? 0) - 1;
      indegree.set(dependent, next);
      if (next === 0) ready.push(dependent);
    }
  }

  if (result.length !== entries.length) {
    throw new Error('client-modules: dependency cycle in plugin graph');
  }
  return result;
}

function revision(entry: DiscoveredEntry): string {
  const stat = fs.statSync(entry.entryFile);
  return crypto
    .createHash('sha1')
    .update(`${entry.id}:${stat.mtimeMs}:${stat.ctimeMs}:${stat.size}`)
    .digest('hex')
    .slice(0, 10);
}

function resolveFrontendFile(base: string): string {
  const candidates = [
    base,
    `${base}.tsx`,
    `${base}.ts`,
    `${base}.jsx`,
    `${base}.js`,
    path.join(base, 'index.tsx'),
    path.join(base, 'index.ts'),
    path.join(base, 'index.js'),
  ];
  for (const candidate of candidates) {
    if (fs.existsSync(candidate) && fs.statSync(candidate).isFile()) return candidate;
  }
  return base;
}

async function buildPlugin(entry: PluginEntry, root: string): Promise<string> {
  const legacy = path.resolve(root, 'legacy');
  const result = await build({
    entryPoints: [entry.entryFile],
    absWorkingDir: root,
    outfile: path.join(entry.dir, 'client.js'),
    bundle: true,
    write: false,
    format: 'cjs',
    platform: 'browser',
    target: ['es2020'],
    jsx: 'automatic',
    external: EXTERNALS,
    define: {
      'process.env.NEXT_PUBLIC_API_URL': JSON.stringify(
        process.env.VITE_PUBLIC_BACKEND_URL ||
          process.env.BACKEND_URL ||
          process.env.VITE_BACKEND_URL ||
          'http://127.0.0.1:8000',
      ),
      'process.env.NODE_ENV': JSON.stringify('production'),
    },
    alias: {
      'next/navigation': path.resolve(root, 'shell/shims/next-navigation.tsx'),
      'next/link': path.resolve(root, 'shell/shims/next-link.tsx'),
      'next/dynamic': path.resolve(root, 'shell/shims/next-dynamic.tsx'),
    },
    plugins: [
      {
        name: 'frontend-alias',
        setup(pluginBuild) {
          pluginBuild.onResolve({ filter: /^@\// }, (args) => ({
            path: resolveFrontendFile(path.join(legacy, args.path.slice(2))),
          }));
        },
      },
    ],
    logLevel: 'silent',
    loader: {
      '.tsx': 'tsx',
      '.ts': 'ts',
      '.css': 'css',
      '.svg': 'file',
      '.png': 'file',
      '.jpg': 'file',
      '.jpeg': 'file',
      '.gif': 'file',
      '.webp': 'file',
    },
    sourcemap: false,
  });

  const files = result.outputFiles ?? [];
  const code = files.find((file) => file.path.endsWith('.js'))?.text;
  if (!code) throw new Error(`client-modules: ${entry.id} produced no JavaScript bundle`);
  const css = files
    .filter((file) => file.path.endsWith('.css'))
    .map((file) => file.text)
    .join('\n');
  const cssInjection = css
    ? `(function(){var style=document.createElement('style');style.setAttribute('data-plugin',${JSON.stringify(
        entry.id,
      )});style.textContent=${JSON.stringify(css)};document.head.appendChild(style);})();\n`
    : '';

  return (
    cssInjection +
    `window.__ModuleLoader__.load({\n` +
    `  id: ${JSON.stringify(entry.id)},\n` +
    `  factory: function () {\n` +
    `    var module = { exports: {} };\n` +
    `    var exports = module.exports;\n` +
    `    var require = window.__ModuleLoader__.require;\n` +
    `${code}\n` +
    `    return module.exports;\n` +
    `  }\n` +
    `});\n`
  );
}

function composeGraph(entries: PluginEntry[], rev: string): { entries: BootEntry[]; batches: BootBatch[] } {
  const ordered = sortEntries(entries);
  return {
    entries: ordered.map((entry) => ({
      id: entry.id,
      url: `/plugins/${entry.dirName}/client.js?rev=${entry.rev}`,
      rev: entry.rev,
      inject: entry.inject,
      immediately: entry.immediately,
      ...(entry.plugin ? { plugin: entry.plugin } : {}),
    })),
    batches: [
      {
        phase: 'application',
        url: `/plugins/??${ordered.map((entry) => entry.dirName).join(',')}&rev=${rev}`,
        rev,
        entries: ordered.map((entry) => entry.id),
      },
    ],
  };
}

function pluginMiddleware(root: string, entries: PluginEntry[]) {
  const codeCache = new Map<string, string>();

  async function buildCached(entry: PluginEntry): Promise<string> {
    const key = `${entry.id}:${entry.rev}`;
    const cached = codeCache.get(key);
    if (cached) return cached;
    const code = await buildPlugin(entry, root);
    codeCache.set(key, code);
    return code;
  }

  return async (req: any, res: any, next: () => void): Promise<void> => {
    const url = String(req.url ?? '');
    const batch = /^\/plugins\/\?\?([^&]+)/.exec(url);
    if (batch) {
      const names = batch[1].split(',').filter(Boolean);
      const selected = names
        .map((name) => entries.find((entry) => entry.dirName === name))
        .filter((entry): entry is PluginEntry => Boolean(entry));
      try {
        const bodies = await Promise.all(selected.map((entry) => buildCached(entry)));
        res.statusCode = 200;
        res.setHeader('Content-Type', 'application/javascript; charset=utf-8');
        res.setHeader('Cache-Control', 'no-store');
        res.end(bodies.join('\n'));
      } catch (error) {
        res.statusCode = 500;
        res.setHeader('Content-Type', 'text/plain; charset=utf-8');
        res.end(error instanceof Error ? error.stack ?? error.message : String(error));
      }
      return;
    }

    const single = /^\/plugins\/([^/?]+)\/client\.js/.exec(url);
    if (!single) {
      next();
      return;
    }
    const entry = entries.find((candidate) => candidate.dirName === single[1]);
    if (!entry) {
      res.statusCode = 404;
      res.end('plugin not found');
      return;
    }
    try {
      const code = await buildCached(entry);
      res.statusCode = 200;
      res.setHeader('Content-Type', 'application/javascript; charset=utf-8');
      res.setHeader('Cache-Control', 'no-store');
      res.end(code);
    } catch (error) {
      res.statusCode = 500;
      res.setHeader('Content-Type', 'text/plain; charset=utf-8');
      res.end(error instanceof Error ? error.stack ?? error.message : String(error));
    }
  };
}

export function clientModules(options: { root?: string } = {}): Plugin {
  const root = path.resolve(options.root ?? process.cwd());
  let isBuild = false;
  let entries: PluginEntry[] = [];

  return {
    name: 'agent-platform:client-modules',
    enforce: 'pre',
    config(_config, env) {
      isBuild = env.command === 'build';
    },
    buildStart() {
      const rev = isBuild ? 'build' : Date.now().toString(36);
      entries = scanPlugins(root)
        .map((entry) => ({ ...entry, rev: isBuild ? revision(entry) : rev }))
        .sort((a, b) => a.id.localeCompare(b.id));
    },
    configureServer(server) {
      server.middlewares.use((req, res, next) => {
        void pluginMiddleware(root, entries)(req, res, next);
      });
    },
    transformIndexHtml: {
      order: 'pre',
      handler(html) {
        const rev = isBuild ? 'build' : Date.now().toString(36);
        const graph = composeGraph(entries, rev);
        const payload = JSON.stringify(graph).replace(/</g, '\\u003c');
        return html.replace('</head>', `<script>window.__DSH_BOOT__=${payload};</script></head>`);
      },
    },
    async writeBundle(options) {
      const outDir = path.resolve(root, options.dir ?? 'dist');
      for (const entry of entries) {
        const code = await buildPlugin(entry, root);
        const target = path.join(outDir, 'plugins', entry.dirName, 'client.js');
        fs.mkdirSync(path.dirname(target), { recursive: true });
        fs.writeFileSync(target, code, 'utf8');
      }
    },
  };
}
