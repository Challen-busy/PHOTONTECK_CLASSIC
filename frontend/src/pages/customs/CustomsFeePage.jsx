/**
 * CustomsFeePage —— 报关费补录（已放行进口报关单登记费用）（PRD 06-3）
 *
 * 复用单据壳 PurchaseDocPage：台账列已放行报关单，抽屉里以费用子表网格录入报关费 / 运费，
 * 引擎 RELEASED 自循环边「登记费用」→ customs.allocate_fee_to_landed_cost effect 按占比分摊
 * 回写关联各入库批次到岸成本 + 金蝶增量推送（随入库单，不写真实 HTTP，属段5）。
 *
 * ★真值（已勘 /api/schema 2026-06-17）：
 *   - 头表 customs_declaration（同报关单台账，号 declaration_number）。
 *   - 费用子表 customs_fee_line（FK customs_declaration_id）：fee_type / amount / currency / payee
 *     / bill_number / incurred_date / allocation_basis(AMOUNT 申报金额占比 / QUANTITY 数量占比)
 *     / allocation_detail(分摊明细，回写 effect 产出)。
 *   - 「登记费用」=RELEASED→RELEASED 自循环边（仅进口已放行单可走，editable=notes + 费用子表）。
 *     真实可走边以 /api/transitions 为准；未注册时抽屉如实显示无动作（不写死推进）。
 *
 * ★段5 边界：金蝶真实推送 / 分摊回写的 outbox 真实 HTTP 属段5，本段引擎 effect 仅 enqueue 占位。
 */
import PurchaseDocPage from '../purchase/PurchaseDocPage';

// 台账筛选提示：费用登记发生在已放行单上
const STATUS_ENUM = [
  { text: '已放行 RELEASED（可登记费用）', value: 'RELEASED' },
  { text: '已申报 SUBMITTED', value: 'SUBMITTED' },
  { text: '草拟 DRAFT', value: 'DRAFT' },
  { text: '已关闭 CLOSED', value: 'CLOSED' },
];

export default function CustomsFeePage() {
  return (
    <PurchaseDocPage
      docType="CUSTOMS_DECLARATION"
      table="customs_declaration"
      lineTable="customs_fee_line"
      lineFk="customs_declaration_id"
      title="报关费补录"
      subtitle="已放行进口报关单登记费用 · 分摊回写批次到岸成本"
      domain="报关"
      numberField="declaration_number"
      statusEnum={STATUS_ENUM}
      // 费用子表随「登记费用」边提交；本页不在草拟态改头明细，仅 RELEASED 登记费用。
      editableStates={[]}
      lineTitle="报关费 / 运费明细（费用类型 / 金额 / 币种 / 货代账单号 / 分摊方式 · 网格录入）"
      newLabel="新建报关单"
      primaryToStates={['RELEASED']}
      intro={{
        title: '报关费 / 运费货代账单后到（货物入库之后才来），物流主任在已放行的进口报关单上「登记费用」，系统按「申报金额占比 / 数量占比」分摊回写各入库批次到岸成本。',
        description: '操作：进已放行进口报关单 → 抽屉里费用子表网格录入报关费 / 运费（报关费 / 运费至少填一项）+ 货代账单号 + 分摊方式 → 引擎「登记费用」边触发分摊回写 effect（分摊合计=费用合计），并 enqueue 金蝶增量（随入库单，不做账）。出口方向无此动作。两张账单先后到可分两次登记，系统累加留痕。费用金额（amount / 分摊）对纯销售隐藏（利润防火墙）。',
      }}
      todoNote="报关费复用 CUSTOMS_DECLARATION doc_type + customs_fee_line 子表（/api/schema 已就绪）。「登记费用」为 RELEASED 自循环边（customs.allocate_fee_to_landed_cost effect 分摊回写 goods_receipt_line/inventory 到岸成本 + enqueue 金蝶增量，真实 HTTP 属段5）。dev 库 reseed 后 /api/transitions 出现该边，抽屉「登记费用（仅进口·分摊回写到岸成本）」按钮自动点亮；未点亮前抽屉如实显示无动作，不伪造分摊。"
    />
  );
}
