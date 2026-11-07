import { Bot } from 'lucide-react';

import AgentDetailPage from '@/app/agents/[id]/page';
import RouterDetailPage from '@/app/agents/router/[key]/page';
import AgentsPage from '@/app/dashboard/agents/page';
import { definePlugin } from '@app/host';
import type { PluginContext } from '@app/host';

export default definePlugin({
  id: '@app/plugin-agents',
  setup(ctx: PluginContext) {
    ctx.nav.add({
      id: 'agents',
      label: 'Agent',
      to: '/dashboard/agents',
      icon: <Bot size={18} />,
      order: 30,
    });
    ctx.router.add('/dashboard/agents', AgentsPage, {
      shell: 'dashboard',
      layout: 'standard',
    });
    ctx.router.add('/agents/router/[key]', RouterDetailPage, { shell: 'agents' });
    ctx.router.add('/agents/[id]', AgentDetailPage, { shell: 'agents' });
  },
});
