/**
 * SalesOrderPage —— 销售订单 SO（PRD 05-客户销售-订单与履约 页面2 ⭐）
 *
 * 决策①（合同即 SO）：录单 → SA_LEADER 下级审核（销售经理审核）→ 预付到账闸 →
 *   下采购通知 → 执行（分批发货）→ 完成。本页对齐扩展现有 SALES_ORDER 引擎流程
 *   （doc_type=SALES_ORDER / sales_order 表 / sales_order_line 子表），不另造新单据。
 *
 * ★状态码 / 子表名 / 外键全部对准真实 seed（services/phase1_workflows.py SALES_ORDER 流程
 *   + models.py SalesOrder/SalesOrderLine，已勘）：
 *   状态机 START→DRAFT→SALES_MANAGER_REVIEW→ADVANCE_RECEIPT_REQUIRED→READY_FOR_PURCHASE→
 *     PURCHASE_NOTICE_SENT→READY_TO_SHIP→SHIPMENT_REQUESTED→COMPLETED / CANCELLED。
 *   编号列 order_number（内部订单号，月度连号由建单取号 effect 取）；客户订单号 customer_po_number。
 *   子表 sales_order_line（FK sales_order_id；列 material_id/quantity/unit_price/total_price/tax_rate…
 *     由 /api/schema 驱动，PurchaseLineGrid 网格录入，不写死列）。
 *
 * 字段防火墙（总览§8）：SO 是卖方视角、无买价列，卖价（unit_price/total_price/total_amount）对客户
 *   /对内可见；利润点对 SALES+SA 可见。本页纯 schema 驱动，不写死任何价格列。
 *
 * 复用积木：PurchaseDocPage（台账 → 右抽屉不跳页 → 顶部动作按钮；动作一律 /api/transitions 按
 *   doc_type=SALES_ORDER + 当前状态 + 角色过滤真实边 → /api/transition 唯一写入路径，不写死状态码）
 *   + 子表网格 PurchaseLineGrid（Excel 粘贴建行 / FK cell 选择器）。
 *
 * SO 派生 effect（后端已挂在 seed 流程边，本页只读不复述）：
 *   · READY_FOR_PURCHASE 状态 effects=create_purchase_notice_from_sales_order（下采购通知）；
 *   · READY_TO_SHIP→SHIPMENT_REQUESTED 边 effects=派生/关联 SHIPMENT 发货申请；
 *   · SALES_MANAGER_REVIEW→ADVANCE_RECEIPT_REQUIRED 边 effects=预收登记。
 */
import PurchaseDocPage from '../purchase/PurchaseDocPage';

// 状态药丸候选（对齐真实 seed SALES_ORDER 流程；仅台账筛选提示，真实可走边以 /api/transitions 为准）
const STATUS_ENUM = [
  { text: '草稿/录入 DRAFT', value: 'DRAFT' },
  { text: '销售经理审核 SALES_MANAGER_REVIEW', value: 'SALES_MANAGER_REVIEW' },
  { text: '待客户预收 ADVANCE_RECEIPT_REQUIRED', value: 'ADVANCE_RECEIPT_REQUIRED' },
  { text: '可发起采购通知 READY_FOR_PURCHASE', value: 'READY_FOR_PURCHASE' },
  { text: '采购处理中 PURCHASE_NOTICE_SENT', value: 'PURCHASE_NOTICE_SENT' },
  { text: '待发货通知 READY_TO_SHIP', value: 'READY_TO_SHIP' },
  { text: '发货执行中 SHIPMENT_REQUESTED', value: 'SHIPMENT_REQUESTED' },
  { text: '已完成 COMPLETED', value: 'COMPLETED' },
  { text: '已取消 CANCELLED', value: 'CANCELLED' },
];

export default function SalesOrderPage() {
  return (
    <PurchaseDocPage
      docType="SALES_ORDER"
      table="sales_order"
      lineTable="sales_order_line"
      lineFk="sales_order_id"
      title="销售订单 SO"
      subtitle="决策①合同即 SO · 录单→销售经理审核→预付到账闸→下采购通知→分批发货→完成"
      numberField="order_number"
      statusEnum={STATUS_ENUM}
      editableStates={['DRAFT']}
      lineTitle="型号明细（型号 / 数量 / 单价 / 含税单价 / 总额 · 网格录入）"
      newLabel="新建销售订单"
      primaryToStates={['SALES_MANAGER_REVIEW', 'READY_FOR_PURCHASE', 'PURCHASE_NOTICE_SENT', 'READY_TO_SHIP', 'SHIPMENT_REQUESTED', 'COMPLETED']}
      intro={{
        title: '销售订单 = 客户/内部订单号/客户订单号/PM/付款方式/币种/税率 + 型号明细子表（型号/数量/单价/含税单价/总额）。卖方视角无买价列，卖价对客户/对内可见',
        description: '决策①「合同即 SO」：录单（SA）→ 销售经理审核（下级审核 / 签章）→ 预付到账闸（需预收时进 ADVANCE_RECEIPT_REQUIRED，财务确认到账后放行）→ 下采购通知（READY_FOR_PURCHASE 派生采购通知）→ 执行（分批发货，READY_TO_SHIP 发布发货通知关联 SHIPMENT）→ 完成。内部订单号 order_number 月度连号（建单取号 effect）；客户订单号 customer_po_number。动作按钮一律由引擎流程边生成（/api/transitions 按当前状态 + 角色过滤）→ /api/transition 唯一写入路径，不写死状态码。SO 审核/已签后由后端推金蝶 outbox（幂等=内部订单号+company_id）。',
      }}
      todoNote="销售订单对齐现有 SALES_ORDER doc_type（已存在 sales_order 表 + sales_order_line 子表 + 完整履约状态机，seed_phase1 权威源）。本页纯 schema/transitions 驱动：后端注册即点亮，子表列由 /api/schema(sales_order_line) 自动出现，动作按钮由 /api/transitions(SALES_ORDER) 真实边渲染（少几条边即少几个按钮）。"
    />
  );
}
