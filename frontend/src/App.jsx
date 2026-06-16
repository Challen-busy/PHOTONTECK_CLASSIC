import { Routes, Route, Navigate } from 'react-router-dom';
import { Spin } from 'antd';
import { AuthProvider, useAuth } from './auth';
import Layout from './components/Layout';
import Login from './pages/Login';
import ErrorBoundary from './components/ErrorBoundary';

// 工作台域 0
import Workbench from './pages/Workbench';
import Notifications from './pages/Notifications';
import MyTodos from './pages/MyTodos';            // 审批中心收件箱（引擎现成 list_user_todos）

// 业务模块占位（壳就绪，待 P 段建造）
import ModulePlaceholder from './pages/ModulePlaceholder';

// 引擎壳页（保留给 admin）
import DataExplorer from './pages/DataExplorer';
import WorkflowActions from './pages/WorkflowActions';
import NodeView from './pages/NodeView';
import FlowEditor from './pages/FlowEditor';
import DocHistory from './pages/DocHistory';
import Admin from './pages/Admin';

function Protected({ children }) {
  const { user, loading } = useAuth();
  if (loading) return <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100vh' }}><Spin size="large" /></div>;
  if (!user) return <Navigate to="/login" />;
  return children;
}

// admin-only 守卫（引擎壳页 / 账号管理）
function AdminOnly({ children }) {
  const { user } = useAuth();
  if (!user?.is_admin) return <Navigate to="/" replace />;
  return children;
}

// 占位页工厂：少写样板
const PH = (title, domain) => <ModulePlaceholder title={title} domain={domain} />;

function AppRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/" element={<Protected><Layout /></Protected>}>
        {/* 0 工作台 */}
        <Route index element={<Workbench />} />
        <Route path="notifications" element={<Notifications />} />
        <Route path="approvals" element={<MyTodos />} />

        {/* 1 客户 / 销售 */}
        <Route path="sales/customers" element={PH('客户 / 联系人', '客户 / 销售')} />
        <Route path="sales/leads" element={PH('线索 / 商机 / 跟进', '客户 / 销售')} />
        <Route path="sales/quotations" element={PH('报价单', '客户 / 销售')} />
        <Route path="sales/orders" element={PH('销售订单 SO', '客户 / 销售')} />
        <Route path="sales/shipments" element={PH('发货申请 / 发货通知', '客户 / 销售')} />
        <Route path="sales/invoices" element={PH('销项发票管理', '客户 / 销售')} />
        <Route path="sales/tickets" element={PH('售后技术工单', '客户 / 销售')} />
        <Route path="sales/qualification" element={PH('客户认证 / 标书', '客户 / 销售')} />
        <Route path="sales/forecast" element={PH('Forecast 接单', '客户 / 销售')} />

        {/* 2 采购 / 供应链 */}
        <Route path="purchase/inquiries" element={PH('询价', '采购 / 供应链')} />
        <Route path="purchase/orders" element={PH('PO 总表 / 采购订单', '采购 / 供应链')} />
        <Route path="purchase/stockup" element={PH('备货申请', '采购 / 供应链')} />
        <Route path="purchase/samples" element={PH('样品 SDN', '采购 / 供应链')} />
        <Route path="purchase/rma" element={PH('RMA 退货', '采购 / 供应链')} />
        <Route path="purchase/invoices" element={PH('进项发票录入 / 审核', '采购 / 供应链')} />
        <Route path="purchase/intransit" element={PH('采购在途', '采购 / 供应链')} />
        <Route path="purchase/payments" element={PH('付款申请', '采购 / 供应链')} />

        {/* 3 仓储 WMS */}
        <Route path="wms/inbound" element={PH('入库收货', '仓储 WMS')} />
        <Route path="wms/inventory" element={PH('库存（批次 / SN / LOT / 库位）', '仓储 WMS')} />
        <Route path="wms/transactions" element={PH('库存流水 / 事务台账', '仓储 WMS')} />
        <Route path="wms/outbound" element={PH('出库发货', '仓储 WMS')} />
        <Route path="wms/subcontract" element={PH('委外加工', '仓储 WMS')} />
        <Route path="wms/transfer" element={PH('调拨（同公司内仓间）', '仓储 WMS')} />
        <Route path="wms/count" element={PH('盘点 / 库存调整单', '仓储 WMS')} />
        <Route path="wms/locations" element={PH('库位管理', '仓储 WMS')} />
        <Route path="wms/labels" element={PH('标签打印', '仓储 WMS')} />

        {/* 4 报关 */}
        <Route path="customs/declarations" element={PH('报关单（进口 / 出口 / 退运）', '报关')} />
        <Route path="customs/return-monitor" element={PH('退运监控（180天预警）', '报关')} />
        <Route path="customs/fees" element={PH('报关费 / 进出口证补录', '报关')} />
        <Route path="customs/logistics" element={PH('物流 API 货物进度', '报关')} />

        {/* 5 财务视图 / 单据中心 */}
        <Route path="finance/ar" element={PH('应收视图（只读）', '财务视图 / 单据中心')} />
        <Route path="finance/ap" element={PH('应付视图（只读）', '财务视图 / 单据中心')} />
        <Route path="finance/advance" element={PH('预收 / 预付到账确认', '财务视图 / 单据中心')} />
        <Route path="finance/credit-note" element={PH('Credit Note', '财务视图 / 单据中心')} />
        <Route path="finance/kingdee-outbox" element={PH('单据推送中心（金蝶 outbox）', '财务视图 / 单据中心')} />
        <Route path="finance/chain" element={PH('单据链路追踪', '财务视图 / 单据中心')} />
        <Route path="finance/reconcile" element={PH('对账', '财务视图 / 单据中心')} />

        {/* 6 报表 / 看板 */}
        <Route path="reports/kpi" element={PH('经营 KPI', '报表 / 看板')} />
        <Route path="reports/opportunity-board" element={PH('商机看板', '报表 / 看板')} />
        <Route path="reports/ar-board" element={PH('应收看板', '报表 / 看板')} />
        <Route path="reports/target" element={PH('业绩目标 vs 实际', '报表 / 看板')} />
        <Route path="reports/commission" element={PH('提成', '报表 / 看板')} />
        <Route path="reports/cross-company" element={PH('管理层跨公司只读汇总', '报表 / 看板')} />

        {/* 7 主数据 */}
        <Route path="master/customers" element={PH('客户', '主数据')} />
        <Route path="master/suppliers" element={PH('供应商 / 原厂', '主数据')} />
        <Route path="master/products" element={PH('产品 / 型号', '主数据')} />
        <Route path="master/product-codes" element={PH('产品代码（一型号多 code）', '主数据')} />
        <Route path="master/product-lines" element={PH('产线（1线=1供应商）', '主数据')} />
        <Route path="master/locations" element={PH('库位', '主数据')} />
        <Route path="master/hscode" element={PH('HS 编码', '主数据')} />
        <Route path="master/uom" element={PH('计量单位', '主数据')} />

        {/* 8 配置 / 模板 */}
        <Route path="config/label-templates" element={PH('标签模板', '配置 / 模板')} />
        <Route path="config/doc-templates" element={PH('单据模板（PL / INV / 送货单）', '配置 / 模板')} />
        <Route path="config/numbering" element={PH('编号规则', '配置 / 模板')} />
        <Route path="config/approval-flow" element={PH('审批流配置', '配置 / 模板')} />
        <Route path="config/commission" element={PH('提成规则配置', '配置 / 模板')} />

        {/* 9 企业 / 账号管理（admin） */}
        <Route path="org/companies" element={<AdminOnly>{PH('公司 / 租户', '企业 / 账号管理')}</AdminOnly>} />
        <Route path="org/users" element={<AdminOnly>{PH('用户', '企业 / 账号管理')}</AdminOnly>} />
        <Route path="org/roles" element={<AdminOnly>{PH('角色与权限（用户-公司-角色三元）', '企业 / 账号管理')}</AdminOnly>} />
        <Route path="org/audit" element={<AdminOnly><Admin /></AdminOnly>} />

        {/* 引擎壳页（保留给 admin：数据浏览 / 流程管理 / 节点 / 历史） */}
        <Route path="data" element={<AdminOnly><DataExplorer /></AdminOnly>} />
        <Route path="data/:table" element={<AdminOnly><DataExplorer /></AdminOnly>} />
        <Route path="flow-editor" element={<AdminOnly><ErrorBoundary><FlowEditor /></ErrorBoundary></AdminOnly>} />
        <Route path="actions" element={<AdminOnly><WorkflowActions /></AdminOnly>} />
        <Route path="actions/:workflowId" element={<AdminOnly><WorkflowActions /></AdminOnly>} />
        <Route path="history/:docType/:docId" element={<AdminOnly><DocHistory /></AdminOnly>} />

        {/* 待办进单：节点视图（所有角色，从工作台/审批中心下钻） */}
        <Route path="node/:workflowId/:stateCode" element={<NodeView />} />

        {/* 兜底：未知路由回工作台 */}
        <Route path="*" element={<Navigate to="/" replace />} />
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
