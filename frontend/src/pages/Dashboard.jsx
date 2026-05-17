import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { FileText, Plus, Trash2 } from 'lucide-react';
import api from '../services/api';

export default function Dashboard() {
  const [documents, setDocuments] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchDocuments();
  }, []);

  const fetchDocuments = async () => {
    try {
      const response = await api.get('/documents/');
      // FastAPI returns { documents: [...], total: n }
      setDocuments(response.data.documents || []);
    } catch (err) {
      console.error('Error fetching documents', err);
    } finally {
      setLoading(false);
    }
  };

  const handleDelete = async (docId) => {
    if (!window.confirm("Are you sure you want to delete this document and its AI vectors?")) return;
    try {
      await api.delete(`/documents/${docId}`);
      setDocuments(prev => prev.filter(doc => doc.id !== docId));
    } catch (err) {
      console.error('Failed to delete document', err);
      alert('Failed to delete document');
    }
  };

  const formatDate = (dateString) => {
    return new Date(dateString).toLocaleDateString('en-US', {
      year: 'numeric', month: 'short', day: 'numeric'
    });
  };

  if (loading) {
    return <div className="text-center mt-5"><div className="spinner-border text-primary" role="status"></div></div>;
  }

  return (
    <div className="container py-4">
      <div className="d-flex justify-content-between align-items-center mb-5">
        <div>
          <h2 className="fw-bold mb-1">Document Library</h2>
          <p className="text-secondary mb-0">Manage and chat with your files</p>
        </div>
        <Link to="/upload" className="btn btn-primary d-flex align-items-center gap-2">
          <Plus size={20} /> Upload PDF
        </Link>
      </div>

      {documents.length === 0 ? (
        <div className="glass-card text-center py-5">
          <FileText size={48} className="text-secondary mb-3 opacity-50" />
          <h5>No documents yet</h5>
          <p className="text-secondary mb-4">Upload your first PDF to start chatting with it.</p>
          <Link to="/upload" className="btn btn-outline-primary">Upload Document</Link>
        </div>
      ) : (
        <div className="row g-4">
          {documents.map(doc => (
            <div key={doc.id} className="col-md-4 col-lg-3">
              <div className="glass-card h-100 p-4 transition-transform hover-scale">
                <div className="d-flex justify-content-between align-items-start mb-3">
                  <div className="bg-primary bg-opacity-10 p-2 rounded-3 text-primary">
                    <FileText size={24} />
                  </div>
                  <button 
                    onClick={() => handleDelete(doc.id)} 
                    className="btn btn-sm btn-link text-danger p-0"
                    title="Delete document"
                  >
                    <Trash2 size={18} />
                  </button>
                </div>
                <h6 className="fw-bold text-truncate mb-1" title={doc.filename}>{doc.filename}</h6>
                <div className="d-flex justify-content-between text-secondary small mt-3">
                  <span>{(doc.file_size_bytes / 1024 / 1024).toFixed(2)} MB</span>
                  <span>{formatDate(doc.uploaded_at)}</span>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
