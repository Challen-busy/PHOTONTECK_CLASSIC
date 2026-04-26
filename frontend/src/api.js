import axios from 'axios';

const api = axios.create({ baseURL: '/api', withCredentials: true });

api.interceptors.response.use(
  r => r,
  err => {
    if (err.response?.status === 401 && !window.location.pathname.startsWith('/login')) {
      window.location.href = '/login';
    }
    return Promise.reject(err);
  }
);

export default api;

// 通用查询
export const query = (table, opts = {}) => api.post('/query', { table, ...opts });
export const aggregate = (table, field, func, opts = {}) => api.post('/aggregate', { table, field, function: func, ...opts });
export const transition = (data) => api.post('/transition', data);
export const getTransitions = () => api.get('/transitions');
export const getHistory = (docType, docId) => api.get(`/history/${docType}/${docId}`);
export const agentChat = (q) => api.post('/agent/chat', { query: q });
export const previewTransition = (data) => api.post('/transition/preview', data);
export const commitTransition = (card, comment = '') => api.post('/transition/commit', { card, comment });
export const getWorkflows = () => api.get('/workflows');
export const getKnowledge = () => api.get('/knowledge');
export const getMyTodos = () => api.get('/my-todos');
export const getOrderChains = (params = {}) => api.get('/order-chains', { params });
