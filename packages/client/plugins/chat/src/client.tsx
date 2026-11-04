import ChatPage from '@/app/dashboard/chat/page';
import { definePlugin } from '@app/host';
import type { PluginContext } from '@app/host';

export default definePlugin({
  id: '@app/plugin-chat',
  setup(ctx: PluginContext) {
    ctx.router.add('/dashboard/chat', ChatPage);
  },
});
