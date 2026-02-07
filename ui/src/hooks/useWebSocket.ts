import { useEffect, useRef, useState, useCallback } from 'react';
import type { ConnectionState, InboundWsMessage, OutboundWsMessage } from '../types/index.ts';

const WS_BASE_URL = import.meta.env.VITE_WS_URL || 'ws://127.0.0.1:8000/ws';
const WS_AUTH_TOKEN = import.meta.env.VITE_WS_AUTH_TOKEN || '';
const WS_URL = WS_AUTH_TOKEN
  ? `${WS_BASE_URL}${WS_BASE_URL.includes('?') ? '&' : '?'}token=${encodeURIComponent(WS_AUTH_TOKEN)}`
  : WS_BASE_URL;
const RECONNECT_DELAY_MS = 3000;
const MAX_RECONNECT_ATTEMPTS = 5;

interface UseWebSocketOptions {
  /** Called synchronously whenever an inbound message arrives. */
  onMessage?: (msg: InboundWsMessage) => void;
}

interface UseWebSocketReturn {
  send: (message: OutboundWsMessage) => void;
  connectionState: ConnectionState;
}

function parseMessage(event: MessageEvent): InboundWsMessage {
  try {
    const data = JSON.parse(event.data as string);
    if (data.type === 'openclaw_event' || data.type === 'mode_updated' ||
        data.type === 'search_results' || data.type === 'terminal_output' ||
        data.type === 'approval_required' || data.type === 'approval_resolved') {
      return data as InboundWsMessage;
    }
    return { type: 'generic', text: event.data as string };
  } catch {
    return { type: 'generic', text: event.data as string };
  }
}

/**
 * Manages the WebSocket lifecycle: connect, reconnect, parse inbound
 * messages into typed discriminated unions, and expose a typed `send`.
 *
 * Accepts an optional `onMessage` callback so consumers can react to
 * inbound messages without intermediate state (avoids render-phase
 * ref access and setState-in-effect lint issues).
 */
export function useWebSocket(options?: UseWebSocketOptions): UseWebSocketReturn {
  const ws = useRef<WebSocket | null>(null);
  const reconnectAttempts = useRef(0);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Store the onMessage callback in a ref so the WebSocket onmessage
  // handler always calls the latest version without needing it as a
  // dependency of the connection effect.
  const onMessageRef = useRef(options?.onMessage);

  const [connectionState, setConnectionState] = useState<ConnectionState>('connecting');

  // Keep the ref in sync with the latest callback on every render.
  // This is safe: we're updating a ref that is *not* read during render,
  // only inside the WebSocket event handler (an async callback).
  useEffect(() => {
    onMessageRef.current = options?.onMessage;
  });

  useEffect(() => {
    let disposed = false;

    function connect() {
      // Clean up any existing connection
      if (ws.current) {
        ws.current.onopen = null;
        ws.current.onmessage = null;
        ws.current.onclose = null;
        ws.current.onerror = null;
        if (ws.current.readyState === WebSocket.OPEN) {
          ws.current.close();
        }
      }

      if (disposed) return;
      setConnectionState('connecting');

      const socket = new WebSocket(WS_URL);

      socket.onopen = () => {
        if (disposed) return;
        setConnectionState('connected');
        reconnectAttempts.current = 0;
      };

      socket.onmessage = (event: MessageEvent) => {
        if (disposed) return;
        const parsed = parseMessage(event);
        onMessageRef.current?.(parsed);
      };

      socket.onclose = () => {
        if (disposed) return;
        setConnectionState('disconnected');
        if (reconnectAttempts.current < MAX_RECONNECT_ATTEMPTS) {
          reconnectTimer.current = setTimeout(() => {
            reconnectAttempts.current += 1;
            connect();
          }, RECONNECT_DELAY_MS);
        }
      };

      socket.onerror = () => {
        if (disposed) return;
        setConnectionState('error');
      };

      ws.current = socket;
    }

    connect();

    return () => {
      disposed = true;
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current);
      ws.current?.close();
    };
  }, []);

  const send = useCallback((message: OutboundWsMessage) => {
    if (ws.current?.readyState === WebSocket.OPEN) {
      ws.current.send(JSON.stringify(message));
    }
  }, []);

  return { send, connectionState };
}
