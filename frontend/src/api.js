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
export const getSchema = (table) => api.get(`/schema/${table}`);
export const transition = (data) => api.post('/transition', data);
// 公司切换（后端已实现，决策B：仅在已开通公司间切换，重写会话 active_company_id）
export const switchCompany = (companyId) => api.post('/me/switch-company', { company_id: companyId });
export const getTransitions = () => api.get('/transitions');
export const getHistory = (docType, docId) => api.get(`/history/${docType}/${docId}`);
export const agentChat = (q) => api.post('/agent/chat', { query: q });
export const previewTransition = (data) => api.post('/transition/preview', data);
export const commitTransition = (card, comment = '') => api.post('/transition/commit', { card, comment });
export const getWorkflows = () => api.get('/workflows');
export const getKnowledge = () => api.get('/knowledge');
export const getMyTodos = () => api.get('/my-todos');
export const getOrderChains = (params = {}) => api.get('/order-chains', { params });
export const getCommandCatalog = () => api.get('/commands/catalog');
export const getCommandFailureSummary = (params = {}) => api.get('/commands/failures/summary', { params });
export const getCommandLogs = (params = {}) => api.get('/commands/logs', { params });
export const getCommandDetail = (id) => api.get(`/commands/logs/${id}`);
export const getCommandInventoryMovements = (id) => api.get(`/commands/logs/${id}/inventory-movements`);
export const retryCommandLog = (id) => api.post(`/commands/logs/${id}/retry`);

// WMS 一期
export const getWmsSummary = () => api.get('/wms/summary');
export const getWmsInventory = (params = {}) => api.get('/wms/inventory', { params });
export const getWmsReservations = (params = {}) => api.get('/wms/reservations', { params });
export const getWmsCommandAudit = (params = {}) => api.get('/wms/audit/commands', { params });
export const getWmsMovementAudit = (params = {}) => api.get('/wms/audit/movements', { params });
export const reserveWmsInventory = (data) => api.post('/wms/reservations', data);
export const releaseWmsReservation = (id, data = {}) => api.post(`/wms/reservations/${id}/release`, data);
export const getWmsSnRules = () => api.get('/wms/sn-rules');
export const saveWmsSnRule = (data) => api.post('/wms/sn-rules', data);
export const validateWmsSnRule = (data) => api.post('/wms/sn-rules/validate', data);
export const getWmsPolicies = () => api.get('/wms/policies');
export const saveWmsPolicy = (data) => api.post('/wms/policies', data);
export const getWmsAlerts = () => api.get('/wms/alerts');
export const matchWmsStock = (data) => api.post('/wms/stock-match', data);
export const autoAllocateWmsShipment = (id, data = {}) => api.post(`/wms/shipments/${id}/auto-allocate`, data);
export const getWmsCounts = () => api.get('/wms/counts');
export const createWmsCount = (data) => api.post('/wms/counts', data);
export const getWmsCountDetail = (id) => api.get(`/wms/counts/${id}`);
export const updateWmsCountLine = (countId, lineId, data) => api.post(`/wms/counts/${countId}/lines/${lineId}`, data);
export const submitWmsCount = (id) => api.post(`/wms/counts/${id}/submit`);
export const adjustWmsCount = (id) => api.post(`/wms/counts/${id}/adjust`);
export const getWmsReport = (name, params = {}) => api.get(`/wms/reports/${name}`, { params });
export const importWmsInventoryCsv = (formData) => api.post('/wms/import/inventory-csv', formData, {
  headers: { 'Content-Type': 'multipart/form-data' },
});
