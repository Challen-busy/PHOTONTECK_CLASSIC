/**
 * QuotationPage —— 报价单台账（PRD 05-CRM前段 页面6 ⭐，本模块最关键页）
 *
 * 承载三方协作定价机制 + 字段防火墙 + PM 门控（甲方 Q18，2026-06-16 拍板）：
 *   - FAE 确认规格 → 产品部/PA 录采购成本（对销售端隐藏）→ ★PM「是否报价」门控 →
 *     ★PM 设利润点定卖价 → 已报价 → 客户接受/拒绝/过期。
 *
 * ★对齐扩展现有 QUOTATION 引擎（doc_type=QUOTATION / quotation 表 / quotation_line 子表），
 *   不另造 QUOTE。现有 QuotationLine 是产品行（material_id/quantity/unit_price），PRD §6 的阶梯价
 *   列（min_quantity / unit_price / profit_point + 隐藏的 cost_unit）由后端段3b ➕ 扩列——本页纯
 *   schema 驱动子表网格（PurchaseLineGrid），后端 ➕ 列自动出现、防火墙遮蔽列自动不渲。
 *
 * ★段2d-2 lineFk 教训：阶梯价子表父 FK 对准真列名 quotation_id（已查证 models.py QuotationLine
 *   外键即 quotation_id，非 quote_id）；派生 _ 展示列由 PurchaseDocPage.buildSubUpdates 提交前 strip。
 *
 * 🔒 字段防火墙（§00-8 / Q18，query+schema 两路）——本页纯 schema 驱动、不写死任何价格/成本列：
 *   · 采购成本 cost / cost_unit ：对销售端（SALES+SA）后端序列化层删除（schema 不返回即不出列），
 *     销售端打开报价单看不到采购成本（跨所有状态生效）。
 *   · 利润点 profit_point / unit_profit_point ：对 SALES+SA 可见（Q18 报价决策用，与 SA 同层，
 *     不入隐藏集；引擎现状本就未覆盖 profit_point → 正好无需为它新增隐藏），仅编辑权限 PM。
 *
 * ★PM 门控（状态机两个 PM 专属关卡 allowed_roles=[PRODUCT_MANAGER]）：
 *   · 待报价决策：PM 选「报价 / 不报价」（不报价直接关闭，进不了已报价、推不给销售对客户）。
 *   · 待定价：PM 据成本 + 利润点定卖价。不点报价、没定价 → 进不了「已报价」。
 *
 * 复用积木：PurchaseDocPage（台账 → 右抽屉不跳页 → 顶部动作按钮，动作一律 /api/transitions
 *   按当前状态 + 角色过滤真实边 → /api/transition 唯一写入路径，不写死状态码）+ 子表网格
 *   PurchaseLineGrid（阶梯价 Excel 粘贴建行，录单增强 14 律 §3）。
 *
 * ★引擎实况：QUOTATION doc_type / quotation 表 / quotation_line 子表已存在；本页对齐扩展，
 *   PM 门控状态机 + 阶梯价扩列 + 成本字段防火墙由后端段3b ➕。流程未注册全态时动作按钮按
 *   /api/transitions 真实边渲染（少几条边即少几个按钮），不伪造推进。
 */
import PurchaseDocPage from '../purchase/PurchaseDocPage';

// 状态药丸候选（含两个 PM 专属关卡；仅台账筛选提示，真实可走边以 /api/transitions 为准，不写死推进）
const STATUS_ENUM = [
  { text: '草稿/制作 DRAFT', value: 'DRAFT' },
  { text: '待成本 PENDING_COST', value: 'PENDING_COST' },
  { text: '★待报价决策 PENDING_QUOTE_DECISION', value: 'PENDING_QUOTE_DECISION' },
  { text: '★待定价 PENDING_PRICING', value: 'PENDING_PRICING' },
  { text: '已报价/已发客户 SENT', value: 'SENT' },
  { text: '客户已确认 CUSTOMER_CONFIRMED', value: 'CUSTOMER_CONFIRMED' },
  { text: '已生成销售订单 SALES_ORDER_CREATED', value: 'SALES_ORDER_CREATED' },
  { text: '客户已拒绝 CUSTOMER_REJECTED', value: 'CUSTOMER_REJECTED' },
  { text: '关闭未报 CLOSED_NO_QUOTE', value: 'CLOSED_NO_QUOTE' },
  { text: '已过期 EXPIRED', value: 'EXPIRED' },
  { text: '已取消 CANCELLED', value: 'CANCELLED' },
];

