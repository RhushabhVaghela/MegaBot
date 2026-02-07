import { render, screen, fireEvent, waitFor, act, within } from '@testing-library/react'
import { describe, it, expect, beforeEach } from 'vitest'
import App from './App'

interface MockWebSocketInstance {
  onmessage: ((ev: { data: string }) => void) | null;
  onopen: (() => void) | null;
  onclose: (() => void) | null;
  onerror: (() => void) | null;
  readyState: number;
  close: () => void;
  send: (data: string) => void;
}

interface MockWebSocketStatic {
  instances: MockWebSocketInstance[];
  OPEN: number;
  CLOSED: number;
}

function getMockWS(): MockWebSocketInstance {
  return (window.WebSocket as unknown as MockWebSocketStatic).instances[0]
}

/**
 * Helper: get a tab button from the desktop sidebar (the <aside>).
 * The mobile nav also renders the same labels, so we scope to the aside.
 */
function getDesktopTab(name: RegExp): HTMLElement {
  const sidebar = screen.getByLabelText(/Navigation sidebar/i)
  return within(sidebar).getByText(name)
}

describe('App Component', () => {
  beforeEach(() => {
    (window.WebSocket as unknown as MockWebSocketStatic).instances = []
  })

  it('renders MegaBot header', () => {
    render(<App />)
    expect(screen.getByText(/MegaBot/i)).toBeInTheDocument()
  })

  it('renders skip-to-content link for accessibility', () => {
    render(<App />)
    expect(screen.getByText(/Skip to main content/i)).toBeInTheDocument()
  })

  it('shows connection status', () => {
    render(<App />)
    // Connection status should be visible (connecting initially)
    expect(screen.getAllByRole('status').length).toBeGreaterThan(0)
  })

  it('switches to terminal tab', () => {
    render(<App />)
    fireEvent.click(getDesktopTab(/Terminal/i))
    expect(screen.getByText(/megabot@local:~\$/i)).toBeInTheDocument()
  })

  it('switches to memory tab', () => {
    render(<App />)
    fireEvent.click(getDesktopTab(/Memory/i))
    expect(screen.getByText(/Hierarchical Memory/i)).toBeInTheDocument()
  })

  it('sends a chat message and clears input', async () => {
    render(<App />)
    // Wait for connection to establish
    await act(async () => {
      await new Promise(r => setTimeout(r, 10))
    })

    const input = screen.getByPlaceholderText(/Ask anything/i)
    const sendButton = screen.getByLabelText(/Send message/i)

    fireEvent.change(input, { target: { value: 'test message' } })
    fireEvent.click(sendButton)

    expect(screen.getByText('test message')).toBeInTheDocument()
    expect((input as HTMLInputElement).value).toBe('')
  })

  it('sends message on Enter key', async () => {
    render(<App />)
    await act(async () => {
      await new Promise(r => setTimeout(r, 10))
    })

    const input = screen.getByPlaceholderText(/Ask anything/i)
    fireEvent.change(input, { target: { value: 'enter message' } })
    fireEvent.keyDown(input, { key: 'Enter', code: 'Enter' })
    expect(screen.getByText('enter message')).toBeInTheDocument()
  })

  it('does not send empty messages', async () => {
    render(<App />)
    await act(async () => {
      await new Promise(r => setTimeout(r, 10))
    })

    const sendButton = screen.getByLabelText(/Send message/i)
    expect(sendButton).toBeDisabled()
  })

  it('changes system mode', async () => {
    render(<App />)
    const select = screen.getByLabelText(/System mode/i)
    fireEvent.change(select, { target: { value: 'build' } })
    await waitFor(() => {
      expect((select as HTMLSelectElement).value).toBe('build')
    })
  })

  it('handles openclaw_event from WebSocket', async () => {
    render(<App />)
    const ws = getMockWS()
    act(() => {
      ws.onmessage?.({ data: JSON.stringify({
        type: 'openclaw_event',
        payload: {
          method: 'chat.message',
          params: { sender: 'OpenClawBot', content: 'hello world' }
        }
      })})
    })
    expect(screen.getByText('hello world')).toBeInTheDocument()
    expect(screen.getByText('OpenClawBot')).toBeInTheDocument()
  })

  it('handles search_results from WebSocket', async () => {
    render(<App />)
    fireEvent.click(getDesktopTab(/Memory/i))

    const refreshButton = screen.getByLabelText(/Refresh memory items/i)
    fireEvent.click(refreshButton)

    const ws = getMockWS()
    act(() => {
      ws.onmessage?.({ data: JSON.stringify({
        type: 'search_results',
        results: [{ content: 'memory item 1' }]
      })})
    })
    expect(screen.getByText('memory item 1')).toBeInTheDocument()
  })

  it('handles generic text messages', async () => {
    render(<App />)
    const ws = getMockWS()
    act(() => {
      ws.onmessage?.({ data: 'Generic system update' })
    })
    expect(screen.getByText('Generic system update')).toBeInTheDocument()
  })

  it('handles mode_updated message', async () => {
    render(<App />)
    const ws = getMockWS()
    act(() => {
      ws.onmessage?.({ data: JSON.stringify({
        type: 'mode_updated',
        mode: 'debug'
      }) })
    })
    const select = screen.getByLabelText(/System mode/i)
    expect((select as HTMLSelectElement).value).toBe('debug')
  })

  it('handles terminal_output from WebSocket', async () => {
    render(<App />)
    fireEvent.click(getDesktopTab(/Terminal/i))

    const ws = getMockWS()
    act(() => {
      ws.onmessage?.({ data: JSON.stringify({
        type: 'terminal_output',
        content: 'Build complete.'
      })})
    })
    expect(screen.getByText('Build complete.')).toBeInTheDocument()
  })

  it('sends terminal commands', async () => {
    render(<App />)
    await act(async () => {
      await new Promise(r => setTimeout(r, 10))
    })

    fireEvent.click(getDesktopTab(/Terminal/i))

    const termInput = screen.getByLabelText(/Terminal command input/i)
    fireEvent.change(termInput, { target: { value: 'help' } })
    fireEvent.keyDown(termInput, { key: 'Enter', code: 'Enter' })

    expect(screen.getByText('> help')).toBeInTheDocument()
  })
})
