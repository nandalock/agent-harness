'use client';

// DirectoryBrowser — DSH browse 后端对应的页面内目录选择器。
//
// 远程浏览器 / Docker 里没有宿主桌面，不能弹系统对话框；目录必须由**后端**
// 读文件系统、一層一層返回绝对路径。这里只做展示与导航，路径从不自己拼。
// 本地后端列宿主目录；Docker 后端只列挂载根，返回的 folder 值交给
// POST /sessions 解析。

import { useCallback, useEffect, useRef, useState } from 'react';
import { ArrowUp, ChevronRight, Eye, EyeOff, Folder, FolderPlus, Loader2 } from 'lucide-react';
import Modal from './Modal';
import { W, R, WS } from '../theme';
import { browseDirectory, createBrowseDirectory, type BrowseListing } from './useWorkspace';

export interface BrowsePick {
  path: string;
  folder: string | null;
  mode: 'local' | 'mounted';
  writable: boolean;
}

interface Props {
  open: boolean;
  onClose: () => void;
  onPick: (pick: BrowsePick) => void;
  onManual: () => void;
}

export default function DirectoryBrowser({ open, onClose, onPick, onManual }: Props) {
  const [listing, setListing] = useState<BrowseListing | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [pathDraft, setPathDraft] = useState('');
  const [showHidden, setShowHidden] = useState(false);
  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState('');
  const [createErr, setCreateErr] = useState('');
  const [creatingBusy, setCreatingBusy] = useState(false);
  const newInputRef = useRef<HTMLInputElement>(null);

  const load = useCallback(async (path?: string) => {
    setLoading(true); setError(''); setCreateErr('');
    try {
      const next = await browseDirectory(path);
      setListing(next);
      setPathDraft(next.path);
    } catch (e: any) {
      setError(e?.message || String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!open) return;
    setListing(null); setError(''); setShowHidden(false);
    setCreating(false); setNewName(''); setCreateErr('');
    void load();
  }, [open, load]);

  useEffect(() => {
    if (creating) newInputRef.current?.focus();
  }, [creating]);

  async function submitCreate() {
    if (!listing || creatingBusy) return;
    const name = newName.trim();
    if (!name) return;
    setCreatingBusy(true); setCreateErr('');
    try {
      await createBrowseDirectory(listing.path, name);
      setCreating(false); setNewName('');
      await load(listing.path);
    } catch (e: any) {
      setCreateErr(e?.message || String(e));
    } finally {
      setCreatingBusy(false);
    }
  }

  function pickCurrent() {
    if (!listing) return;
    onPick({
      path: listing.path,
      folder: listing.folder,
      mode: listing.mode,
      writable: listing.writable,
    });
  }

  function goUp() {
    const crumbs = listing?.crumbs ?? [];
    void load(crumbs.length >= 2 ? crumbs[crumbs.length - 2].path : '');
  }

  const visible = (listing?.entries ?? []).filter(e => showHidden || !e.hidden);

  return (
    <Modal
      open={open}
      title="选择项目文件夹"
      description="目录由后端读取；选中后作为项目的实际工作目录。"
      width={680}
      busy={creatingBusy}
      onClose={onClose}
      footer={(
        <>
          <button className="ws-link-btn" style={{ marginRight: 'auto' }} onClick={onManual}>
            手动输入路径
          </button>
          <button className="ws-btn ws-btn-outline" onClick={onClose} disabled={creatingBusy}
            style={{ height: 32, padding: '0 14px', borderRadius: R.sm }}>
            取消
          </button>
          <button className="ws-btn ws-btn-primary" onClick={pickCurrent}
            disabled={!listing || loading || creatingBusy}
            style={{ height: 32, padding: '0 14px', borderRadius: R.sm }}>
            选择此文件夹
          </button>
        </>
      )}
    >
      {/* 面包屑 + 上一级 */}
      <div className="ws-browse-crumbs">
        <button className="ws-btn ws-round" onClick={goUp} title="上一级"
          style={{ padding: 3, display: 'flex', color: W.secondary }}>
          <ArrowUp size={14} />
        </button>
        {listing?.crumbs.map((crumb, index) => (
          <span key={crumb.path} className="ws-browse-crumb">
            {index > 0 && <ChevronRight size={11} color={W.dimmed} />}
            <button className="ws-btn" onClick={() => void load(crumb.path)}
              title={crumb.path}>
              {crumb.label}
            </button>
          </span>
        ))}
        {!listing && !loading && !error && <span style={{ color: W.dimmed, fontSize: 12 }}>未加载</span>}
      </div>

      {/* 直接输入绝对路径（DSH 的 path draft） */}
      <div className="ws-browse-path">
        <input
          value={pathDraft}
          onChange={e => setPathDraft(e.target.value)}
          onKeyDown={e => {
            if (e.nativeEvent.isComposing) return;
            if (e.key === 'Enter') { e.preventDefault(); void load(pathDraft); }
          }}
          placeholder="绝对路径"
          aria-label="目录路径"
          className="ws-browse-input"
          disabled={loading}
        />
        <button className="ws-btn ws-btn-outline" onClick={() => void load(pathDraft)}
          disabled={loading || !pathDraft.trim()}
          style={{ height: 30, padding: '0 10px', borderRadius: R.sm, fontSize: 12 }}>
          转到
        </button>
      </div>

      <div className="ws-browse-toolbar">
        <button className="ws-btn ws-round" onClick={() => setShowHidden(v => !v)}
          title={showHidden ? '隐藏隐藏项' : '显示隐藏项'}
          style={{ padding: '3px 7px', display: 'flex', alignItems: 'center', gap: 4, fontSize: 12, color: W.dimmed }}>
          {showHidden ? <EyeOff size={13} /> : <Eye size={13} />}
          {showHidden ? '隐藏项开' : '隐藏项关'}
        </button>
        <div style={{ flex: 1 }} />
        {listing?.canCreate && !creating && (
          <button className="ws-btn ws-round" onClick={() => { setCreating(true); setCreateErr(''); }}
            style={{ padding: '3px 8px', display: 'flex', alignItems: 'center', gap: 4, fontSize: 12, color: W.secondary }}>
            <FolderPlus size={13} /> 新建文件夹
          </button>
        )}
      </div>

      {creating && (
        <div className="ws-browse-new">
          <FolderPlus size={13} color={W.dimmed} />
          <input
            ref={newInputRef}
            value={newName}
            onChange={e => { setNewName(e.target.value); setCreateErr(''); }}
            onKeyDown={e => {
              if (e.nativeEvent.isComposing) return;
              if (e.key === 'Enter') { e.preventDefault(); void submitCreate(); }
              if (e.key === 'Escape') { setCreating(false); setNewName(''); setCreateErr(''); }
            }}
            placeholder="文件夹名"
            className="ws-browse-input"
            disabled={creatingBusy}
          />
          <button className="ws-btn ws-btn-primary" onClick={() => void submitCreate()}
            disabled={!newName.trim() || creatingBusy}
            style={{ height: 28, padding: '0 10px', borderRadius: R.sm, fontSize: 12 }}>
            {creatingBusy ? '创建中…' : '创建'}
          </button>
          <button className="ws-btn" onClick={() => { setCreating(false); setNewName(''); setCreateErr(''); }}
            style={{ height: 28, padding: '0 8px', borderRadius: R.sm, fontSize: 12, color: W.dimmed }}>
            取消
          </button>
        </div>
      )}
      {createErr && <div className="ws-browse-error">{createErr}</div>}

      <div className="ws-browse-list">
        {loading && (
          <div className="ws-browse-center"><Loader2 size={16} className="ws-spin" /> 加载中…</div>
        )}
        {!loading && error && (
          <div className="ws-browse-center ws-browse-error">
            <span>{error}</span>
            <button className="ws-link-btn" onClick={() => void load(pathDraft || undefined)}>重试</button>
          </div>
        )}
        {!loading && !error && visible.length === 0 && (
          <div className="ws-browse-center">{listing?.entries.length ? '没有可见的子目录' : '这个目录下没有子目录'}</div>
        )}
        {!loading && !error && visible.map(entry => (
          <button key={entry.path} className="ws-browse-row" onClick={() => void load(entry.path)}
            title={entry.path} style={{ opacity: entry.hidden ? 0.65 : 1 }}>
            <Folder size={15} color={W.tertiary} />
            <span className="ws-browse-name">{entry.name}</span>
            <ChevronRight size={12} color={W.dimmed} />
          </button>
        ))}
        {listing?.truncated && !loading && !error && (
          <div className="ws-browse-center">目录项过多，仅显示前 1000 项</div>
        )}
      </div>
    </Modal>
  );
}
