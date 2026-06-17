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

// 7 主数据（schema 驱动台账 + 详情抽屉；8 类含字典型一律同壳）
import MasterDataPage from './pages/master/MasterDataPage';

// 8 配置 / 模板（标签模板 / 单据模板可配子系统）
import LabelTemplatePage from './pages/config/LabelTemplatePage';
import DocTemplatePage from './pages/config/DocTemplatePage';

// 3 仓储 WMS — 入库与库存（PRD 03a；干净业务页，替换原始引擎 demo WmsWorkbench）
import InboundPage from './pages/wms/InboundPage';
import InventoryPage from './pages/wms/InventoryPage';
import MovementPage from './pages/wms/MovementPage';
import LabelsPage from './pages/wms/LabelsPage';
import OutboundPage from './pages/wms/OutboundPage';
import OutboundLedgerPage from './pages/wms/OutboundLedgerPage';
import InventoryCountPage from './pages/wms/InventoryCountPage';
import StockTransferPage from './pages/wms/StockTransferPage';
import StockAdjustmentPage from './pages/wms/StockAdjustmentPage';
import SubcontractPage from './pages/wms/SubcontractPage';

// 2 采购 / 供应链 — 采购询价主链（PRD 04a-1/04a-2/04a-5；台账→抽屉→动作，走元数据 API）
import InternalInquiryPage from './pages/purchase/InternalInquiryPage';
import SupplierInquiryPage from './pages/purchase/SupplierInquiryPage';
import PurchaseNoticePage from './pages/purchase/PurchaseNoticePage';
import PurchaseOrderPage from './pages/purchase/PurchaseOrderPage';
import PurchaseOrderLedgerPage from './pages/purchase/PurchaseOrderLedgerPage';

