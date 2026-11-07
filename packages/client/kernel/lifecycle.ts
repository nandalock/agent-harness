/** Plugin-owned registrations. Every effect is undone when its plugin unloads. */

export type Disposer = () => void;

const owned = new Map<string, Disposer[]>();

/**
 * Adopt one registration under `pluginId`.
 * Returns a scoped disposer that removes exactly this effect.
 */
export function trackPluginEffect(pluginId: string, dispose: Disposer): Disposer {
  const effects = owned.get(pluginId) ?? [];
  effects.push(dispose);
  owned.set(pluginId, effects);

  return () => {
    const current = owned.get(pluginId);
    if (!current) return;
    const index = current.indexOf(dispose);
    if (index < 0) return;
    current.splice(index, 1);
    if (current.length === 0) owned.delete(pluginId);
    dispose();
  };
}

/** Undo every effect owned by one plugin, newest first. Failures are isolated. */
export function disposePlugin(pluginId: string): void {
  const effects = owned.get(pluginId);
  if (!effects) return;
  owned.delete(pluginId);
  for (const dispose of [...effects].reverse()) {
    try {
      dispose();
    } catch (error) {
      console.error(`client-modules: ${pluginId} cleanup failed`, error);
    }
  }
}

/** Undo every plugin effect. Used by tests and full reloads. */
export function disposeAllPlugins(): void {
  for (const pluginId of [...owned.keys()]) disposePlugin(pluginId);
}

export function pluginEffectCount(pluginId: string): number {
  return owned.get(pluginId)?.length ?? 0;
}
