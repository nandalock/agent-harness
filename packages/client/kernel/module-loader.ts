import type { WebBootEntry } from './types';

type ModuleFactory = (require: (id: string) => unknown) => unknown;

const platform = new Map<string, unknown>();
const factories = new Map<string, ModuleFactory>();
const cache = new Map<string, unknown>();

export function installPlatformModules(modules: Record<string, unknown>): void {
  for (const [id, value] of Object.entries(modules)) {
    platform.set(id, value);
  }
}

export function installGlobalFacade(): void {
  (window as any).__ModuleLoader__ = {
    load: ({ id, factory }: { id: string; factory: ModuleFactory }) => {
      factories.set(id, factory);
    },
    require: requireModule,
  };
}

export function registerModule(id: string, factory: ModuleFactory): void {
  factories.set(id, factory);
}

export function requireModule(id: string): unknown {
  if (platform.has(id)) return platform.get(id);
  if (cache.has(id)) return cache.get(id);
  const factory = factories.get(id);
  if (!factory) {
    throw new Error(`client-modules: module ${JSON.stringify(id)} is not loaded`);
  }
  const exports = factory(requireModule);
  cache.set(id, exports);
  return exports;
}

export function materialize(id: string): any {
  const exports = requireModule(id) as any;
  return exports?.default ?? exports;
}

function loadScript(url: string): Promise<void> {
  return new Promise((resolve, reject) => {
    const script = document.createElement('script');
    script.src = url;
    script.async = true;
    script.onload = () => resolve();
    script.onerror = () => reject(new Error(`client-modules: failed to load ${url}`));
    document.head.appendChild(script);
  });
}

const loading = new Map<string, Promise<void>>();

export async function loadEntry(entry: WebBootEntry): Promise<void> {
  if (platform.has(entry.id) || factories.has(entry.id) || cache.has(entry.id)) return;
  const existing = loading.get(entry.id);
  if (existing) return existing;
  const task = (async () => {
    await loadScript(entry.url);
    if (!factories.has(entry.id)) {
      throw new Error(
        `client-modules: ${entry.url} loaded without registering ${JSON.stringify(entry.id)}`,
      );
    }
  })();
  loading.set(entry.id, task);
  try {
    await task;
  } finally {
    loading.delete(entry.id);
  }
}

export function loadedModuleIds(): string[] {
  return [...factories.keys()];
}
