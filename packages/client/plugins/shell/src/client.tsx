import React from 'react';

import AgentsLayout from '@/app/agents/layout';
import DashboardLayout from '@/app/dashboard/layout';
import Providers from '@/app/providers';
import { definePlugin, navigate, RouterOutlet, useRoute } from '@app/host';
import type { PluginContext } from '@app/host';

function NotFound() {
  return (
    <div style={{ padding: 24, fontFamily: 'system-ui, sans-serif' }}>
      <h1 style={{ fontSize: 20, margin: 0 }}>404</h1>
      <p style={{ color: '#86909C', fontSize: 14 }}>没有找到这个页面。</p>
    </div>
  );
}

function Root() {
  const path = useRoute();

  React.useEffect(() => {
    if (path === '/' || path === '/login') {
      navigate('/dashboard');
    }
  }, [path]);

  if (path === '/' || path === '/login') return null;
  if (path.startsWith('/agents/')) {
    return (
      <AgentsLayout>
        <RouterOutlet />
      </AgentsLayout>
    );
  }
  if (path.startsWith('/dashboard')) {
    return (
      <DashboardLayout>
        <RouterOutlet />
      </DashboardLayout>
    );
  }
  return <RouterOutlet />;
}

export default definePlugin({
  id: '@app/plugin-shell',
  setup(ctx: PluginContext) {
    ctx.router.add('*', NotFound);
    ctx.slots.register('root', 'shell', () => (
      <Providers>
        <Root />
      </Providers>
    ));
  },
});
