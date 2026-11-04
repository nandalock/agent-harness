'use client';

import {
  Children, createContext, forwardRef, isValidElement, useContext, useImperativeHandle,
  useLayoutEffect, useRef, useState, type CSSProperties, type ReactNode,
} from 'react';
import { useVirtualizer } from '@tanstack/react-virtual';

const RowState = createContext<Map<string, boolean> | null>(null);

// The transcript owns disclosure state, so leaving the virtual window doesn't
// forget which thinking/tool panels the reader opened.
export function useRowDisclosure(key: string) {
  const saved = useContext(RowState);
  const [open, setOpen] = useState(() => saved?.get(key) ?? false);
  function update(value: boolean | ((previous: boolean) => boolean)) {
    setOpen(previous => {
      const next = typeof value === 'function' ? value(previous) : value;
      saved?.set(key, next);
      return next;
    });
  }
  return [open, update] as const;
}

export interface TranscriptHandle { scrollToEnd(): void }
interface Props {
  children: ReactNode;
  style?: CSSProperties;
  loading?: boolean;
  hasMore?: boolean;
  loadingOlder?: boolean;
  error?: string;
  onLoadOlder?: () => void;
}

export default forwardRef<TranscriptHandle, Props>(function VirtualTranscript({
  children, style, loading, hasMore, loadingOlder, error, onLoadOlder,
}, ref) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const initialPositioned = useRef(false);
  const disclosures = useRef(new Map<string, Map<string, boolean>>());
  const [following, setFollowing] = useState(true);
  const rows = Children.toArray(children);
  const keyOf = (index: number) => {
    const row = rows[index];
    return isValidElement(row) ? String(row.key) : String(index);
  };
  const virtualizer = useVirtualizer({
    count: rows.length,
    getScrollElement: () => scrollRef.current,
    getItemKey: keyOf,
    estimateSize: () => 160,
    overscan: 4,
    paddingStart: 48,
    paddingEnd: 8,
    anchorTo: 'end',
    followOnAppend: 'auto',
    scrollEndThreshold: 48,
  });
  useImperativeHandle(ref, () => ({ scrollToEnd() { virtualizer.scrollToEnd(); setFollowing(true); } }));
  useLayoutEffect(() => {
    if (!loading && rows.length && !initialPositioned.current) {
      initialPositioned.current = true;
      virtualizer.scrollToEnd();
    }
  }, [loading, rows.length, virtualizer]);
  // Reflow invalidates offscreen heights too. Refill mounted measurements in
  // the same callback: their ResizeObserver may already have reported the new
  // size before this viewport observer clears the cache, with no further row
  // resize to repair the now-estimated positions.
  const previousWidth = useRef(0);
  useLayoutEffect(() => {
    const element = scrollRef.current;
    if (!element) return;
    const observer = new ResizeObserver(entries => {
      const width = entries[0].contentRect.width;
      if (width <= 0) return;
      if (previousWidth.current && Math.abs(width - previousWidth.current) > 1) {
        // Read before invalidation: resizeItem can synchronously change the
        // virtual window and detach some of these elements while notifying.
        const sizes = Array.from(element.querySelectorAll<HTMLElement>('[data-message-key]'),
          row => [Number(row.dataset.index), row.offsetHeight] as const);
        virtualizer.measure();
        sizes.forEach(([index, height]) => virtualizer.resizeItem(index, height));
      }
      previousWidth.current = width;
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, [virtualizer]);

  const items = virtualizer.getVirtualItems();
  const first = items[0];
  const last = items[items.length - 1];

  return (
    <div style={{ flex: 1, minHeight: 0, position: 'relative', display: 'flex' }}>
      <div ref={scrollRef} data-testid="virtual-transcript"
        onScroll={() => {
          const el = scrollRef.current!;
          setFollowing(el.scrollHeight - el.scrollTop - el.clientHeight < 48);
        }}
        style={{ ...style, flex: 1, minHeight: 0, overflowY: 'auto', overflowAnchor: 'none' }}>
        {/* Keep mounted messages in normal flow. Only the unmounted regions
            use estimated space, so a growing/remeasured answer cannot overlap
            the next message while measurements are catching up. */}
        <div style={{ position: 'relative', width: '100%',
          paddingTop: first?.start ?? 0,
          paddingBottom: Math.max(0, virtualizer.getTotalSize() - (last?.end ?? 0)) }}>
          <div style={{ position: 'absolute', top: 0, height: 40, width: '100%', textAlign: 'center', fontSize: 12 }}>
            {loading ? '加载历史消息…' : (hasMore || error) ? (
              <button type="button" disabled={loadingOlder} onClick={onLoadOlder}
                style={{ color: 'inherit', background: 'transparent', border: 0, cursor: 'pointer', padding: 8 }}>
                {loadingOlder ? '加载中…' : error ? `${error} · 重试` : '加载更早的消息'}
              </button>
            ) : null}
          </div>
          {items.map(item => {
            const key = String(item.key);
            let state = disclosures.current.get(key);
            if (!state) { state = new Map(); disclosures.current.set(key, state); }
            return (
              <div key={key} ref={virtualizer.measureElement} data-index={item.index} data-message-key={key}
                style={{ width: '100%', display: 'flow-root' }}>
                <RowState.Provider value={state}>{rows[item.index]}</RowState.Provider>
              </div>
            );
          })}
        </div>
      </div>
      {!following && rows.length > 0 && (
        <button type="button" onClick={() => virtualizer.scrollToEnd()} aria-label="回到最新消息"
          style={{ position: 'absolute', bottom: 12, right: 24, borderRadius: 16, padding: '6px 12px',
            background: '#2a2a2a', color: '#eee', border: '1px solid #555', cursor: 'pointer' }}>↓ 最新消息</button>
      )}
    </div>
  );
});
