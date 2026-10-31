import React, { useState } from 'react';
import { createRoot } from 'react-dom/client';
import VirtualTranscript from '../../legacy/components/VirtualTranscript';
import AgentTurn from '../../legacy/app/dashboard/workspace/_components/AgentTurn';
import '../../legacy/app/dashboard/workspace/workspace.css';

const answer = `## 文件夹检查结果

工作目录中的文件已经逐项检查。这里有一段较长的中文说明，用来验证侧边栏打开、关闭和浏览器宽度变化后的实际消息高度。`.repeat(4) + `

| 工具 | 用途 | 状态 |
| --- | --- | --- |
| powershell | Windows 文件与进程操作 | 可用 |
| python | 读取、分析并生成文件 | 可用 |

\`\`\`python
from pathlib import Path
print(list(Path('.').iterdir()))
\`\`\`
`;

function Fixture() {
  const [width, setWidth] = useState(980);
  const [count, setCount] = useState(() => Number(new URLSearchParams(location.search).get('count')) || 6);
  const [start, setStart] = useState(0);
  const [extra, setExtra] = useState('');
  return (
    <div className="ws-root" style={{ height: '100vh', display: 'flex', flexDirection: 'column' }}>
      <div style={{ display: 'flex', gap: 8 }}>
        <button onClick={() => setWidth(value => value === 980 ? 600 : 980)}>切换侧栏</button>
        <button onClick={() => setCount(value => value + 2)}>追加消息</button>
        <button onClick={() => { setStart(value => value - 20); setCount(value => value + 20); }}>加载历史</button>
        <button onClick={() => setExtra(value => value + '\n\n' + answer)}>流式追加正文</button>
      </div>
      <div data-testid="chat-column" style={{ width, maxWidth: '100%', flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column' }}>
        <VirtualTranscript style={{ padding: '16px' }}>
          {Array.from({ length: count }, (_, index) => (start + index) % 2 === 0 ? (
            <div key={`user:${start + index}`} data-row-id={start + index} style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 20 }}>
              <div style={{ padding: 16, borderRadius: 20, background: '#ddd' }}>工作区里现在有什么？消息 {start + index}</div>
            </div>
          ) : (
            <div key={`agent:${start + index}`} data-row-id={start + index} style={{ marginBottom: 20 }}>
              <AgentTurn content={answer + (index === count - 1 ? extra : '')} legacyThinking={`检查目录，确认真实输出。${start + index}`} time="19:27" />
            </div>
          ))}
        </VirtualTranscript>
      </div>
    </div>
  );
}

createRoot(document.getElementById('root')!).render(<React.StrictMode><Fixture /></React.StrictMode>);