export default function QuotationPage() {
  return (
    <PurchaseDocPage
      docType="QUOTATION"
      table="quotation"
      lineTable="quote_tier_line"
      lineFk="quotation_id"
      title="报价单"
      subtitle="三方协作定价 · 字段防火墙（成本对销售端隐藏 / 利润点可见）· PM「是否报价」门控 + 定价关卡"
      numberField="quotation_number"
      statusEnum={STATUS_ENUM}
      editableStates={['DRAFT', 'PENDING_COST', 'PENDING_QUOTE_DECISION', 'PENDING_PRICING']}
      lineTitle="阶梯价（起订量 / 单价 / 利润点 · 网格录入；采购成本列对销售端由后端遮蔽不渲）"
      newLabel="新建报价单"
      primaryToStates={['PENDING_COST', 'PENDING_QUOTE_DECISION', 'PENDING_PRICING', 'SENT', 'CUSTOMER_CONFIRMED', 'SALES_ORDER_CREATED']}
      intro={{
        title: '报价单 = 客户/型号/币种/税率/有效期/条款 + 阶梯价子表（起订量/单价/利润点）。本页两条安全律：① 字段防火墙——采购成本对销售端隐藏、利润点对销售端可见；② PM 门控——不经 PM 选「报价」并设利润点，报价单进不了「已报价」推不给销售',
        description: '🔒 字段防火墙（§00-8 / 甲方 Q18）：采购成本 cost/cost_unit 对销售端（SALES+SA）由后端 query+schema 两路删除（销售端登录时这两列不出现、跨所有状态）；利润点 profit_point/unit_profit_point 对 SALES+SA 可见（报价决策用、与 SA 同层），仅编辑权限归 PM。本页纯 schema 驱动，不写死任何价格/成本列。 ★PM 门控（两个 PM 专属关卡 allowed_roles=[PRODUCT_MANAGER]）：待报价决策（PM 选报价/不报价，不报价直接关闭）→ 待定价（PM 据成本+利润点定卖价），不点报价、没定价进不了「已报价」。 流程：草稿 → 待规格确认（科研，FAE）→ 待成本（PM/PA 录成本，对销售隐藏）→ ★待报价决策 → ★待定价 → 已报价 → 客户接受（提示转 SO，SO 在 05b）/ 拒绝 / 过期。前段不推金蝶（金蝶接 SO 起）。动作按钮一律由引擎流程边生成（/api/transitions 按当前状态 + 角色过滤）→ /api/transition 唯一写入路径，不写死状态码。',
      }}
      todoNote="报价单对齐扩展现有 QUOTATION doc_type（已存在 quotation 表 + quotation_line 子表，不另造 QUOTE）。需后端段3b：① 把 quotation_line ➕ 阶梯价列（min_quantity/profit_point/cost_unit/unit_profit_point，现有 QuotationLine 仅产品行 material_id/quantity/unit_price）；② 字段防火墙——把 quotation.cost / quotation_line.cost_unit（采购成本）加入隐藏集对 SALES+SA 删（BUY_PRICE_FIELDS/自定义隐藏集 + _can_view_*，query+schema 两路），profit_point/unit_profit_point 不入隐藏集（Q18 对销售端可见，引擎现状本就未覆盖 profit_point）；③ 用 PM 门控状态机替换/扩现有极简 QUOTATION 流程（DRAFT→SPEC_REVIEW→COSTING→DECISION_PENDING→PRICING→QUOTED→ACCEPTED/REJECTED/EXPIRED，DECISION_PENDING+PRICING 节点 allowed_roles=[PRODUCT_MANAGER]，规避 D-02e 边级角色坑；DECISION_PENDING 关卡选「报价/不报价」、PRICING 关卡定卖价）；④ quotation_number 月度连号（若需对齐 Q-{YYMM}-{NNN}）。注册后本页自动点亮，销售端登录采购成本列自动隐藏、利润点列可见。"
    />
  );
}
