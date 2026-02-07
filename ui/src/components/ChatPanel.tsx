import type { Message, ConnectionState } from '../types/index.ts';
import { MessageList } from './MessageList.tsx';
import { ChatInput } from './ChatInput.tsx';

interface ChatPanelProps {
  messages: Message[];
  onSend: (text: string) => void;
  connectionState: ConnectionState;
}

export function ChatPanel({ messages, onSend, connectionState }: ChatPanelProps) {
  const isDisconnected = connectionState !== 'connected';

  return (
    <div className="flex-1 flex flex-col min-h-0">
      <MessageList messages={messages} />
      <ChatInput onSend={onSend} disabled={isDisconnected} />
    </div>
  );
}
