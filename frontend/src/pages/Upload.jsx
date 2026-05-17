import { useState, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { Upload as UploadIcon, FileText, CheckCircle } from 'lucide-react';
import api from '../services/api';

export default function Upload() {
  const [file, setFile] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState(false);
  const fileInputRef = useRef(null);
  const navigate = useNavigate();

  const handleFileSelect = (e) => {
    const selectedFile = e.target.files[0];
    if (selectedFile && selectedFile.type === 'application/pdf') {
      setFile(selectedFile);
      setError('');
    } else {
      setError('Please select a valid PDF file.');
      setFile(null);
    }
  };

  const handleUpload = async () => {
    if (!file) return;
    setLoading(true);
    setError('');
    
    const formData = new FormData();
    formData.append('file', file);

    try {
      await api.post('/documents/upload', formData, {
        headers: { 'Content-Type': 'multipart/form-data' }
      });
      setSuccess(true);
      setTimeout(() => navigate('/dashboard'), 2000);
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to upload document');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="container py-4 d-flex justify-content-center">
      <div className="glass-card p-5 text-center" style={{width: '100%', maxWidth: '600px', marginTop: '5vh'}}>
        <h2 className="fw-bold mb-1">Upload Document</h2>
        <p className="text-secondary mb-5">Process a new PDF for the AI to read</p>

        {success ? (
          <div className="py-5">
            <CheckCircle size={64} className="text-success mb-3" />
            <h4 className="text-success">Upload Complete!</h4>
            <p className="text-secondary">Vectors generated and saved. Redirecting...</p>
          </div>
        ) : (
          <>
            <input 
              type="file" 
              ref={fileInputRef} 
              onChange={handleFileSelect} 
              accept="application/pdf" 
              className="d-none" 
            />
            
            <div 
              className="border border-2 border-dashed rounded-4 p-5 mb-4"
              style={{borderColor: 'var(--border-color)', cursor: 'pointer', backgroundColor: '#f1f5f9'}}
              onClick={() => fileInputRef.current.click()}
            >
              {file ? (
                <>
                  <FileText size={48} className="text-primary mb-3" />
                  <h5>{file.name}</h5>
                  <p className="text-secondary small mb-0">{(file.size / 1024 / 1024).toFixed(2)} MB</p>
                </>
              ) : (
                <>
                  <UploadIcon size={48} className="text-secondary mb-3 opacity-50" />
                  <h5>Click to select PDF</h5>
                  <p className="text-secondary small mb-0">Max file size 20MB</p>
                </>
              )}
            </div>

            {error && <div className="alert alert-danger py-2">{error}</div>}

            <button 
              className="btn btn-primary w-100 py-3 d-flex align-items-center justify-content-center gap-2"
              disabled={!file || loading}
              onClick={handleUpload}
            >
              {loading ? (
                <><div className="spinner-border spinner-border-sm"></div> Processing Vectors...</>
              ) : (
                <><UploadIcon size={20} /> Process Document</>
              )}
            </button>
          </>
        )}
      </div>
    </div>
  );
}
