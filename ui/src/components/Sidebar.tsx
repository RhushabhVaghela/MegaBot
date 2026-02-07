import type { TabId, SystemMode, ConnectionState } from '../types/index.ts';
import { ModeSelector } from './ModeSelector.tsx';
import { ConnectionStatus } from './ConnectionStatus.tsx';

interface SidebarProps {
  activeTab: TabId;
  onTabChange: (tab: TabId) => void;
  mode: SystemMode;
  onChangeMode: (mode: string) => void;
  connectionState: ConnectionState;
}

const NAV_ITEMS: ReadonlyArray<{ id: TabId; label: string; icon: string; activeClass: string; mobileActiveClass: string }> = [
  { id: 'chat',     label: 'Chat',       icon: '💬', activeClass: 'bg-teal-600/20 text-teal-400', mobileActiveClass: 'text-teal-400' },
  { id: 'memory',   label: 'Memory',     icon: '🧠', activeClass: 'bg-amber-600/20 text-amber-400', mobileActiveClass: 'text-amber-400' },
  { id: 'terminal', label: 'Terminal',    icon: '💻', activeClass: 'bg-emerald-600/20 text-emerald-400', mobileActiveClass: 'text-emerald-400' },
];

export function Sidebar({ activeTab, onTabChange, mode, onChangeMode, connectionState }: SidebarProps) {
  return (
    <>
      {/* ── Desktop sidebar (md+) ── */}
      <aside
        className="hidden md:flex w-64 bg-[#161922] border-r border-gray-800 flex-col shrink-0"
        aria-label="Navigation sidebar"
      >
        {/* Brand */}
        <div className="p-6 border-b border-gray-800">
          <h1 className="text-xl font-bold text-teal-400 tracking-tight">
            MegaBot
          </h1>
          <p className="text-[10px] text-gray-500 mt-0.5 uppercase tracking-widest">Unified Local Assistant</p>
        </div>

        {/* Navigation */}
        <nav className="flex-1 p-4 space-y-1" aria-label="Main navigation">
          {NAV_ITEMS.map(({ id, label, icon, activeClass }) => (
            <button
              key={id}
              onClick={() => onTabChange(id)}
              aria-current={activeTab === id ? 'page' : undefined}
              className={`w-full text-left p-3 rounded-sm transition-colors text-sm font-medium
                          focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-teal-500
                          ${activeTab === id ? activeClass : 'text-gray-400 hover:bg-gray-800 hover:text-gray-200'}`}
            >
              <span aria-hidden="true" className="mr-2">{icon}</span>
              {label}
            </button>
          ))}
        </nav>

        {/* Mode selector */}
        <ModeSelector mode={mode} onChangeMode={onChangeMode} />

        {/* Status */}
        <div className="p-4 border-t border-gray-800">
          <ConnectionStatus state={connectionState} />
        </div>
      </aside>

      {/* ── Mobile bottom tab bar (<md) ── */}
      <nav
        className="md:hidden fixed bottom-0 left-0 right-0 z-40 bg-[#161922] border-t border-gray-800
                   flex items-stretch justify-around
                   pb-[env(safe-area-inset-bottom,0px)]"
        aria-label="Main navigation"
      >
        {NAV_ITEMS.map(({ id, label, icon, mobileActiveClass }) => (
          <button
            key={id}
            onClick={() => onTabChange(id)}
            aria-current={activeTab === id ? 'page' : undefined}
            className={`flex-1 flex flex-col items-center justify-center gap-0.5
                        min-h-[56px] py-2 transition-colors
                        focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-teal-500
                        ${activeTab === id ? mobileActiveClass : 'text-gray-500'}`}
          >
            <span aria-hidden="true" className="text-xl leading-none">{icon}</span>
            <span className="text-[10px] font-medium leading-none">{label}</span>
          </button>
        ))}

        {/* Connection status dot in the bar */}
        <div className="absolute top-2 right-3 pointer-events-none" aria-hidden="true">
          <ConnectionStatus state={connectionState} />
        </div>
      </nav>
    </>
  );
}
