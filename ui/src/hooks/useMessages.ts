import { useState, useCallback } from 'react';
import type { Message, InboundWsMessage, SearchResult, SystemMode, PendingApproval } from '../types/index.ts';

let messageIdCounter = 0;
function nextId(): string {
  messageIdCounter += 1;
  return `msg-${messageIdCounter}-${Date.now()}`;
}

interface UseMessagesReturn {
  messages: Message[];
  addUserMessage: (text: string) => void;
  terminalOutput: string[];
  addTerminalLine: (line: string) => void;
  searchResults: SearchResult[];
  categories: string[];
  mode: SystemMode;
  pendingApprovals: PendingApproval[];
  removeApproval: (actionId: string) => void;
  /** Pass this directly as `onMessage` to useWebSocket. */
  processMessage: (msg: InboundWsMessage) => void;
}

/**
 * Manages chat messages, terminal output, memory search results,
 * and system mode — all derived from inbound WebSocket events.
 *
 * Exposes `processMessage` which should be passed as the `onMessage`
 * callback to `useWebSocket`. This event-driven pattern avoids both
 * render-phase ref access and setState-in-effect lint violations.
 */
export function useMessages(): UseMessagesReturn {
  const [messages, setMessages] = useState<Message[]>([]);
  const [terminalOutput, setTerminalOutput] = useState<string[]>(['MegaBot Terminal Ready.']);
  const [searchResults, setSearchResults] = useState<SearchResult[]>([]);
  const [categories, setCategories] = useState<string[]>(['General']);
  const [mode, setMode] = useState<SystemMode>('plan');
  const [pendingApprovals, setPendingApprovals] = useState<PendingApproval[]>([]);

  const processMessage = useCallback((msg: InboundWsMessage) => {
    switch (msg.type) {
      case 'openclaw_event': {
        const { payload } = msg;
        if (payload.method === 'chat.message') {
          setMessages(prev => [...prev, {
            id: nextId(),
            sender: payload.params.sender ?? 'OpenClaw',
            text: payload.params.content,
            type: 'bot',
            timestamp: Date.now(),
          }]);
        }
        break;
      }
      case 'mode_updated':
        setMode(msg.mode);
        break;
      case 'search_results': {
        setSearchResults(msg.results);
        if (msg.results.length > 0) {
          const uniqueCats = Array.from(
            new Set(msg.results.map(r => r.category ?? 'General'))
          );
          setCategories(uniqueCats);
        }
        break;
      }
      case 'terminal_output':
        setTerminalOutput(prev => [...prev, msg.content]);
        break;
      case 'approval_required':
        setPendingApprovals(prev => [...prev, msg.action]);
        break;
      case 'approval_resolved':
        setPendingApprovals(prev => prev.filter(a => a.id !== msg.action_id));
        break;
      case 'generic':
        setMessages(prev => [...prev, {
          id: nextId(),
          sender: 'MegaBot',
          text: msg.text,
          type: 'bot',
          timestamp: Date.now(),
        }]);
        break;
    }
  }, []);

  const addUserMessage = useCallback((text: string) => {
    setMessages(prev => [...prev, {
      id: nextId(),
      sender: 'You',
      text,
      type: 'user',
      timestamp: Date.now(),
    }]);
  }, []);

  const addTerminalLine = useCallback((line: string) => {
    setTerminalOutput(prev => [...prev, line]);
  }, []);

  const removeApproval = useCallback((actionId: string) => {
    setPendingApprovals(prev => prev.filter(a => a.id !== actionId));
  }, []);

  return { messages, addUserMessage, terminalOutput, addTerminalLine, searchResults, categories, mode, pendingApprovals, removeApproval, processMessage };
}