// 客户联系人子表（PRD 02 页面1 子表 customer_contact_line，BizEditableTable 网格录入）
const REL_LEVEL = [
  { label: 'A 信任', value: 'A' }, { label: 'B 亲切', value: 'B' },
  { label: 'C 熟悉', value: 'C' }, { label: 'D 初识', value: 'D' },
];
const CUSTOMER_CONTACT_SUBTABLE = {
  table: 'customer_contact_line',
  parentFk: 'customer_id',
  title: '联系人（多行网格录入）',
  columns: [
    { title: '部门', dataIndex: 'department', width: 110 },
    { title: '职务', dataIndex: 'title', width: 100 },
    { title: '姓名', dataIndex: 'name', width: 110,
      formItemProps: { rules: [{ required: true, message: '必填' }] } },
    { title: '电话', dataIndex: 'phone', width: 130 },
    { title: '邮箱', dataIndex: 'email', width: 180 },
    { title: '关系等级', dataIndex: 'relation_level', width: 120,
      valueType: 'select', valueEnum: undefined,
      fieldProps: { options: REL_LEVEL } },
    { title: '背景', dataIndex: 'background', width: 160 },
  ],
};

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

        {/* 2 采购 / 供应链（询价主链：内部询价 04a-1 / 对原厂询价 04a-2 / 采购通知 04a-5
            干净业务页，走元数据 API；台账→抽屉不跳页→动作走 /api/transition。
            对原厂单价由后端 Q18 字段防火墙对销售端遮蔽，本页纯 schema 驱动不写死价格列） */}
        <Route path="purchase/inquiries" element={<InternalInquiryPage />} />
        <Route path="purchase/supplier-inquiries" element={<SupplierInquiryPage />} />
        <Route path="purchase/notices" element={<PurchaseNoticePage />} />
        <Route path="purchase/orders" element={<PurchaseOrderPage />} />
        <Route path="purchase/orders-ledger" element={<PurchaseOrderLedgerPage />} />
        <Route path="purchase/stockup" element={PH('备货申请', '采购 / 供应链')} />
        <Route path="purchase/samples" element={PH('样品 SDN', '采购 / 供应链')} />
        <Route path="purchase/rma" element={PH('RMA 退货', '采购 / 供应链')} />
        <Route path="purchase/invoices" element={PH('进项发票录入 / 审核', '采购 / 供应链')} />
        <Route path="purchase/intransit" element={PH('采购在途', '采购 / 供应链')} />
        <Route path="purchase/payments" element={PH('付款申请', '采购 / 供应链')} />

        {/* 3 仓储 WMS（入库与库存 03a：干净业务页，走元数据 API；出库/调拨/盘点/委外为后续段） */}
        <Route path="wms/inbound" element={<InboundPage />} />
        <Route path="wms/inventory" element={<InventoryPage />} />
        <Route path="wms/transactions" element={<MovementPage />} />
        <Route path="wms/outbound" element={<OutboundPage />} />
        <Route path="wms/outbound-ledger" element={<OutboundLedgerPage />} />
        <Route path="wms/subcontract" element={<SubcontractPage />} />
        <Route path="wms/transfer" element={<StockTransferPage />} />
        <Route path="wms/count" element={<InventoryCountPage />} />
        <Route path="wms/stock-adjustment" element={<StockAdjustmentPage />} />
        <Route path="wms/locations" element={
          <MasterDataPage
            table="warehouse_location" title="库位管理" domain="仓储 WMS"
            docType="WAREHOUSE_LOCATION" writable
            primaryCols={['code', 'zone', 'shelf', 'position']}
            todoNote="warehouse_location 三级库位（货区/货架/货层）+ location_type（普通/流转仓/RMA/样品/待处理/NG）。流转仓「快进快出不上架」。建档/改档走引擎唯一写入路径 /api/transition(WAREHOUSE_LOCATION 流程，照段0c 单态 ACTIVE + 自环编辑)；后端未注册该流程时引擎如实返回「没有活跃的流程定义」、本页不伪造成功。"
          />
        } />
        <Route path="wms/labels" element={<LabelsPage />} />

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

        {/* 7 主数据（schema 驱动台账 + 详情抽屉，严守 14 律：台账→抽屉不跳页）
            写入一律走引擎唯一路径 /api/transition；docType 缺活跃状态机时引擎如实报错，
            前端不伪造成功（守"唯一写入路径"）。8 类主数据与字典页同壳 MasterDataPage。 */}
        <Route path="master/customers" element={
          <MasterDataPage
            table="customer" title="客户" docType="CUSTOMER" writable
            primaryCols={['code', 'short_name', 'name']}
            subTable={CUSTOMER_CONTACT_SUBTABLE}
            todoNote="客户建档/改档走 /api/transition（CUSTOMER 状态机）；内嵌联系人子表 customer_contact_line 随单 sub_updates 提交。若引擎报「没有活跃的流程定义」，需后端注册 CUSTOMER 建档状态机（EXT-02-W）。"
          />
        } />
        <Route path="master/suppliers" element={
          <MasterDataPage
            table="supplier" title="供应商 / 原厂" docType="SUPPLIER" writable
            primaryCols={['code', 'short_name', 'name']}
            todoNote="供应商建档/改档走 /api/transition（SUPPLIER 状态机）；一供应商绑一负责 PA（responsible_pa_id cell 选择器）。若引擎报「没有活跃的流程定义」，需后端注册 SUPPLIER 建档状态机（EXT-02-W）。"
          />
        } />
        <Route path="master/products" element={
          <MasterDataPage
            table="material" title="产品 / 型号" docType="MATERIAL" writable
            primaryCols={['sku', 'name']}
            todoNote="型号建档/改档走 /api/transition（MATERIAL 状态机）；含 control_mode(SN/LOT)/uom_id/HS 双码/ECCN/MOQ/MPQ/质保 等（PRD 02 页面3 ⭐，FK 走 cell 选择器）。若引擎报「没有活跃的流程定义」，需后端注册 MATERIAL 建档状态机（EXT-02-W）。"
          />
        } />
        <Route path="master/product-codes" element={
          <MasterDataPage
            table="product_code" title="产品代码" docType="PRODUCT_CODE" writable
            primaryCols={['internal_code', 'vendor_pn', 'customer_material_no']}
            todoNote="产品代码建档/改档走 /api/transition（PRODUCT_CODE 状态机）；型号×供应商→内部 code，复合唯一（PRD 02 页面4 ⭐），型号/供应商 FK 走 cell 选择器、改档锁定。"
          />
        } />
        <Route path="master/product-lines" element={
          <MasterDataPage
            table="product_line" title="产线" docType="PRODUCT_LINE" writable
            primaryCols={['code', 'line_name']}
            todoNote="产线建档/改档走 /api/transition（PRODUCT_LINE 状态机）；1 线=1 供应商（DB 唯一约束兜底），绑定 PM/FAE/PA（角色 cell 选择器，PRD 02 页面5）。"
          />
        } />
        <Route path="master/locations" element={
          <MasterDataPage
            table="warehouse_location" title="库位"
            primaryCols={['code', 'zone', 'shelf', 'position']}
            todoNote="warehouse_location 表已扩 location_type/capacity（货区/货架/货层三级，PRD 02 页面6）、可查可看详情；为 __queryable__ 主数据、无 doc_type，建档/改档待后端 ➕ 写路径（EXT-02-W）。"
          />
        } />
        <Route path="master/hscode" element={
          <MasterDataPage
            table="hs_code" title="HS 编码"
            primaryCols={['hs_number', 'description_cn', 'description_en']}
            todoNote="HS 编码已落独立真表 hs_code（原产 & 中国双码字典，全局共享 PRD 02 页面7），与客户/供应商同壳可查可看详情；为 __queryable__ 纯字典、无 doc_type，维护待后端 ➕ 写路径（EXT-02-W）。"
          />
        } />
        <Route path="master/uom" element={
          <MasterDataPage
            table="unit_of_measure" title="计量单位"
            primaryCols={['uom_code', 'uom_name']}
            todoNote="计量单位已落独立真表 unit_of_measure（包/盘/PCS 字典，全局共享 PRD 02 页面8），与客户/供应商同壳可查可看详情；为 __queryable__ 纯字典、无 doc_type，维护待后端 ➕ 写路径（EXT-02-W）。"
          />
        } />

        {/* 8 配置 / 模板 */}
        <Route path="config/label-templates" element={<LabelTemplatePage />} />
        <Route path="config/doc-templates" element={<DocTemplatePage />} />
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
