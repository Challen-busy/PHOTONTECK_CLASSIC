/**
 * PurchaseInvoicePage —— 进项发票录入 / ★审核（原厂 invoice → 审核 → 应付，PRD 04a-7）⭐
 *
 * 复用 PURCHASE_INVOICE doc_type + purchase_invoice_line 子表（✅引擎已 seed）。
 * 头：发票号 / 供应商 / 关联 PO / 关联入库 / 金额🔒 / 货币 / 税率 / 发票日 / 备注；
 * 明细网格：关联 PO 行 / 关联入库行 / 型号 / 数量 / 单价🔒 / 行金额🔒 / 税率。
 *
 * 流程（seed_phase1 权威）：START → DRAFT(PA 录) → MATCHING(★FINANCE 勾稽审核) → AP_CREATED(已生成应付，终态) / CANCELLED。
 *   ★财务审核节点：MATCHING 的 allowed_roles 含 FINANCE，「勾稽通过并生成应付」边带 AP/PO effect（形成应付 + 推金蝶，§00-6.2）。
 *   驱动一律走 /api/transitions（按 doc_type+当前状态过滤真实边）+ /api/transition（唯一写入路径），不写死状态码。
 *
 * 🔒 Q18 字段防火墙：金额 amount / 单价 unit_price / 行金额 total_price（采购成本）对销售端（SALES + SA）隐藏。
 *    遮蔽在后端（purchase_invoice/_line ∈ BUY_TABLES，amount/unit_price/total_price ∈ BUY_PRICE_FIELDS）——
 *    本页纯按 /api/schema 渲染，销售登录时该列不返回即不出现，前端不写死价格列。
 */
import PurchaseDocPage from './PurchaseDocPage';

const STATUS_ENUM = [
  { text: 'DRAFT 登记发票', value: 'DRAFT' },
  { text: '★待财务审核 PENDING_REVIEW', value: 'PENDING_REVIEW' },
  { text: '★已生成应付 AP_CREATED', value: 'AP_CREATED' },
  { text: '已取消 CANCELLED', value: 'CANCELLED' },
];

export default function PurchaseInvoicePage() {
  return (
    <PurchaseDocPage
      docType="PURCHASE_INVOICE"
      table="purchase_invoice"
      lineTable="purchase_invoice_line"
      lineFk="purchase_invoice_id"
      title="进项发票"
      subtitle="原厂 invoice 录入 → ★财务勾稽审核 → 应付（PA 采购端最后一步）"
      numberField="invoice_number"
      statusEnum={STATUS_ENUM}
      editableStates={['DRAFT']}
      lineTitle="进项发票明细（关联 PO 行 / 入库行 / 型号 / 数量 / 单价🔒 / 行金额🔒 / 税率 · 网格录入）"
      scanSequence={['material_id', 'quantity']}
      newLabel="录入进项发票"
      primaryToStates={['PENDING_REVIEW', 'AP_CREATED']}
      intro={{
        title: '一张进项发票 = PA 收到原厂正式 invoice 后据 PO + 入库勾稽录入，提交 → ★财务审核（核发票号/金额/与入库一致）→ 形成应付并推金蝶',
        description: '发票号原厂给、公司内唯一、财务对账用它；无入库不能录（须关联入库单）。DRAFT 态 PA 可改头与明细；提交进入 PENDING_REVIEW 后由★财务勾稽审核——「勾稽通过并生成应付」一步形成 accounts_payable + 推金蝶（进项/应付源，决策③）。金额 / 单价 / 行金额等采购成本由后端字段防火墙对销售端（SALES + SA）遮蔽，本页按 schema 渲染，销售登录时该列不出现。',
      }}
      todoNote="进项发票复用引擎已 seed 的 PURCHASE_INVOICE doc_type + purchase_invoice_line 子表（START→DRAFT→MATCHING→AP_CREATED→CANCELLED，MATCHING 的 allowed_roles 含 FINANCE 为★审核节点，「勾稽通过并生成应付」边带 AP/PO/推金蝶 effect）。若 /api/schema 失败需后端确认该流程与 invoice_number 月度连号编号规则已注册；注册后本页自动点亮、价格列对 SALES/SA 自动隐藏。"
    />
  );
}
