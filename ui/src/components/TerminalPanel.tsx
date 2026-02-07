import { useState, useCallback, useRef, useEffect, type KeyboardEvent } from 'react';

interface TerminalPanelProps {
  output: string[];
  onCommand: (cmd: string) => void;
}

export function TerminalPanel({ output, onCommand }: TerminalPanelProps) {
  const [input, setInput] = useState('');
  const outputRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  // Auto-scroll output
  useEffect(() => {
    outputRef.current?.scrollTo({ top: outputRef.current.scrollHeight, behavior: 'smooth' });
  }, [output]);

  const handleSubmit = useCallback(() => {
    const trimmed = input.trim();
    if (!trimmed) return;
    onCommand(trimmed);
    setInput('');
  }, [input, onCommand]);

  const handleKeyDown = useCallback((e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      handleSubmit();
    }
  }, [handleSubmit]);

  // Focus input when panel mounts
  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  return (
    <div
      className="flex-1 bg-[#0a0a0a] p-4 font-mono text-sm flex flex-col min-h-0"
      role="region"
      aria-label="Terminal"
      onClick={() => inputRef.current?.focus()}
    >
      <div className="text-emerald-400 mb-1 text-xs font-bold tracking-wide">
        MegaBot v1.0.0
      </div>
      <div className="text-gray-500 mb-4 text-xs">
        Type &apos;help&apos; for available commands.
      </div>

      <div
        ref={outputRef}
        className="flex-1 overflow-y-auto mb-2 space-y-0.5"
        role="log"
        aria-label="Terminal output"
        aria-live="polite"
      >
        {output.map((line, idx) => (
          <div
            key={idx}
            className={`${line.startsWith('>') ? 'text-teal-400' : 'text-gray-300'} leading-relaxed`}
          >
            {line}
          </div>
        ))}
      </div>

      <div className="flex gap-2 items-center border-t border-gray-800 pt-2">
        <span className="text-teal-400 select-none text-xs" aria-hidden="true">megabot@local:~$</span>
        <input
          ref={inputRef}
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          className="flex-1 bg-transparent border-none outline-none text-white text-sm
                     focus-visible:outline-none caret-teal-400"
          aria-label="Terminal command input"
          spellCheck={false}
          autoComplete="off"
        />
      </div>
    </div>
  );
}
