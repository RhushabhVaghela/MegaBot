/** Shared domain types for the MegaBot dashboard. */

export interface Message {
  id: string;
  sender: string;
  text: string;
  type: 'user' | 'bot' | 'system';
  timestamp: number;
}

export interface SearchResult {
  content: string;
  category?: string;
}

export type TabId = 'chat' | 'memory' | 'terminal';

export type SystemMode = 'plan' | 'build' | 'ask' | 'loki';

export const SYSTEM_MODES: ReadonlyArray<{ value: SystemMode; label: string }> = [
  { value: 'plan', label: 'Plan (Read-only)' },
  { value: 'build', label: 'Build (Full Access)' },
  { value: 'ask', label: 'Ask (Conversational)' },
  { value: 'loki', label: 'Loki (Autonomous)' },
] as const;

export type ConnectionState = 'connecting' | 'connected' | 'disconnected' | 'error';

/**
 * Represents a pending action awaiting human approval.
 * Matches the sanitized action object sent by the backend
 * (see ``core/task_utils.sanitize_action``).
 */
export interface PendingApproval {
  id: string;
  type: string;
  description: string;
  payload?: { method?: string; params?: Record<string, unknown> };
}

/**
 * Discriminated union for all inbound WebSocket message types.
 * Enables exhaustive switch handling.
 */
export type InboundWsMessage =
  | { type: 'openclaw_event'; payload: { method: string; params: { sender?: string; content: string } } }
  | { type: 'mode_updated'; mode: SystemMode }
  | { type: 'search_results'; results: SearchResult[] }
  | { type: 'terminal_output'; content: string }
  | { type: 'approval_required'; action: PendingApproval }
  | { type: 'approval_resolved'; action_id: string; approved: boolean }
  | { type: 'generic'; text: string };

export type OutboundWsMessage =
  | { type: 'message'; content: string }
  | { type: 'set_mode'; mode: string }
  | { type: 'search'; query: string }
  | { type: 'command'; command: string }
  | { type: 'approve_action'; action_id: string }
  | { type: 'reject_action'; action_id: string };
