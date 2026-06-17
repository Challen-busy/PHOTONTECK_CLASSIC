/**
 * SalesInvoicePage —— 销项发票（PRD 05-客户销售-订单与履约 页面5；决策③）
 *
 * 对齐扩展现有 SALES_INVOICE 引擎流程（doc_type=SALES_INVOICE / sales_invoice 表 /
 *   sales_invoice_line 子表），不另造单据。
 *
 * ★状态码 / 子表名 / 外键对准真实 seed（services/phase1_workflows.py SALES_INVOICE 流程 +
 *   models.py SalesInvoice/SalesInvoiceLine，已勘）：
 *   状态机 START→DRAFT→MATCHING→AR_CREATED / CANCELLED。
 *   MATCHING→AR_CREATED 边 effects=sales_invoice_ar_effect（形成应收 + 推金蝶销项，决策③）。
 *   编号列 invoice_number；头含 关联SO sales_order_id / 关联发货 shipment_id / amount / tax_rate。
 *   子表 sales_invoice_line（FK sales_invoice_id；I 号配对 PL：sales_order_line_id / shipment_line_id）。
 *
 * 复用积木：PurchaseDocPage（台账 → 右抽屉不跳页 → 顶部动作按钮；动作一律 /api/transitions 按
 *   doc_type=SALES_INVOICE + 当前状态 + 角色过滤真实边 → /api/transition 唯一写入路径，不写死状态码）。
 */
import PurchaseDocPage from '../purchase/PurchaseDocPage';

// 状态药丸候选（对齐真实 seed SALES_INVOICE 流程；真实可走边以 /api/transitions 为准）
const STATUS_ENUM = [
  { text: '登记发票 DRAFT', value: 'DRAFT' },
  { text: '勾稽中 MATCHING', value: 'MATCHING' },
  { text: '已生成应收 AR_CREATED', value: 'AR_CREATED' },
  { text: '已取消 CANCELLED', value: 'CANCELLED' },
];

export default function SalesInvoicePage() {
  return (
    <PurchaseDocPage
      docType="SALES_INVOICE"
      table="sales_invoice"
      lineTable="sales_invoice_line"
      lineFk="sales_invoice_id"
      title="销项发票"
      subtitle="决策③ · 登记 → 勾稽 MATCHING（I 号配对 PL）→ 形成应收 AR + 推金蝶销项"
      numberField="invoice_number"
      statusEnum={STATUS_ENUM}
      editableStates={['DRAFT']}
      lineTitle="发票明细（型号 / 数量 / 单价 / 含税单价 / 关联 SO 行 / 关联发货行 · 网格录入）"
      newLabel="新建销项发票"
      primaryToStates={['MATCHING', 'AR_CREATED']}
      intro={{
        title: '销项发票 = 发票号/关联SO/关联发货/金额/税率 + 发票明细子表（I 号配对 PL，关联 SO 行与发货行）',
        description: '决策③：登记销售发票（DRAFT）→ 提交勾稽（MATCHING，把发票行 I 号与发货明细 PL 配对）→ 勾稽通过并生成应收（AR_CREATED）。MATCHING→AR_CREATED 形成应收账款并由后端推金蝶销项 outbox。头表单含 关联SO（sales_order_id）/ 关联发货（shipment_id）/ 金额 / 币种 / 税率 / 开票日期。动作按钮一律由引擎流程边生成（/api/transitions 按当前状态 + 角色过滤）→ /api/transition 唯一写入路径，不写死状态码。',
      }}
      todoNote="销项发票对齐现有 SALES_INVOICE doc_type（已存在 sales_invoice 表 + sales_invoice_line 子表 + 勾稽状态机 DRAFT→MATCHING→AR_CREATED，seed_phase1 权威源）。本页纯 schema/transitions 驱动：子表列由 /api/schema(sales_invoice_line) 自动出现，动作按钮由 /api/transitions(SALES_INVOICE) 真实边渲染。"
    />
  );
}
