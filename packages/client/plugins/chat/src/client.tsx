import { MessageCircle } from 'lucide-react';

import ChatPageInner from '@/app/dashboard/_components/ChatPageInner';
import { definePlugin } from '@app/host';
import type { PluginContext } from '@app/host';

export default definePlugin({
  id: '@app/plugin-chat',
  setup(ctx: PluginContext) {
    ctx.nav.add({
      id: 'chat',
      label: '聊天',
      to: '/dashboard/chat',
      icon: <MessageCircle size={18} />,
      order: 10,
    });
    // Kept mounted after leaving so an in-flight conversation is not torn down.
    ctx.router.add('/dashboard/chat', ChatPageInner, {
      shell: 'dashboard',
      layout: 'chat',
      keepAlive: true,
    });
  },
});
