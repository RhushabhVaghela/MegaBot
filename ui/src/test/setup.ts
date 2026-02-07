import '@testing-library/jest-dom'
import { vi } from 'vitest'

// Mock WebSocket
interface MockMessageEvent {
  data: string;
}

class MockWebSocket {
  url: string;
  onmessage: ((ev: MockMessageEvent) => void) | null = null;
  onopen: (() => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  readyState: number = 1;
  static instances: MockWebSocket[] = [];
  static OPEN = 1;
  static CLOSED = 3;

  constructor(url: string) {
    this.url = url;
    MockWebSocket.instances.push(this);
    // Simulate async connection
    setTimeout(() => {
      this.readyState = 1;
      this.onopen?.();
    }, 0);
  }

  send(data: string) {
    const msg = JSON.parse(data);
    if (msg.type === 'set_mode') {
      setTimeout(() => {
        this.onmessage?.({ data: JSON.stringify({ type: 'mode_updated', mode: msg.mode }) });
      }, 0);
    }
  }

  close() {
    this.readyState = 3;
    this.onclose?.();
  }
}

// Expose static constants to match native WebSocket
Object.defineProperty(MockWebSocket, 'CONNECTING', { value: 0 });
Object.defineProperty(MockWebSocket, 'OPEN', { value: 1, writable: true });
Object.defineProperty(MockWebSocket, 'CLOSING', { value: 2 });
Object.defineProperty(MockWebSocket, 'CLOSED', { value: 3, writable: true });

vi.stubGlobal('WebSocket', MockWebSocket);

// Fix for JSDOM missing scrollTo
Element.prototype.scrollTo = vi.fn();
