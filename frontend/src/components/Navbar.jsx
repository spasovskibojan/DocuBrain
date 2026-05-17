import { Link, useNavigate } from 'react-router-dom';
import { LogOut, LayoutDashboard, Upload, MessageSquare, Zap } from 'lucide-react';

export default function Navbar() {
  const navigate = useNavigate();
  const token = localStorage.getItem('token');

  const handleLogout = () => {
    localStorage.removeItem('token');
    navigate('/login');
  };

  return (
    <nav className="navbar navbar-expand-lg navbar-dark py-3">
      <div className="container">
        <Link className="navbar-brand fw-bold fs-4 d-flex align-items-center gap-2" to="/">
          <div style={{width: 32, height: 32, borderRadius: 8, background: 'var(--accent-color)', display: 'flex', alignItems: 'center', justifyContent: 'center'}}>
            <span className="text-white fs-5">D</span>
          </div>
          DocuBrain AI
        </Link>
        
        {token && (
          <div className="d-flex align-items-center gap-4">
            <Link to="/dashboard" className="nav-link text-white d-flex align-items-center gap-2">
              <LayoutDashboard size={18} /> Library
            </Link>
            <Link to="/workflows" className="nav-link text-white d-flex align-items-center gap-2">
              <Zap size={18} /> AI Tools
            </Link>
            <Link to="/upload" className="nav-link text-white d-flex align-items-center gap-2">
              <Upload size={18} /> Upload
            </Link>
            <Link to="/chat" className="nav-link text-white d-flex align-items-center gap-2">
              <MessageSquare size={18} /> AI Chat
            </Link>
            <button onClick={handleLogout} className="btn btn-outline-danger btn-sm d-flex align-items-center gap-2 ms-3">
              <LogOut size={16} /> Logout
            </button>
          </div>
        )}
      </div>
    </nav>
  );
}
