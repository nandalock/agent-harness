import { LayoutGrid } from 'lucide-react';

import WorkspacePage from '@/app/dashboard/workspace/page';
import { definePlugin } from '@app/host';
import type { PluginContext } from '@app/host';

export default definePlugin({
  id: '@app/plugin-workspace',
  setup(ctx: PluginContext) {
    ctx.nav.add({
      id: 'workspace',
      label: '工作区',
      to: '/dashboard/workspace',
      icon: <LayoutGrid size={18} />,
      order: 80,
    });
    // The workspace owns all three panes and its own scrolling.
    ctx.router.add('/dashboard/workspace', WorkspacePage, {
      shell: 'dashboard',
      layout: 'immersive',
    });
  },
});
