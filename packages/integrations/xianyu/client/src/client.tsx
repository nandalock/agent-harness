import { Plug } from 'lucide-react';

import IntegrationsPage from '@/app/dashboard/integrations/page';
import { definePlugin } from '@app/host';
import type { PluginContext } from '@app/host';

export default definePlugin({
  id: '@app/plugin-integrations',
  setup(ctx: PluginContext) {
    ctx.nav.add({
      id: 'integrations',
      label: '集成管理',
      to: '/dashboard/integrations',
      icon: <Plug size={18} />,
      order: 50,
    });
    ctx.router.add('/dashboard/integrations', IntegrationsPage, {
      shell: 'dashboard',
      layout: 'standard',
    });
  },
});
