import { boot } from '../kernel/boot';

boot().catch((error: unknown) => {
  console.error(error);
  const root = document.getElementById('root');
  if (!root) return;
  const pre = document.createElement('pre');
  pre.style.padding = '24px';
  pre.style.color = '#F53F3F';
  pre.style.whiteSpace = 'pre-wrap';
  pre.textContent = `前端插件壳启动失败\n\n${error instanceof Error ? error.stack ?? error.message : String(error)}`;
  root.replaceChildren(pre);
});
