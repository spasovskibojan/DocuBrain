import { useState, useRef, useEffect } from 'react';
import { Send, Bot, User, FileText, Trash2 } from 'lucide-react';
import api from '../services/api';

export default function Chat() {
  const [messages, setMessages] = useState([
    { role: 'ai', content: 'Hello! Ask me anything about the documents you uploaded.', sources: null }
  ]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const endOfMessagesRef = useRef(null);

  useEffect(() => {
    fetchHistory();
  }, []);

  const fetchHistory = async () => {
    try {
      const response = await api.get('/query/history');
      if (response.data && response.data.length > 0) {
        const historyMessages = [];
        response.data.forEach(item => {
          historyMessages.push({ role: 'user', content: item.question, sources: null });
          historyMessages.push({ role: 'ai', content: item.answer, sources: item.source_chunks });
        });
        setMessages([
          { role: 'ai', content: 'Hello! Ask me anything about the documents you uploaded.', sources: null },
          ...historyMessages
        ]);
      }
    } catch (err) {
      console.error('Failed to load chat history', err);
    }
  };

  const handleClearChat = async () => {
    if (!window.confirm('Are you sure you want to clear your chat history?')) return;
    
    try {
      await api.delete('/query/history');
      setMessages([{ role: 'ai', content: 'Hello! Ask me anything about the documents you uploaded.', sources: null }]);
    } catch (err) {
      console.error('Failed to clear chat history', err);
    }
  };

  useEffect(() => {
    endOfMessagesRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const handleSend = async (e) => {
    e.preventDefault();
    if (!input.trim()) return;

    const userMessage = input;
    setInput('');
    setMessages(prev => [...prev, { role: 'user', content: userMessage, sources: null }]);
    setLoading(true);

    try {
      const response = await api.post('/query/ask', {
        question: userMessage,
        document_id: null
      });

      setMessages(prev => [
        ...prev, 
        { 
          role: 'ai', 
          content: response.data.answer, 
          sources: response.data.sources 
        }
      ]);
    } catch (err) {
      setMessages(prev => [...prev, { role: 'ai', content: 'Sorry, I encountered an error answering that.', sources: null }]);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="container py-2" style={{height: 'calc(100vh - 100px)'}}>
      <div className="glass-card d-flex flex-column h-100 overflow-hidden">
        {/* Chat Header */}
        <div className="p-4 border-bottom d-flex justify-content-between align-items-center" style={{borderColor: 'var(--border-color)'}}>
          <h5 className="mb-0 fw-bold d-flex align-items-center gap-2">
            <Bot className="text-primary" /> AI Assistant
          </h5>
          <button 
            onClick={handleClearChat}
            className="btn btn-sm btn-outline-danger d-flex align-items-center gap-1"
            title="Clear Chat History"
          >
            <Trash2 size={14} /> Clear
          </button>
        </div>

        {/* Chat Messages */}
        <div className="flex-grow-1 overflow-auto p-4 d-flex flex-column gap-4">
          {messages.map((msg, idx) => (
            <div key={idx} className={`d-flex flex-column ${msg.role === 'user' ? 'align-items-end' : 'align-items-start'}`}>
              <div className="d-flex align-items-end gap-2 mb-1">
                {msg.role === 'ai' && <div className="bg-primary bg-opacity-25 p-2 rounded-circle"><Bot size={16} className="text-primary" /></div>}
                <div className={msg.role === 'user' ? 'chat-user' : 'chat-ai'}>
                  <div style={{whiteSpace: 'pre-wrap'}}>{msg.content}</div>
                </div>
                {msg.role === 'user' && <div className="bg-secondary p-2 rounded-circle"><User size={16} className="text-white" /></div>}
              </div>

              {/* Source Citations */}
              {msg.sources && msg.sources.length > 0 && (
                <div className="ms-5 ps-2 mt-2 d-flex flex-wrap gap-2">
                  <span className="text-secondary small me-1">Sources:</span>
                  {msg.sources.map((source, i) => (
                    <div key={i} className="source-badge d-flex align-items-center gap-1" title={source.chunk_text}>
                      <FileText size={12} />
                      {source.document_name} (Pg {source.page_number})
                    </div>
                  ))}
                </div>
              )}
            </div>
          ))}
          {loading && (
            <div className="d-flex align-items-end gap-2">
              <div className="bg-primary bg-opacity-25 p-2 rounded-circle"><Bot size={16} className="text-primary" /></div>
              <div className="chat-ai text-secondary">
                <div className="spinner-grow spinner-grow-sm me-1" role="status"></div>
                <div className="spinner-grow spinner-grow-sm me-1" role="status"></div>
                <div className="spinner-grow spinner-grow-sm" role="status"></div>
              </div>
            </div>
          )}
          <div ref={endOfMessagesRef} />
        </div>

        {/* Input Area */}
        <div className="p-3 border-top" style={{backgroundColor: '#f1f5f9', borderColor: 'var(--border-color)'}}>
          <form onSubmit={handleSend} className="d-flex gap-2">
            <input
              type="text"
              className="form-control rounded-pill px-4"
              placeholder="Ask a question about your documents..."
              value={input}
              onChange={(e) => setInput(e.target.value)}
              disabled={loading}
              style={{backgroundColor: '#ffffff', color: 'var(--text-primary)', border: '1px solid var(--border-color)'}}
            />
            <button 
              type="submit" 
              className="btn btn-primary rounded-circle d-flex align-items-center justify-content-center p-0"
              style={{width: '46px', height: '46px'}}
              disabled={!input.trim() || loading}
            >
              <Send size={18} />
            </button>
          </form>
        </div>
      </div>
    </div>
  );
}
