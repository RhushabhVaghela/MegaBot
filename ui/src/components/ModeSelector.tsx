import type { SystemMode } from '../types/index.ts';
import { SYSTEM_MODES } from '../types/index.ts';

interface ModeSelectorProps {
  mode: SystemMode;
  onChangeMode: (mode: string) => void;
}

export function ModeSelector({ mode, onChangeMode }: ModeSelectorProps) {
  return (
    <div className="p-4 border-t border-gray-800">
      <label
        htmlFor="system-mode-select"
        className="text-[10px] uppercase text-gray-500 font-bold mb-2 block tracking-wider"
      >
        System Mode
      </label>
      <select
        id="system-mode-select"
        value={mode}
        onChange={(e) => onChangeMode(e.target.value)}
        className="w-full bg-[#0f1117] border border-gray-700 rounded-sm p-2 text-xs text-teal-400
                   focus:outline-none focus:ring-2 focus:ring-teal-500 focus:ring-offset-1 focus:ring-offset-[#161922]
                   transition-colors cursor-pointer"
        aria-label="System mode"
      >
        {SYSTEM_MODES.map(({ value, label }) => (
          <option key={value} value={value}>{label}</option>
        ))}
      </select>
    </div>
  );
}
