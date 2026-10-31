import AgentDetailPage from '@/app/agents/[id]/page';
import RouterDetailPage from '@/app/agents/router/[key]/page';
import AgentsPage from '@/app/dashboard/agents/page';
import { definePlugin } from '@app/host';
import type { PluginContext } from '@app/host';

export default definePlugin({
  id: '@app/plugin-agents',
  setup(ctx: PluginContext) {
    ctx.router.add('/dashboard/agents', AgentsPage);
    ctx.router.add('/agents/router/[key]', RouterDetailPage);
    ctx.router.add('/agents/[id]', AgentDetailPage);
  },
});
