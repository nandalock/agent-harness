'use client';

import { useMemo, useRef } from 'react';
import { useVirtualizer } from '@tanstack/react-virtual';

const BLOCK_LINES = 80;
const LINE_HEIGHT = 19;

// Plain text blocks keep multi-line source exact; highlighting separate virtual
// chunks could give incorrect colours when a string/comment crosses a boundary.
export default function VirtualFileText({ text }: { text: string }) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const lines = useMemo(() => text.split('\n'), [text]);
  const virtualizer = useVirtualizer({
    count: Math.ceil(lines.length / BLOCK_LINES),
    getScrollElement: () => scrollRef.current,
    estimateSize: index => Math.min(BLOCK_LINES, lines.length - index * BLOCK_LINES) * LINE_HEIGHT,
    overscan: 1,
  });
  return (
    <div ref={scrollRef} data-testid="virtual-file" style={{ height: '100%', overflow: 'auto', padding: 16, boxSizing: 'border-box' }}>
      <div style={{ height: virtualizer.getTotalSize(), position: 'relative', minWidth: '100%', width: 'max-content' }}>
        {virtualizer.getVirtualItems().map(block => (
          <pre key={block.key} data-file-block={block.index} style={{ position: 'absolute', top: 0,
            transform: `translateY(${block.start}px)`, margin: 0, fontSize: 12, lineHeight: `${LINE_HEIGHT}px`,
            fontFamily: 'ui-monospace, SFMono-Regular, Consolas, monospace', whiteSpace: 'pre' }}>
            {lines.slice(block.index * BLOCK_LINES, (block.index + 1) * BLOCK_LINES).join('\n')}
          </pre>
        ))}
      </div>
    </div>
  );
}
