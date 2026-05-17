import { useState } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import api from '../services/api';

export default function Login() {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();

  const handleLogin = async (e) => {
    e.preventDefault();
    setLoading(true);
    setError('');
    
    try {
      const response = await api.post('/auth/login', {
        email: email,
        password: password
      });
      
      localStorage.setItem('token', response.data.access_token);
      navigate('/dashboard');
    } catch (err) {
      const detail = err.response?.data?.detail;
      // If FastAPI returns a Pydantic validation error (array of objects), stringify it
      if (Array.isArray(detail)) {
        setError(detail.map(e => e.msg).join(', '));
      } else {
        setError(detail || 'Failed to login');
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="container d-flex justify-content-center align-items-center" style={{minHeight: '80vh'}}>
      <div className="glass-card p-5" style={{width: '100%', maxWidth: '400px'}}>
        <div className="text-center mb-4">
          <h2 className="fw-bold mb-1">Welcome Back</h2>
          <p className="text-secondary">Sign in to your DocuBrain account</p>
        </div>
        
        {error && <div className="alert alert-danger py-2">{error}</div>}
        
        <form onSubmit={handleLogin}>
          <div className="mb-3">
            <label className="form-label text-secondary small">Email address</label>
            <input 
              type="email" 
              className="form-control" 
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required 
            />
          </div>
          <div className="mb-4">
            <label className="form-label text-secondary small">Password</label>
            <input 
              type="password" 
              className="form-control" 
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required 
            />
          </div>
          <button type="submit" className="btn btn-primary w-100 py-2 mb-3" disabled={loading}>
            {loading ? 'Authenticating...' : 'Sign In'}
          </button>
          
          <div className="text-center">
            <p className="text-secondary small mb-0">
              Don't have an account? <Link to="/register" className="text-accent text-decoration-none">Create one</Link>
            </p>
          </div>
        </form>
      </div>
    </div>
  );
}
