import { Routes, Route, Navigate } from 'react-router-dom';
import { Spin } from 'antd';
import { AuthProvider, useAuth } from './auth';
import Layout from './components/Layout';
import Login from './pages/Login';
import Dashboard from './pages/Dashboard';
import DataExplorer from './pages/DataExplorer';
import WorkflowActions from './pages/WorkflowActions';
import AgentChat from './pages/AgentChat';
import DocHistory from './pages/DocHistory';
import Admin from './pages/Admin';
import FlowEditor from './pages/FlowEditor';
import NodeView from './pages/NodeView';
import MyTodos from './pages/MyTodos';
import BusinessPortal from './pages/BusinessPortal';
import OrderChainMonitor from './pages/OrderChainMonitor';
import ErrorBoundary from './components/ErrorBoundary';

function Protected({ children }) {
  const { user, loading } = useAuth();
  if (loading) return <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100vh' }}><Spin size="large" /></div>;
  if (!user) return <Navigate to="/login" />;
  return children;
}

function AppRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/" element={<Protected><Layout /></Protected>}>
        <Route index element={<Dashboard />} />
        <Route path="crm" element={<BusinessPortal type="crm" />} />
        <Route path="erp" element={<BusinessPortal type="erp" />} />
        <Route path="wms" element={<BusinessPortal type="wms" />} />
        <Route path="order-chain" element={<OrderChainMonitor />} />
        <Route path="todos" element={<MyTodos />} />
        <Route path="data" element={<DataExplorer />} />
        <Route path="data/:table" element={<DataExplorer />} />
        <Route path="actions" element={<WorkflowActions />} />
        <Route path="actions/:workflowId" element={<WorkflowActions />} />
        <Route path="agent" element={<AgentChat />} />
        <Route path="history/:docType/:docId" element={<DocHistory />} />
        <Route path="node/:workflowId/:stateCode" element={<NodeView />} />
        <Route path="admin" element={<Admin />} />
        <Route path="flow-editor" element={<ErrorBoundary><FlowEditor /></ErrorBoundary>} />
      </Route>
    </Routes>
  );
}

export default function App() {
  return (
    <AuthProvider>
      <AppRoutes />
    </AuthProvider>
  );
}
