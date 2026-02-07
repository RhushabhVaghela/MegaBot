import { useState, useEffect, useRef } from 'react';

interface Message {
  sender: string;
  text: string;
  type?: 'user' | 'bot' | 'system';
}

interface SearchResult {
  content: string;
  category?: string;
}

const WS_URL = import.meta.env.VITE_WS_URL || 'ws://127.0.0.1:8000/ws';

function App() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [activeTab, setActiveTab] = useState<'chat' | 'memory' | 'terminal'>('chat');
  const [mode, setMode] = useState<string>('plan');
  const [searchResults, setSearchResults] = useState<SearchResult[]>([]);
  const ws = useRef<WebSocket | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  const [categories, setCategories] = useState<string[]>(['General']);
  const [terminalInput, setTerminalInput] = useState('');
  const [terminalOutput, setTerminalOutput] = useState<string[]>(['MegaBot Terminal Ready.']);

  useEffect(() => {
    ws.current = new WebSocket(WS_URL);
    ws.current.onmessage = (event) => {
      let data;
      try {
        data = JSON.parse(event.data);
      } catch {
        data = { type: 'generic', text: event.data };
      }
      
      if (data.type === 'openclaw_event') {
        const payload = data.payload;
        if (payload.method === 'chat.message') {
           setMessages(prev => [...prev, {
             sender: payload.params.sender || 'OpenClaw', 
             text: payload.params.content,
             type: 'bot'
           }]);
        }
      } else if (data.type === 'mode_updated') {
        setMode(data.mode);
      } else if (data.type === 'search_results') {
        setSearchResults(data.results);
        // Extract unique categories from results if available
        if (data.results && data.results.length > 0) {
           const cats = Array.from(new Set(data.results.map((r: SearchResult) => r.category || 'General')));
           setCategories(cats as string[]);
        }
      } else if (data.type === 'terminal_output') {
        setTerminalOutput(prev => [...prev, data.content]);
      } else {
        setMessages(prev => [...prev, {sender: 'MegaBot', text: event.data || JSON.stringify(data), type: 'bot'}]);
      }
    };
    return () => ws.current?.close();
  }, []);

  const sendTerminalCommand = () => {
    if (terminalInput && ws.current) {
      ws.current.send(JSON.stringify({ type: 'command', command: terminalInput }));
      setTerminalOutput(prev => [...prev, `> ${terminalInput}`]);
      setTerminalInput('');
    }
  };

  const changeMode = (newMode: string) => {
    if (ws.current) {
      ws.current.send(JSON.stringify({ type: 'set_mode', mode: newMode }));
    }
  };

  useEffect(() => {
    scrollRef.current?.scrollTo(0, scrollRef.current.scrollHeight);
  }, [messages]);

  const sendMessage = () => {
    if (input && ws.current) {
      const payload = { type: 'message', content: input };
      ws.current.send(JSON.stringify(payload));
      setMessages(prev => [...prev, {sender: 'You', text: input, type: 'user'}]);
      setInput('');
    }
  };

  const searchMemory = (query: string) => {
    if (ws.current) {
      ws.current.send(JSON.stringify({ type: 'search', query }));
    }
  };

  return (
    <div className="flex h-screen bg-[#0f1117] text-gray-200 font-sans">
      {/* Sidebar */}
      <aside className="w-64 bg-[#161922] border-r border-gray-800 flex flex-col" aria-label="Navigation sidebar">
        <div className="p-6 border-b border-gray-800">
          <h1 className="text-xl font-bold bg-gradient-to-r from-blue-400 to-purple-500 bg-clip-text text-transparent">
            MegaBot
          </h1>
          <p className="text-xs text-gray-500 mt-1">Unified Local Assistant</p>
        </div>
        <nav className="flex-1 p-4 space-y-2">
          <button 
            onClick={() => setActiveTab('chat')}
            className={`w-full text-left p-3 rounded-lg transition ${activeTab === 'chat' ? 'bg-blue-600/20 text-blue-400' : 'hover:bg-gray-800'}`}
          >
            💬 Chat
          </button>
          <button 
            onClick={() => setActiveTab('memory')}
            className={`w-full text-left p-3 rounded-lg transition ${activeTab === 'memory' ? 'bg-purple-600/20 text-purple-400' : 'hover:bg-gray-800'}`}
          >
            🧠 Memory Hub
          </button>
          <button 
            onClick={() => setActiveTab('terminal')}
            className={`w-full text-left p-3 rounded-lg transition ${activeTab === 'terminal' ? 'bg-green-600/20 text-green-400' : 'hover:bg-gray-800'}`}
          >
            💻 Terminal
          </button>
        </nav>

        <div className="p-4 border-t border-gray-800">
          <label className="text-[10px] uppercase text-gray-500 font-bold mb-2 block">System Mode</label>
          <select 
            value={mode} 
            onChange={(e) => changeMode(e.target.value)}
            className="w-full bg-[#0f1117] border border-gray-700 rounded p-2 text-xs text-blue-400 focus:outline-none"
            aria-label="System mode"
          >
            <option value="plan">Plan (Read-only)</option>
            <option value="build">Build (Full Access)</option>
            <option value="architect">Architect</option>
            <option value="debug">Debug</option>
          </select>
        </div>
        <div className="p-4 border-t border-gray-800 text-xs text-gray-600">
          Status: <span className="text-green-500">Local Only</span>
        </div>
      </aside>

      {/* Main Content */}
      <main className="flex-1 flex flex-col">
        {activeTab === 'chat' ? (
          <>
            <div ref={scrollRef} className="flex-1 overflow-y-auto p-6 space-y-4">
              {messages.length === 0 && (
                <div className="h-full flex flex-col items-center justify-center text-gray-600">
                  <div className="w-16 h-16 bg-gray-800 rounded-full flex items-center justify-center mb-4">
                    🤖
                  </div>
                  <p>How can I help you today?</p>
                </div>
              )}
              {messages.map((msg, i) => (
                <div key={i} className={`flex ${msg.type === 'user' ? 'justify-end' : 'justify-start'}`}>
                  <div className={`max-w-[80%] p-4 rounded-2xl shadow-lg ${
                    msg.type === 'user' 
                      ? 'bg-blue-600 text-white rounded-tr-none' 
                      : 'bg-[#1e2330] text-gray-200 rounded-tl-none border border-gray-700'
                  }`}>
                    {msg.sender && <div className="text-[10px] uppercase font-bold text-gray-500 mb-1">{msg.sender}</div>}
                    <p className="text-sm">{msg.text}</p>
                  </div>
                </div>
              ))}
            </div>
            
            <div className="p-6 bg-[#161922] border-t border-gray-800">
              <div className="max-w-4xl mx-auto flex gap-4">
                <input 
                  type="text" 
                  value={input} 
                  onChange={(e) => setInput(e.target.value)}
                  onKeyPress={(e) => e.key === 'Enter' && sendMessage()}
                  className="flex-1 bg-[#0f1117] border border-gray-700 rounded-xl p-4 focus:outline-none focus:ring-2 focus:ring-blue-500 transition shadow-inner"
                  placeholder="Ask anything..."
                  aria-label="Chat message input"
                />
                <button 
                  onClick={sendMessage}
                  className="bg-blue-600 hover:bg-blue-700 text-white px-8 py-4 rounded-xl font-medium transition transform active:scale-95 shadow-lg shadow-blue-900/20"
                  aria-label="Send message"
                >
                  Send
                </button>
              </div>
            </div>
          </>
        ) : activeTab === 'terminal' ? (
          <div className="flex-1 bg-black p-4 font-mono text-sm overflow-y-auto flex flex-col">
            <div className="text-green-500 mb-2">MegaBot v0.2.0-alpha (Combined OpenClaw + memU + Roo Code + OpenCode)</div>
            <div className="text-gray-400 mb-4">Type 'help' for available commands.</div>
            <div className="flex-1 overflow-y-auto mb-2" role="log" aria-label="Terminal output">
              {terminalOutput.map((line, idx) => (
                <div key={idx} className={`${line.startsWith('>') ? 'text-blue-400' : 'text-gray-300'}`}>{line}</div>
              ))}
            </div>
            <div className="flex gap-2">
              <span className="text-blue-400">megabot@local:~$</span>
              <input 
                type="text" 
                value={terminalInput}
                onChange={(e) => setTerminalInput(e.target.value)}
                onKeyPress={(e) => e.key === 'Enter' && sendTerminalCommand()}
                className="flex-1 bg-transparent border-none outline-none text-white"
                aria-label="Terminal input"
                autoFocus
              />
            </div>
          </div>
        ) : (
          <div className="p-8" role="region" aria-label="Memory Hub">

            <h2 className="text-2xl font-bold mb-6">Hierarchical Memory</h2>
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
              <div className="bg-[#1e2330] p-6 rounded-2xl border border-gray-800">
                <h3 className="text-lg font-semibold mb-4 flex items-center gap-2">
                  <span className="text-blue-400">&#128193;</span> Categories
                </h3>
                <ul className="space-y-2 text-sm text-gray-400">
                  {categories.map((cat, idx) => (
                    <li key={idx}>{cat}</li>
                  ))}
                </ul>
              </div>
              <div className="bg-[#1e2330] p-6 rounded-2xl border border-gray-800 col-span-2">
                <div className="flex justify-between items-center mb-4">
                  <h3 className="text-lg font-semibold">Recent Memory Items</h3>
                  <button 
                    onClick={() => searchMemory('all')}
                    className="text-xs bg-gray-800 hover:bg-gray-700 px-2 py-1 rounded text-gray-400"
                  >
                    Refresh
                  </button>
                </div>
                <div className="space-y-4">
                  {searchResults.length === 0 ? (
                    <p className="text-gray-600">No recent items. Try searching above.</p>
                  ) : (
                    searchResults.map((item, idx) => (
                      <div key={idx} className="p-3 bg-[#0f1117] rounded-lg border border-gray-700 text-sm">
                        {item.content}
                      </div>
                    ))
                  )}
                </div>
              </div>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}

export default App;
