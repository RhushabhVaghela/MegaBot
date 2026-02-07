import type { Message } from '../types/index.ts';

interface MessageBubbleProps {
  message: Message;
}

export function MessageBubble({ message }: MessageBubbleProps) {
  const isUser = message.type === 'user';

  return (
    <div
      className={`flex ${isUser ? 'justify-end' : 'justify-start'}`}
      role="listitem"
    >
      <div
        className={`max-w-[80%] p-4 shadow-lg text-sm leading-relaxed ${
          isUser
            ? 'bg-teal-600 text-white rounded-2xl rounded-tr-sm'
            : 'bg-[#1e2330] text-gray-200 rounded-2xl rounded-tl-sm border border-gray-700/60'
        }`}
      >
        {message.sender && (
          <div className="text-[10px] uppercase font-bold text-gray-400 mb-1 tracking-wider">
            {message.sender}
          </div>
        )}
        <p className="whitespace-pre-wrap break-words">{message.text}</p>
      </div>
    </div>
  );
}
