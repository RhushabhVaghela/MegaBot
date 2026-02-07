import { useRef, useEffect } from 'react';
import type { Message } from '../types/index.ts';
import { MessageBubble } from './MessageBubble.tsx';

interface MessageListProps {
  messages: Message[];
}

export function MessageList({ messages }: MessageListProps) {
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' });
  }, [messages]);

  return (
    <div
      ref={scrollRef}
      className="flex-1 overflow-y-auto p-6 space-y-4"
      role="list"
      aria-label="Chat messages"
    >
      {messages.length === 0 ? (
        <div className="h-full flex flex-col items-center justify-center text-gray-600 select-none">
          <div className="w-16 h-16 bg-gray-800 rounded-full flex items-center justify-center mb-4 text-2xl" aria-hidden="true">
            🤖
          </div>
          <p className="text-sm">How can I help you today?</p>
        </div>
      ) : (
        messages.map((msg) => (
          <MessageBubble key={msg.id} message={msg} />
        ))
      )}
    </div>
  );
}
