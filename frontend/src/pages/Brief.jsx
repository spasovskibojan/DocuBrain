import { useState, useEffect } from 'react';
import { Zap } from 'lucide-react';
import api from '../services/api';

export default function Brief() {
  const [documents, setDocuments] = useState([]);
  const [selectedDocId, setSelectedDocId] = useState('');
  const [loadingDocs, setLoadingDocs] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState('');

  useEffect(() => {
    api.get('/documents/').then(res => {
      setDocuments(res.data.documents || []);
      setLoadingDocs(false);
    });
  }, []);

  const handleGenerate = async (e) => {
    e.preventDefault();
    if (!selectedDocId) return;
    setGenerating(true);
    setError('');
    setResult(null);

    try {
      const res = await api.post(`/workflows/executive-brief?document_id=${selectedDocId}`);
      setResult(res.data.brief);
    } catch (err) {
      setError('Failed to generate brief.');
    } finally {
      setGenerating(false);
    }
  };

  return (
    <div className="container py-4">
      <h2 className="fw-bold mb-4 d-flex align-items-center gap-2">
        <Zap className="text-danger" size={28} /> Executive Brief
      </h2>
      
      <div className="row g-4">
        <div className="col-md-4">
          <div className="glass-card p-4">
            <h5 className="fw-bold mb-3">Target Document</h5>
            <form onSubmit={handleGenerate}>
              <select className="form-select mb-3" value={selectedDocId} onChange={e => setSelectedDocId(e.target.value)} required>
                <option value="" disabled>{loadingDocs ? 'Loading...' : 'Select document...'}</option>
                {documents.map(doc => <option key={doc.id} value={doc.id}>{doc.filename}</option>)}
              </select>
              <button className="btn btn-danger w-100" disabled={!selectedDocId || generating}>
                {generating ? 'Analyzing...' : 'Generate Brief'}
              </button>
            </form>
            {error && <div className="alert alert-danger mt-3 py-2 small">{error}</div>}
          </div>
        </div>
        <div className="col-md-8">
          <div className="glass-card p-4 h-100">
            <h5 className="fw-bold mb-3">AI Summary</h5>
            <div className="bg-light rounded p-3" style={{minHeight: '200px', whiteSpace: 'pre-wrap'}}>
              {result || (generating ? 'Reading document...' : 'Waiting for document...')}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
