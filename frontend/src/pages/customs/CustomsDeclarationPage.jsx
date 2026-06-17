/**
 * CustomsDeclarationPage —— 报关单台账（进口 / 出口 / 退运三方向）⭐（PRD 06-1）
 *
 * 复用采购域通用单据壳 PurchaseDocPage（台账→右抽屉不跳页→顶部动作按钮，动作一律
 * 由 /api/transitions 真实边渲染 → /api/transition 唯一写入路径；纯 schema 驱动子表网格）。
 *
 * ★真值（已勘 /api/schema 2026-06-17）：
 *   - doc_type=CUSTOMS_DECLARATION、头表 customs_declaration（号 declaration_number，CD{YYMM}-{seq}）
 *   - 商品明细子表 customs_declaration_line（FK customs_declaration_id）
 *     合规五件套录入列：hs_code_cn(HS 中国/报关地码) / origin_country(原产国) / cn_name(中文品名)
 *     / eccn(ECCN) / hs_code_origin(原产 HS 参考) + material_id / quantity / uom / declared_amount。
 *   - 状态码 DRAFT→SUBMITTED→RELEASED→CLOSED + REJECTED + CANCELLED（以 WorkflowDefinition 为准，
 *     statusEnum 仅作台账筛选提示；真实可走边以 /api/transitions 为准，不写死推进）。
 *   - 方向 direction：IMPORT 进口 / EXPORT 出口 / RE_EXPORT 退运出口（无「退关进口」，SOP §四-1）。
 *
 * ★引擎实况：customs_declaration 表 /api/schema 已就绪（本页台账即可渲染）。WorkflowDefinition
 *   CUSTOMS_DECLARATION 由后端写入 phase1_workflows.py，待 dev 库 reseed 后 /api/transitions
 *   出现「申报 / 海关放行 / 海关退单 / 重新申报 / 登记费用 / 关闭」边，抽屉动作按钮自动点亮。
 *   未点亮前抽屉显示「当前状态无可执行动作」（PurchaseDocPage 既有优雅降级），不写死状态码。
 */
import PurchaseDocPage from '../purchase/PurchaseDocPage';

// 台账状态筛选提示（真实可走边以 /api/transitions 为准）
const STATUS_ENUM = [
  { text: '草拟 DRAFT', value: 'DRAFT' },
  { text: '已申报 SUBMITTED', value: 'SUBMITTED' },
  { text: '已放行 RELEASED', value: 'RELEASED' },
  { text: '已退单 REJECTED', value: 'REJECTED' },
  { text: '已关闭 CLOSED', value: 'CLOSED' },
  { text: '已取消 CANCELLED', value: 'CANCELLED' },
];

export default function CustomsDeclarationPage() {
  return (
    <PurchaseDocPage
      docType="CUSTOMS_DECLARATION"
      table="customs_declaration"
      lineTable="customs_declaration_line"
      lineFk="customs_declaration_id"
      title="报关单"
      subtitle="进口 IMPORT / 出口 EXPORT / 退运 RE_EXPORT · 报关自己做（决策⑪）"
      domain="报关"
      numberField="declaration_number"
      statusEnum={STATUS_ENUM}
      editableStates={['DRAFT', 'REJECTED']}
      lineTitle="商品明细（HS 中国码 / 原产国 / 中文品名 / ECCN / 数量 / 申报金额 · 网格录入）"
      newLabel="新建报关单"
      primaryToStates={['SUBMITTED', 'RELEASED']}
      intro={{
        title: '一张报关单 = 一票报关；方向选进口 / 出口 / 退运。商品明细从关联出入库批次聚合为真相（退运手补行），报关地决定 HS 取中国 / 香港口径。',
        description: '★申报硬拦（合规五件套）：草拟态 HS 报关地码 / 原产国 / 中文品名 / ECCN（退运放宽 ECCN）可空可改，点「申报」时逐行硬拦——任一缺失被引擎拒绝并返回 rule_failures 指出哪行缺哪项，同时自动派 PA 补录待办。退运方向另校「原进口报关单」限本公司已放行进口单（→香港退香港物理保证）。动作按钮一律由引擎流程边生成 → /api/transition，不写死状态码。报关单据默认不推金蝶。',
      }}
      todoNote="报关单复用引擎 CUSTOMS_DECLARATION doc_type + customs_declaration_line 子表（/api/schema 已就绪）。WorkflowDefinition（DRAFT→SUBMITTED→RELEASED→CLOSED + REJECTED + CANCELLED，申报闸挂 customs.validate_compliance_pack + 派 PA 补录 effect、放行回写报关单号 effect）由后端 phase1_workflows.py 注册；dev 库 reseed 后 /api/transitions 出现真实边，抽屉动作按钮自动点亮。未点亮前抽屉如实显示「当前状态无可执行动作」、不伪造推进。"
    />
  );
}
