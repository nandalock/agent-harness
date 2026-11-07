import { Wrench } from 'lucide-react';

import McpDetailPage from '@/app/dashboard/mcp/[id]/page';
import McpToolPage from '@/app/dashboard/mcp/tool/[name]/page';
import McpPage from '@/app/dashboard/mcp/page';
import { definePlugin } from '@app/host';
import type { PluginContext } from '@app/host';

export default definePlugin({
  id: '@app/plugin-mcp',
  setup(ctx: PluginContext) {
    ctx.nav.add({
      id: 'mcp',
      label: '工具',
      to: '/dashboard/mcp',
      icon: <Wrench size={18} />,
      order: 40,
    });
    ctx.router.add('/dashboard/mcp', McpPage, {
      shell: 'dashboard',
      layout: 'flush',
    });
    ctx.router.add('/dashboard/mcp/tool/[name]', McpToolPage, {
      shell: 'dashboard',
      layout: 'standard',
    });
    ctx.router.add('/dashboard/mcp/[id]', McpDetailPage, {
      shell: 'dashboard',
      layout: 'standard',
    });
  },
});
