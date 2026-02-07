import { useState, useCallback } from 'react';
import type { TabId } from './types/index.ts';
import { useWebSocket } from './hooks/useWebSocket.ts';
import { useMessages } from './hooks/useMessages.ts';
import { Sidebar, ChatPanel, TerminalPanel, MemoryPanel, ErrorBoundary, ApprovalPanel } from './components/index.ts';

function App() {
  const { messages, addUserMessage, terminalOutput, addTerminalLine, searchResults, categories, mode, pendingApprovals, removeApproval, processMessage } = useMessages();
  const { send, connectionState } = useWebSocket({ onMessage: processMessage });
  const [activeTab, setActiveTab] = useState<TabId>('chat');

  const handleSendMessage = useCallback((text: string) => {
    send({ type: 'message', content: text });
    addUserMessage(text);
  }, [send, addUserMessage]);

  const handleChangeMode = useCallback((newMode: string) => {
    send({ type: 'set_mode', mode: newMode });
  }, [send]);

  const handleTerminalCommand = useCallback((cmd: string) => {
    send({ type: 'command', command: cmd });
    addTerminalLine(`> ${cmd}`);
  }, [send, addTerminalLine]);

  const handleSearchMemory = useCallback((query: string) => {
    send({ type: 'search', query });
  }, [send]);

  const handleApprove = useCallback((actionId: string) => {
    send({ type: 'approve_action', action_id: actionId });
    removeApproval(actionId);
  }, [send, removeApproval]);

  const handleReject = useCallback((actionId: string) => {
    send({ type: 'reject_action', action_id: actionId });
    removeApproval(actionId);
  }, [send, removeApproval]);

  return (
    <div className="flex h-dvh bg-[#0f1117] text-gray-200 font-sans">
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:absolute focus:z-50 focus:p-4 focus:bg-teal-600 focus:text-white"
      >
        Skip to main content
      </a>

      <Sidebar
        activeTab={activeTab}
        onTabChange={setActiveTab}
        mode={mode}
        onChangeMode={handleChangeMode}
        connectionState={connectionState}
      />

      {/* Main content — on mobile, add bottom padding for the fixed tab bar */}
      <main
        id="main-content"
        className="flex-1 flex flex-col min-h-0 min-w-0
                   pb-[calc(56px+env(safe-area-inset-bottom,0px))] md:pb-0"
      >
        <ErrorBoundary>
          {pendingApprovals.length > 0 && (
            <ApprovalPanel
              pendingApprovals={pendingApprovals}
              onApprove={handleApprove}
              onReject={handleReject}
            />
          )}
          {activeTab === 'chat' && (
            <ChatPanel
              messages={messages}
              onSend={handleSendMessage}
              connectionState={connectionState}
            />
          )}
          {activeTab === 'terminal' && (
            <TerminalPanel
              output={terminalOutput}
              onCommand={handleTerminalCommand}
            />
          )}
          {activeTab === 'memory' && (
            <MemoryPanel
              categories={categories}
              searchResults={searchResults}
              onSearch={handleSearchMemory}
            />
          )}
        </ErrorBoundary>
      </main>
    </div>
  );
}

export default App;
