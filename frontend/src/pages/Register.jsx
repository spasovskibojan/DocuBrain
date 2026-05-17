import { useState } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import api from '../services/api';

export default function Register() {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [companyName, setCompanyName] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();

  const handleRegister = async (e) => {
    e.preventDefault();
    setLoading(true);
    setError('');
    
    try {
      // Step 1: Register User
      await api.post('/auth/register', {
        email: email,
        password: password,
        company_name: companyName
      });
      
      // Step 2: Auto-login after successful registration
      const formData = new URLSearchParams();
      formData.append('username', email);
      formData.append('password', password);

      const loginResponse = await api.post('/auth/login', {
        email: email,
        password: password
      });
      
      localStorage.setItem('token', loginResponse.data.access_token);
      navigate('/dashboard');
    } catch (err) {
      const detail = err.response?.data?.detail;
      if (Array.isArray(detail)) {
        setError(detail.map(e => e.msg).join(', '));
      } else {
        setError(detail || 'Failed to register account');
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="container d-flex justify-content-center align-items-center" style={{minHeight: '80vh'}}>
      <div className="glass-card p-5" style={{width: '100%', maxWidth: '400px'}}>
        <div className="text-center mb-4">
          <h2 className="fw-bold mb-1">Create Account</h2>
          <p className="text-secondary">Join DocuBrain for your firm</p>
        </div>
        
        {error && <div className="alert alert-danger py-2">{error}</div>}
        
        <form onSubmit={handleRegister}>
          <div className="mb-3">
            <label className="form-label text-secondary small">Company Name (Optional)</label>
            <input 
              type="text" 
              className="form-control" 
              value={companyName}
              onChange={(e) => setCompanyName(e.target.value)}
            />
          </div>
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
              minLength={6}
            />
          </div>
          <button type="submit" className="btn btn-primary w-100 py-2 mb-3" disabled={loading}>
            {loading ? 'Creating account...' : 'Register'}
          </button>
          
          <div className="text-center">
            <p className="text-secondary small mb-0">
              Already have an account? <Link to="/login" className="text-accent text-decoration-none">Sign in</Link>
            </p>
          </div>
        </form>
      </div>
    </div>
  );
}
