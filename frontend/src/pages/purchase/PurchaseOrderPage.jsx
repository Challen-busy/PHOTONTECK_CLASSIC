/**
 * PurchaseOrderPage —— 采购订单 PO（PRD 04a-3）⭐
 *
 * 复用 PURCHASE_ORDER doc_type + purchase_order_line 子表（✅引擎已存在，段2b 后端重构主链流程）。
 * 头（schema 驱动）：供应商 / 原厂 SO# / 报备 end-customer / PM / PD / PA / 关联 SO / 是否备货 /
 *   付款·贸易条件 / ship-to·bill-to / 是否预付；明细网格：型号 / 数量 / 单价 / 交期 / 已收。
 *
 * 状态药丸 = 重构后主链（DRAFT → 待采购审批 PENDING_APPROVAL → ★采购审批 FINANCE_APPROVAL →
 *   已下单 ORDERED → 部分到货 / 已到货 → 关闭）；★真实可执行边一律以 /api/transitions 为准
 *   （后端重构前 seed 仍是 K3 镜像态，本页状态枚举仅作筛选提示，动作按当前状态过滤真实边）。
 *
 * 🔒 Q18 字段防火墙：PO 头 total_amount / advance_payment_amount / stock_amount_* 与子表
 *   unit_price / total_price（采购进价/成本）对销售端（SALES + SA）隐藏。遮蔽在后端
 *   （purchase_order(_line) ∈ BUY_TABLES，价格列 ∈ BUY_PRICE_FIELDS，_can_view_buy_price 不含
 *   SALES/SA）。本页纯按 /api/schema 渲染——销售登录时该列不返回即不渲，前端不写死价格列。
 *
 * ★采购审批是 FINANCE 节点（蓝图 §5.1）：FINANCE 登录时 /api/transitions 才返回审批通过/驳回边，
 *   PA 登录看不到——角色闸由引擎按 allowed_roles 过滤，本页不写死角色判断。
 */
import PurchaseDocPage from './PurchaseDocPage';

// 状态枚举 = 重构后聚焦主链（仅筛选提示；真实边以 /api/transitions 为准）
const STATUS_ENUM = [
  { text: '草稿 DRAFT', value: 'DRAFT' },
  { text: '待采购审批 PENDING_APPROVAL', value: 'PENDING_APPROVAL' },
  { text: '★采购审批 FINANCE_APPROVAL', value: 'FINANCE_APPROVAL' },
  { text: '已下单 ORDERED', value: 'ORDERED' },
  { text: '部分到货 PARTIAL', value: 'PARTIAL' },
  { text: '已到货 RECEIVED', value: 'RECEIVED' },
  { text: '已关闭 CLOSED', value: 'CLOSED' },
  { text: '驳回 REJECTED', value: 'REJECTED' },
  { text: '已取消 CANCELLED', value: 'CANCELLED' },
];

export default function PurchaseOrderPage() {
  return (
    <PurchaseDocPage
      docType="PURCHASE_ORDER"
      table="purchase_order"
      lineTable="purchase_order_line"
      lineFk="purchase_order_id"
      title="采购订单 PO"
      subtitle="PA 录单 → ★财务采购审批 → 已下单（推金蝶 + 导出发原厂）"
      numberField="order_number"
      statusEnum={STATUS_ENUM}
      editableStates={['DRAFT', 'REJECTED']}
      lineTitle="采购明细（型号 / 数量 / 单价🔒 / 交期 / 已收 · 网格录入）"
      scanSequence={['material_id', 'quantity']}
      newLabel="新建采购订单"
      primaryToStates={['PENDING_APPROVAL', 'FINANCE_APPROVAL', 'ORDERED']}
      intro={{
        title: '一张 PO = 一次对某供应商的采购：含报备 end-customer（可≠销售客户，PM 定）/ 原厂 SO# / 关联 SO（备货空）/ 是否备货 / 付款·贸易条件 / ship-to·bill-to',
        description: 'PA 录单（型号选该供应商维度的产品代码、数量≠0、单价手录可改）→ 提交 → ★采购审批（财务，蓝图 §5.1，FINANCE 登录才见审批边）→ 已下单（推金蝶应付源 + 导出 PDF 发原厂）→ 入库回填已收消在途。单价 / 订单金额 / 预付金额 / 备货金额等采购进价由后端字段防火墙对销售端（SALES + SA）遮蔽——本页按 schema 渲染，销售登录时该列不出现。DRAFT / 驳回态可改头与明细。',
      }}
      todoNote="采购订单复用引擎现有 PURCHASE_ORDER doc_type + purchase_order_line 子表（✅已存在）。若 /api/schema 失败或动作不全，需后端段2b：① 重构 PO 流程为聚焦主链（DRAFT→待采购审批→★FINANCE 采购审批→已下单→部分/已到货→关闭），拆出独立 ★FINANCE 采购审批节点，入库/质检/发票移出 PO 大流程（入库=GOODS_RECEIPT、发票=PURCHASE_INVOICE）；② ➕ 头列 factory_so_number/product_manager_id/pd_id/notice_date/stock_amount_*/stock_quantity/stock_reason；③ PO 号月度连号 + 抬头码编号规则；④ PO 审批通过 → kingdee_outbox 推送 effect（order_number+company_id 幂等）；⑤ Q18：purchase_order(_line) 入 BUY_TABLES、total_amount/advance_payment_amount/stock_amount_*/unit_price/total_price 入 BUY_PRICE_FIELDS。注册后本页自动点亮，价格列对 SALES/SA 自动隐藏，FINANCE 见审批边。"
    />
  );
}
