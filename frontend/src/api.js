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

// 销售签单台账聚合（段3b 只读端点；后端未开通时 404 → 页面降级「待后端补段」）
export const getSalesLedger = (params = {}) => api.get('/sales/ledger', { params });

// 采购台账聚合（段2b/2c 只读端点）
export const getPurchaseLedger = (params = {}) => api.get('/purchase/ledger', { params });
export const getPurchaseIntransit = (params = {}) => api.get('/purchase/intransit', { params });
// 采购在途提醒扫描（手动触发轻量扫描：承诺 ETA 过期且未发货 → 写站内提醒）
export const scanPurchaseIntransitAlerts = () => api.post('/purchase/intransit/scan-alerts');

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
export const generateAdjustmentFromCount = (id) => api.post(`/wms/counts/${id}/generate-adjustment`);
export const getWmsReport = (name, params = {}) => api.get(`/wms/reports/${name}`, { params });
export const importWmsInventoryCsv = (formData) => api.post('/wms/import/inventory-csv', formData, {
  headers: { 'Content-Type': 'multipart/form-data' },
});

// 财务·总账（finance-gl）报表只读端点（routers/reports.py，已实现 + 按 _company_filter 隔离）
export const getAccountingPeriods = () => api.get('/reports/periods');
export const getTrialBalance = (params = {}) => api.get('/reports/trial_balance', { params });
export const getAccountBalanceReport = (params = {}) => api.get('/reports/account_balance', { params });
export const getAgingAnalysis = (params = {}) => api.get('/reports/aging_analysis', { params });

// 财务命令统一入口（finance-gl wave-4；后端 POST /api/commands/execute 仅放行 finance.* + 财务角色门）
export const executeCommand = (command, payload = {}, idempotency_key) =>
  api.post('/commands/execute', idempotency_key ? { command, payload, idempotency_key } : { command, payload });
export const batchVoucherTransition = (voucher_ids, to_state) => executeCommand('finance.batch_voucher_transition', { voucher_ids, to_state });
export const checkVoucherGaps = (company_id, period_id) => executeCommand('finance.check_voucher_gaps', { company_id, period_id });
export const renumberVouchers = (company_id, period_id, dry_run = true) => executeCommand('finance.renumber_vouchers', { company_id, period_id, dry_run });
export const createVoucherFromModel = (model_voucher_id, voucher_date, period_id) => executeCommand('finance.create_voucher_from_model', period_id ? { model_voucher_id, voucher_date, period_id } : { model_voucher_id, voucher_date });
export const getVoucherSummary = (params = {}) => api.get('/reports/voucher-summary', { params });

// 财务·账簿补全 + 三大财务报表（finance-gl wave-5；reports.py 只读端点，_company_filter 隔离）
export const getDetailLedger = (params = {}) => api.get('/reports/detail_ledger', { params });
export const getGeneralLedger = (params = {}) => api.get('/reports/general_ledger', { params });
export const getAuxBalance = (params = {}) => api.get('/reports/aux-balance', { params });
export const getBalanceSheet = (params = {}) => api.get('/reports/balance-sheet', { params });
export const getIncomeStatement = (params = {}) => api.get('/reports/income-statement', { params });
export const getCashFlowStatement = (params = {}) => api.get('/reports/cash-flow-statement', { params });

// 财务·现金流量归集 + 定期凭证（finance-gl wave-6）
export const assignCashflow = (payload) => executeCommand('finance.assign_cashflow', payload);
export const generateRecurringVoucher = (scheme_id, period_id, voucher_date) => executeCommand('finance.generate_recurring_voucher', voucher_date ? { scheme_id, period_id, voucher_date } : { scheme_id, period_id });
export const getCashflowTList = (params = {}) => api.get('/reports/cashflow-tlist', { params });
export const getCashflowQuery = (params = {}) => api.get('/reports/cashflow-query', { params });

// 财务·合并报表（finance-gl wave-7）
export const getConsolidatedBalanceSheet = (params = {}) => api.get('/reports/consolidated-balance-sheet', { params });
export const getConsolidatedIncomeStatement = (params = {}) => api.get('/reports/consolidated-income-statement', { params });

// 应收款管理（finance-gl wave-8）
export const getArOpenItems = (params = {}) => api.get('/reports/ar-open-items', { params });
export const getArSummary = (params = {}) => api.get('/reports/ar-summary', { params });
export const getArDetail = (params = {}) => api.get('/reports/ar-detail', { params });
export const getCustomerStatement = (params = {}) => api.get('/reports/customer-statement', { params });
export const writeoff = (payload) => executeCommand('finance.writeoff', payload);
export const unwriteoff = (writeoff_link_ids) => executeCommand('finance.unwriteoff', { writeoff_link_ids });

// 应付款管理（finance-gl 应付波）——应收的供应商侧镜像。待核销项复用通用端点（biz_type=AP）。
export const getApOpenItems = (params = {}) => api.get('/reports/ar-open-items', { params: { ...params, biz_type: 'AP' } });
export const getApSummary = (params = {}) => api.get('/reports/ap-summary', { params });
export const getApDetail = (params = {}) => api.get('/reports/ap-detail', { params });
export const getSupplierStatement = (params = {}) => api.get('/reports/supplier-statement', { params });
export const generateApVouchers = (payload = {}) => executeCommand('finance.generate_ap_vouchers', payload);
