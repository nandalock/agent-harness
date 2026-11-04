import React from 'react';

type Loader = () => Promise<unknown>;

interface DynamicOptions {
  ssr?: boolean;
  loading?: () => React.ReactNode;
}

/**
 * Minimal `next/dynamic` replacement. The migrated pages only use the
 * `dynamic(loader, { ssr:false })` form with a default-exported component.
 */
export default function dynamic(
  loader: Loader,
  options: DynamicOptions = {},
): React.ComponentType<any> {
  const Lazy = React.lazy(loader as () => Promise<{ default: React.ComponentType<any> }>);

  function DynamicComponent(props: Record<string, unknown>) {
    return (
      <React.Suspense fallback={options.loading ? options.loading() : null}>
        <Lazy {...props} />
      </React.Suspense>
    );
  }

  return DynamicComponent;
}
