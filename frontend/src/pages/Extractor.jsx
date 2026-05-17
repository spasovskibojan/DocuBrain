import { useState, useEffect, useRef } from 'react';
import { Link } from 'react-router-dom';
import { FileSpreadsheet, Download, Upload as UploadIcon, Loader2 } from 'lucide-react';
import api from '../services/api';

export default function Extractor() {
  const [documents, setDocuments] = useState([]);
  const [selectedDocId, setSelectedDocId] = useState('');
  const [loadingDocs, setLoadingDocs] = useState(true);
  const [extracting, setExtracting] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [results, setResults] = useState(null);
  const [error, setError] = useState('');
  const fileInputRef = useRef(null);

  useEffect(() => {
    fetchDocuments();
  }, []);

  const fetchDocuments = async () => {
    try {
      const response = await api.get('/documents/');
      setDocuments(response.data.documents || []);
    } catch (err) {
      console.error('Error fetching documents', err);
    } finally {
      setLoadingDocs(false);
    }
  };

  const handleExtract = async (e) => {
    e.preventDefault();
    if (!selectedDocId) return;

    setExtracting(true);
    setError('');
    setResults(null);

    try {
      const response = await api.post(`/workflows/extract-invoice?document_id=${selectedDocId}`);
      setResults(response.data);
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to extract data. Ensure the document is an invoice.');
    } finally {
      setExtracting(false);
    }
  };

  const handleQuickUpload = async (e) => {
    const file = e.target.files[0];
    if (!file || file.type !== 'application/pdf') {
      setError('Please select a valid PDF file.');
      return;
    }

    setUploading(true);
    setError('');
    
    const formData = new FormData();
    formData.append('file', file);

    try {
      const response = await api.post('/documents/upload', formData, {
        headers: { 'Content-Type': 'multipart/form-data' }
      });
      // Refresh documents list
      await fetchDocuments();
      // Auto-select the newly uploaded document
      setSelectedDocId(response.data.id);
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to upload document');
    } finally {
      setUploading(false);
      // Reset input so they can upload the same file again if needed
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  };

  const downloadCSV = () => {
    if (!results) return;
    const headers = ['Vendor Name', 'Invoice Date', 'Total Amount', 'Tax Amount'];
    const row = [
      results.vendor_name || 'N/A',
      results.invoice_date || 'N/A',
      results.total_amount || 'N/A',
      results.tax_amount || 'N/A'
    ];
    
    const csvContent = "data:text/csv;charset=utf-8," 
      + headers.join(",") + "\n"
      + row.map(v => `"${v}"`).join(",");
      
    const encodedUri = encodeURI(csvContent);
    const link = document.createElement("a");
    link.setAttribute("href", encodedUri);
    link.setAttribute("download", "extracted_invoice_data.csv");
    document.body.appendChild(link);
    link.click();
  };

  return (
    <div className="container py-4">
      <div className="mb-4">
        <h2 className="fw-bold mb-1 d-flex align-items-center gap-2">
          <FileSpreadsheet className="text-success" size={28} /> Invoice Extractor
        </h2>
        <p className="text-secondary">Automatically pull structured data from your uploaded invoices.</p>
      </div>

      <div className="row g-4">
        <div className="col-md-5">
          <div className="glass-card p-4">
            <h5 className="fw-bold mb-4">1. Select an Invoice</h5>
            
            <form onSubmit={handleExtract}>
              <div className="mb-4">
                <label className="form-label text-secondary small">Document from Library</label>
                {loadingDocs ? (
                  <div className="text-secondary small">Loading library...</div>
                ) : documents.length === 0 ? (
                  <div className="alert alert-warning py-2 small mb-2">
                    Your library is empty. Please upload an invoice to extract data.
                  </div>
                ) : (
                  <select 
                    className="form-select bg-white mb-2" 
                    value={selectedDocId}
                    onChange={(e) => setSelectedDocId(e.target.value)}
                    required
                  >
                    <option value="" disabled>Select a document...</option>
                    {documents.map(doc => (
                      <option key={doc.id} value={doc.id}>{doc.filename}</option>
                    ))}
                  </select>
                )}
                
                <input 
                  type="file" 
                  ref={fileInputRef} 
                  onChange={handleQuickUpload} 
                  accept="application/pdf" 
                  className="d-none" 
                />
                
                <div className="text-end">
                  <button 
                    type="button"
                    onClick={() => fileInputRef.current?.click()}
                    className="btn btn-link text-decoration-none small p-0 d-flex align-items-center justify-content-end gap-1 ms-auto"
                    disabled={uploading}
                  >
                    {uploading ? (
                      <><Loader2 size={14} className="spin" /> Uploading & Processing...</>
                    ) : (
                      <><UploadIcon size={14} /> Upload new document inline</>
                    )}
                  </button>
                </div>
              </div>
              
              <button 
                type="submit" 
                className="btn btn-success w-100 py-2 d-flex align-items-center justify-content-center gap-2"
                disabled={!selectedDocId || extracting}
              >
                {extracting ? (
                  <><div className="spinner-border spinner-border-sm text-light"></div> Reading document...</>
                ) : (
                  <><FileSpreadsheet size={18} /> Extract Data</>
                )}
              </button>
            </form>
            
            {error && <div className="alert alert-danger mt-3 py-2 small">{error}</div>}
          </div>
        </div>

        <div className="col-md-7">
          <div className="glass-card p-4 h-100 d-flex flex-column">
            <div className="d-flex justify-content-between align-items-center mb-4">
              <h5 className="fw-bold mb-0">2. Extracted Data</h5>
              {results && (
                <button onClick={downloadCSV} className="btn btn-sm btn-outline-success d-flex align-items-center gap-1">
                  <Download size={14} /> Download CSV
                </button>
              )}
            </div>

            {results ? (
              <div className="bg-light rounded p-3 flex-grow-1">
                <table className="table table-borderless mb-0">
                  <tbody>
                    <tr>
                      <td className="text-secondary w-50 pb-3">Vendor Name:</td>
                      <td className="fw-bold pb-3">{results.vendor_name || <span className="text-muted fst-italic">Not found</span>}</td>
                    </tr>
                    <tr>
                      <td className="text-secondary pb-3">Invoice Date:</td>
                      <td className="fw-bold pb-3">{results.invoice_date || <span className="text-muted fst-italic">Not found</span>}</td>
                    </tr>
                    <tr>
                      <td className="text-secondary pb-3">Total Amount:</td>
                      <td className="fw-bold text-success pb-3">{results.total_amount || <span className="text-muted fst-italic">Not found</span>}</td>
                    </tr>
                    <tr>
                      <td className="text-secondary pb-0">Tax / VAT:</td>
                      <td className="fw-bold text-danger pb-0">{results.tax_amount || <span className="text-muted fst-italic">Not found</span>}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="d-flex align-items-center justify-content-center h-100 bg-light rounded text-secondary border border-dashed" style={{minHeight: '200px'}}>
                {extracting ? 'AI is analyzing the invoice...' : 'Waiting for extraction...'}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
