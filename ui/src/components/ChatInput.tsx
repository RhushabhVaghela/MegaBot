import { useState, useCallback, type KeyboardEvent } from 'react';

interface ChatInputProps {
  onSend: (text: string) => void;
  disabled?: boolean;
}

export function ChatInput({ onSend, disabled = false }: ChatInputProps) {
  const [input, setInput] = useState('');

  const handleSend = useCallback(() => {
    const trimmed = input.trim();
    if (!trimmed) return;
    onSend(trimmed);
    setInput('');
  }, [input, onSend]);

  const handleKeyDown = useCallback((e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  }, [handleSend]);

  return (
    <div className="p-4 md:p-6 bg-[#161922] border-t border-gray-800">
      <div className="max-w-4xl mx-auto flex gap-3">
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          disabled={disabled}
          className="flex-1 bg-[#0f1117] border border-gray-700 rounded-sm p-3 md:p-4 text-sm min-h-12
                     placeholder:text-gray-600
                     focus:outline-none focus:ring-2 focus:ring-teal-500 focus:ring-offset-1 focus:ring-offset-[#161922]
                     transition-colors disabled:opacity-50"
          placeholder="Ask anything…"
          aria-label="Chat message input"
        />
        <button
          onClick={handleSend}
          disabled={disabled || !input.trim()}
          className="bg-teal-600 hover:bg-teal-500 text-white px-4 md:px-6 py-3 md:py-4 rounded-sm font-medium text-sm min-h-12
                     transition-all active:scale-[0.97]
                     focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-teal-500
                     disabled:opacity-40 disabled:cursor-not-allowed disabled:active:scale-100"
          aria-label="Send message"
        >
          Send
        </button>
      </div>
    </div>
  );
}
