import McpDetailPage from '@/app/dashboard/mcp/[id]/page';
import McpToolPage from '@/app/dashboard/mcp/tool/[name]/page';
import McpPage from '@/app/dashboard/mcp/page';
import { definePlugin } from '@app/host';
import type { PluginContext } from '@app/host';

export default definePlugin({
  id: '@app/plugin-mcp',
  setup(ctx: PluginContext) {
    ctx.router.add('/dashboard/mcp', McpPage);
    ctx.router.add('/dashboard/mcp/tool/[name]', McpToolPage);
    ctx.router.add('/dashboard/mcp/[id]', McpDetailPage);
  },
});
