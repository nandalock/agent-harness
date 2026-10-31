'use client';

import { useState, useEffect, useCallback } from 'react';
import { usePathname } from 'next/navigation';
import Link from 'next/link';
import dynamic from 'next/dynamic';
import { MessageCircle, BookOpen, Bot, Plug, ChevronLeft, ChevronRight, Brain, Wrench, GitBranch, LayoutGrid } from 'lucide-react';
import { T, S } from '@/app/theme';

const ChatPageInner = dynamic(() => import('./_components/ChatPageInner'), { ssr:false });

interface MenuItem { label:string; path:string; icon:React.ReactNode; }
const MENU: MenuItem[] = [
  { label:'聊天', path:'/dashboard/chat', icon:<MessageCircle size={18} /> },
  { label:'知识库', path:'/dashboard/knowledge', icon:<BookOpen size={18} /> },
  { label:'Agent', path:'/dashboard/agents', icon:<Bot size={18} /> },
  { label:'工具', path:'/dashboard/mcp', icon:<Wrench size={18} /> },
  { label:'集成管理', path:'/dashboard/integrations', icon:<Plug size={18} /> },
  { label:'记忆系统', path:'/dashboard/memory', icon:<Brain size={18} /> },
  { label:'工作流', path:'/dashboard/workflow', icon:<GitBranch size={18} /> },
  { label:'工作区', path:'/dashboard/workspace', icon:<LayoutGrid size={18} /> },
];
const COLLAPSED_W=64, EXPANDED_W=220;

export default function DashboardLayout({ children }:{ children:React.ReactNode }) {
  const pathname = usePathname();
  const [collapsed, setCollapsed] = useState(false);
  const isChat = pathname==='/dashboard/chat';
  const isMcp = pathname === '/dashboard/mcp';
  const isWorkspace = pathname.startsWith('/dashboard/workspace');
  const isWorkflowEditor = pathname.startsWith('/dashboard/workflow/') && pathname !== '/dashboard/workflow';
  // 工作区需要最大可用宽度：进入时自动收成 64px 图标栏，离开时恢复用户偏好。
  // 进入后仍可手动展开（本 effect 只跟随路由变化，不覆盖手动 toggle）。
  useEffect(() => {
    let stored = false;
    try { stored = localStorage.getItem('sidebar_collapsed') === 'true'; } catch { /* ignore */ }
    setCollapsed(isWorkspace ? true : stored);
  }, [isWorkspace]);
  const [chatMounted, setChatMounted] = useState(false);
  useEffect(()=>{ if(isChat&&!chatMounted) setChatMounted(true); },[isChat,chatMounted]);

  const toggle = useCallback(()=>{ setCollapsed(p=>{ const n=!p; localStorage.setItem('sidebar_collapsed',String(n)); return n; }); },[]);

  const sidebarW = collapsed?COLLAPSED_W:EXPANDED_W;
  // 工作区用 DSH 深色 token（bluish-900 / 850 / 750），和其他页的 Coze 深蓝
  // 导航分开：工作区是深色三栏，导航再留一层蓝调会显脏。
  const navBg = isWorkspace ? '#1B1B1C' : T.sidebar;
  const navText = isWorkspace ? '#ADB2B8' : '#86909C';
  const navActiveBg = isWorkspace ? '#2C2C2E' : 'rgba(51,112,255,0.20)';
  const navActiveText = isWorkspace ? '#F9FAFB' : '#fff';
  const brandBg = isWorkspace ? 'rgba(255,255,255,0.08)' : T.accent;
  const avatarBg = isWorkspace ? '#2C2C2E' : 'rgba(51,112,255,0.20)';
  const avatarText = isWorkspace ? '#F9FAFB' : T.accent;
  const isActive = (item:MenuItem) => item.path==='/dashboard'?pathname==='/dashboard':pathname.startsWith(item.path);

  return (
    <div style={{ display:'flex', height:'100vh' }}>
      {/* ── Coze-style sidebar: dark navy ── */}
      <div style={{ width:sidebarW, background:navBg, display:'flex', flexDirection:'column', flexShrink:0, transition:'width .18s ease', overflow:'hidden' }}>
        {/* Brand */}
        <div style={{ padding:collapsed?`${S.base}px ${S.sm}px`:`${S.lg}px ${S.xl}px ${S.base}px`, display:'flex', alignItems:'center', gap:S.sm }}>
          <div style={{ width:32, height:32, borderRadius:8, background:brandBg, flexShrink:0, display:'flex', alignItems:'center', justifyContent:'center', fontSize:14, fontWeight:700, color:'#F9FAFB' }}>AH</div>
          {!collapsed && <span style={{ fontSize:16, fontWeight:600, color:'#F9FAFB', whiteSpace:'nowrap' }}>minidsh</span>}
        </div>
        {/* Nav */}
        <nav style={{ flex:1, padding:`${S.sm}px ${S.xs}px`, display:'flex', flexDirection:'column', gap:1 }}>
          {MENU.map(item=>{
            const active = isActive(item);
            return (
              <Link key={item.path} href={item.path} title={collapsed?item.label:undefined} style={{
                display:'flex', alignItems:'center', gap:10, padding:collapsed?'10px 0':'10px 12px',
                borderRadius:6, justifyContent:collapsed?'center':'flex-start',
                color:active?navActiveText:navText, textDecoration:'none', fontSize:14, fontWeight:active?500:400,
                background:active?navActiveBg:'transparent', whiteSpace:'nowrap',
              }}>{item.icon}{!collapsed && item.label}</Link>
            );
          })}
        </nav>
        {/* Collapse button */}
        <div style={{ padding:`0 ${S.xs}px ${S.xs}px` }}>
          <button onClick={toggle} style={{ width:'100%', padding:'6px 0', borderRadius:6, border:'none', cursor:'pointer', background:'transparent', color:navText, display:'flex', justifyContent:'center' }}>{collapsed?<ChevronRight size={16} />:<ChevronLeft size={16} />}</button>
        </div>
        {/* User */}
        <div style={{ borderTop:'1px solid rgba(255,255,255,0.08)' }}>
          <div style={{
            padding:collapsed?`${S.md}px 0`:`${S.md}px ${S.base}px`, fontSize:13, color:navText,
            display:'flex', alignItems:'center', gap:S.sm, justifyContent:collapsed?'center':'flex-start',
          }}>
            <div style={{ width:28, height:28, borderRadius:'50%', background:avatarBg, flexShrink:0, display:'flex', alignItems:'center', justifyContent:'center', fontSize:12, fontWeight:600, color:avatarText }}>JK</div>
            {!collapsed && <span>jk</span>}
          </div>
        </div>
      </div>

      {/* ── Content ── */}
      {!isChat && !isMcp && !isWorkspace && !isWorkflowEditor && <div style={{ flex:1, background:T.bg, overflow:'auto', padding:S.xl }}>{children}</div>}
      {isMcp && <div style={{ flex:1, overflow:'hidden' }}>{children}</div>}
      {isWorkflowEditor && <div style={{ flex:1, overflow:'hidden' }}>{children}</div>}
      {/* 工作区是自管滚动的三栏（会话 / 文件树 / 预览），不要外层 padding 与滚动条 */}
      {isWorkspace && <div style={{ flex:1, minWidth:0, overflow:'hidden' }}>{children}</div>}
      {chatMounted && <div style={{ flex:1, display:isChat?undefined:'none' }}><ChatPageInner /></div>}
    </div>
  );
}
