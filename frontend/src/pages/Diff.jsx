import { useState, useEffect } from 'react';
import { Scale } from 'lucide-react';
import api from '../services/api';

export default function Diff() {
  const [documents, setDocuments] = useState([]);
  const [doc1Id, setDoc1Id] = useState('');
  const [doc2Id, setDoc2Id] = useState('');
  const [loadingDocs, setLoadingDocs] = useState(true);
  const [comparing, setComparing] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState('');

  useEffect(() => {
    api.get('/documents/').then(res => {
      setDocuments(res.data.documents || []);
      setLoadingDocs(false);
    });
  }, []);

  const handleCompare = async (e) => {
    e.preventDefault();
    if (!doc1Id || !doc2Id) return;
    setComparing(true);
    setError('');
    setResult(null);

    try {
      const res = await api.post(`/workflows/contract-diff?doc1_id=${doc1Id}&doc2_id=${doc2Id}`);
      setResult(res.data.diff);
    } catch (err) {
      setError('Failed to compare documents.');
    } finally {
      setComparing(false);
    }
  };

  return (
    <div className="container py-4">
      <h2 className="fw-bold mb-4 d-flex align-items-center gap-2">
        <Scale className="text-warning" size={28} /> Contract Diff
      </h2>
      
      <div className="row g-4">
        <div className="col-md-4">
          <div className="glass-card p-4">
            <h5 className="fw-bold mb-3">Select Documents</h5>
            <form onSubmit={handleCompare}>
              <select className="form-select mb-3" value={doc1Id} onChange={e => setDoc1Id(e.target.value)} required>
                <option value="" disabled>{loadingDocs ? 'Loading...' : 'Select Base Document...'}</option>
                {documents.map(doc => <option key={doc.id} value={doc.id}>{doc.filename}</option>)}
              </select>
              
              <select className="form-select mb-4" value={doc2Id} onChange={e => setDoc2Id(e.target.value)} required>
                <option value="" disabled>{loadingDocs ? 'Loading...' : 'Select Comparison Document...'}</option>
                {documents.map(doc => <option key={doc.id} value={doc.id}>{doc.filename}</option>)}
              </select>

              <button className="btn btn-warning w-100" disabled={!doc1Id || !doc2Id || comparing}>
                {comparing ? 'Auditing...' : 'Compare Documents'}
              </button>
            </form>
            {error && <div className="alert alert-danger mt-3 py-2 small">{error}</div>}
          </div>
        </div>
        <div className="col-md-8">
          <div className="glass-card p-4 h-100">
            <h5 className="fw-bold mb-3">Audit Results</h5>
            <div className="bg-light rounded p-3" style={{minHeight: '200px', whiteSpace: 'pre-wrap'}}>
              {result || (comparing ? 'Analyzing semantic differences...' : 'Waiting for documents...')}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
