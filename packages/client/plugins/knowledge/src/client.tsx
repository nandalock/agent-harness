import { BookOpen } from 'lucide-react';

import KnowledgePage from '@/app/dashboard/knowledge/page';
import { definePlugin } from '@app/host';
import type { PluginContext } from '@app/host';

export default definePlugin({
  id: '@app/plugin-knowledge',
  setup(ctx: PluginContext) {
    ctx.nav.add({
      id: 'knowledge',
      label: '知识库',
      to: '/dashboard/knowledge',
      icon: <BookOpen size={18} />,
      order: 20,
    });
    ctx.router.add('/dashboard/knowledge', KnowledgePage, {
      shell: 'dashboard',
      layout: 'standard',
    });
  },
});
