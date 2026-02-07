import type { ConnectionState } from '../types/index.ts';

interface ConnectionStatusProps {
  state: ConnectionState;
}

const STATE_CONFIG: Record<ConnectionState, { label: string; color: string; dot: string }> = {
  connected:    { label: 'Connected',    color: 'text-emerald-400', dot: 'bg-emerald-400' },
  connecting:   { label: 'Connecting…',  color: 'text-amber-400',   dot: 'bg-amber-400' },
  disconnected: { label: 'Disconnected', color: 'text-red-400',     dot: 'bg-red-400' },
  error:        { label: 'Error',        color: 'text-red-400',     dot: 'bg-red-400' },
};

export function ConnectionStatus({ state }: ConnectionStatusProps) {
  const cfg = STATE_CONFIG[state];

  return (
    <div className="flex items-center gap-2 text-xs" role="status" aria-live="polite">
      <span className={`inline-block h-2 w-2 rounded-full ${cfg.dot} ${
        state === 'connecting' ? 'animate-pulse' : ''
      }`} aria-hidden="true" />
      <span className={cfg.color}>{cfg.label}</span>
    </div>
  );
}
