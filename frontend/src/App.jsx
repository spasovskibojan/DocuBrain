import { BrowserRouter as Router, Routes, Route, Navigate } from 'react-router-dom';
import Navbar from './components/Navbar';
import Login from './pages/Login';
import Register from './pages/Register';
import Dashboard from './pages/Dashboard';
import Upload from './pages/Upload';
import Chat from './pages/Chat';
import Workflows from './pages/Workflows';
import Extractor from './pages/Extractor';
import Brief from './pages/Brief';
import Diff from './pages/Diff';

// Protected Route Wrapper
const ProtectedRoute = ({ children }) => {
  const token = localStorage.getItem('token');
  if (!token) return <Navigate to="/login" replace />;
  return children;
};

function App() {
  return (
    <Router>
      <div className="min-vh-100 d-flex flex-column">
        <Navbar />
        <main className="flex-grow-1 p-4">
          <Routes>
            <Route path="/" element={<Navigate to="/dashboard" replace />} />
            <Route path="/login" element={<Login />} />
            <Route path="/register" element={<Register />} />
            <Route 
              path="/dashboard" 
              element={<ProtectedRoute><Dashboard /></ProtectedRoute>} 
            />
            <Route 
              path="/upload" 
              element={<ProtectedRoute><Upload /></ProtectedRoute>} 
            />
            <Route 
              path="/chat" 
              element={<ProtectedRoute><Chat /></ProtectedRoute>} 
            />
            <Route 
              path="/workflows" 
              element={<ProtectedRoute><Workflows /></ProtectedRoute>} 
            />
            <Route 
              path="/workflows/extractor" 
              element={<ProtectedRoute><Extractor /></ProtectedRoute>} 
            />
            <Route 
              path="/workflows/brief" 
              element={<ProtectedRoute><Brief /></ProtectedRoute>} 
            />
            <Route 
              path="/workflows/diff" 
              element={<ProtectedRoute><Diff /></ProtectedRoute>} 
            />
          </Routes>
        </main>
      </div>
    </Router>
  );
}

export default App;
