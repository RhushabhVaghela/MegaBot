import { render, screen, fireEvent, waitFor, act } from '@testing-library/react'
import { describe, it, expect, beforeEach } from 'vitest'
import App from './App'

interface MockWebSocketStatic {
  instances: Array<{
    onmessage: ((ev: { data: string }) => void) | null;
    close: () => void;
  }>;
}

function getMockWS() {
  return (window.WebSocket as unknown as MockWebSocketStatic).instances[0]
}

describe('App Component', () => {
  beforeEach(() => {
    (window.WebSocket as unknown as MockWebSocketStatic).instances = []
  })

  it('renders MegaBot header', () => {
    render(<App />)
    expect(screen.getByText(/MegaBot/i)).toBeInTheDocument()
  })

  it('switches tabs', () => {
    render(<App />)
    const memoryTab = screen.getByText(/Memory Hub/i)
    fireEvent.click(memoryTab)
    expect(screen.getByText(/Hierarchical Memory/i)).toBeInTheDocument()
    
    const terminalTab = screen.getByText(/Terminal/i)
    fireEvent.click(terminalTab)
    expect(screen.getByText(/megabot@local:~\$/i)).toBeInTheDocument()
  })

  it('sends a message', async () => {
    render(<App />)
    const input = screen.getByPlaceholderText(/Ask anything.../i)
    const sendButton = screen.getByText(/Send/i)

    fireEvent.change(input, { target: { value: 'test message' } })
    fireEvent.click(sendButton)

    expect(screen.getByText('test message')).toBeInTheDocument()
    expect((input as HTMLInputElement).value).toBe('')
  })

  it('triggers sendMessage on Enter', () => {
    render(<App />)
    const input = screen.getByPlaceholderText(/Ask anything.../i)
    fireEvent.change(input, { target: { value: 'enter message' } })
    fireEvent.keyPress(input, { key: 'Enter', charCode: 13 })
    expect(screen.getByText('enter message')).toBeInTheDocument()
  })

  it('clicks chat tab', () => {
    render(<App />)
    const chatTab = screen.getByText(/Chat/i)
    fireEvent.click(chatTab)
    expect(screen.getByPlaceholderText(/Ask anything.../i)).toBeInTheDocument()
  })

  it('changes system mode', async () => {
    render(<App />)
    const select = screen.getByRole('combobox')
    fireEvent.change(select, { target: { value: 'build' } })
    await waitFor(() => {
      expect((select as HTMLSelectElement).value).toBe('build')
    })
  })

  it('handles openclaw events', async () => {
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

  it('handles search results', async () => {
    render(<App />)
    fireEvent.click(screen.getByText(/Memory Hub/i))
    
    const refreshButton = screen.getByText(/Refresh/i)
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

  it('handles generic messages', async () => {
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
    const select = screen.getByRole('combobox')
    expect((select as HTMLSelectElement).value).toBe('debug')
  })

  it('handles sendMessage when ws is null', async () => {
    // First render with working websocket
    render(<App />)
    const ws = getMockWS()
    
    // Close the websocket to make ws.current null
    act(() => {
      ws.close()
    })
    
    const input = screen.getByPlaceholderText(/Ask anything.../i)
    fireEvent.change(input, { target: { value: 'test without ws' } })
    fireEvent.keyPress(input, { key: 'Enter', charCode: 13 })
    // Message should still appear in UI even if ws is closed
    expect(screen.getByText('test without ws')).toBeInTheDocument()
  })
})
