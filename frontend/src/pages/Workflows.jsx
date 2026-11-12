import { Link } from 'react-router-dom';
import { FileText, FileSpreadsheet, Scale, Zap } from 'lucide-react';

export default function Workflows() {
  const tools = [
    {
      id: 'chat',
      title: 'Document Chat',
      description: 'Ask questions across your document library and get answers with their source pages.',
      icon: <FileText size={32} className="text-primary" />,
      link: '/chat',
      status: 'Active'
    },
    {
      id: 'extractor',
      title: 'Invoice Extractor',
      description: 'Extract the vendor, date, total and tax from an invoice as structured data.',
      icon: <FileSpreadsheet size={32} className="text-success" />,
      link: '/workflows/extractor',
      status: 'Active'
    },
    {
      id: 'compare',
      title: 'Contract Diff',
      description: 'Compare two short documents, such as contract versions, and list their differences.',
      icon: <Scale size={32} className="text-warning" />,
      link: '/workflows/diff',
      status: 'Active'
    },
    {
      id: 'summary',
      title: 'Executive Brief',
      description: 'Get a three-point summary of a short document.',
      icon: <Zap size={32} className="text-danger" />,
      link: '/workflows/brief',
      status: 'Active'
    }
  ];

  return (
    <div className="container py-4">
      <div className="mb-5">
        <h2 className="fw-bold mb-1">AI Workflows</h2>
        <p className="text-secondary mb-0">Select an automated tool to process your documents.</p>
      </div>

      <div className="row g-4">
        {tools.map(tool => (
          <div key={tool.id} className="col-md-6">
            <Link 
              to={tool.link} 
              className={`text-decoration-none ${tool.status === 'Coming Soon' ? 'pe-none opacity-75' : ''}`}
            >
              <div className="glass-card h-100 p-4 transition-transform hover-scale">
                <div className="d-flex justify-content-between align-items-start mb-4">
                  <div className={`bg-opacity-10 p-3 rounded-4 ${
                    tool.id === 'chat' ? 'bg-primary' : 
                    tool.id === 'extractor' ? 'bg-success' : 
                    tool.id === 'compare' ? 'bg-warning' : 'bg-danger'
                  }`}>
                    {tool.icon}
                  </div>
                  <span className={`badge ${tool.status === 'Active' ? 'bg-primary' : 'bg-secondary'}`}>
                    {tool.status}
                  </span>
                </div>
                <h5 className="fw-bold text-dark mb-2">{tool.title}</h5>
                <p className="text-secondary mb-0">{tool.description}</p>
              </div>
            </Link>
          </div>
        ))}
      </div>
    </div>
  );
}
