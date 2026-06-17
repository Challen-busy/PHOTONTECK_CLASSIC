/**
 * SpecialShipmentPage —— 特批发货（先发后补单）（PRD 05-客户销售-订单与履约 页面4b ⭐；决策⑫可隐藏模块）
 *
 * 「发货申请必须关联 SO」硬规则（页面4 SHIPMENT）的唯一受控例外：客户尚未正式下单、因紧急 / 口头
 *   确认 / 战略客户需先发货 → SALES/SA 发起（客户 + 特批理由 + 风险承诺 + 预计补单期限 + 入仓编号
 *   明细，无 SO）→ ★FINANCE 财务特批审（取代必关联 SO 前置，最硬关卡，不批货坚决不出仓）→ 放行 →
 *   仓库出库（复用 03b 互检 + 扣库存）→ shipped_pending_so（待补单债务）→ 客户正式下单后 SA 补录
 *   SO 勾稽（回填 SO 号 / 抵减 SO 在途 / 补推金蝶销售源）→ reconciled → closed。
 *
 * ★可隐藏模块（决策⑫硬要求）：feature.special_batch_shipment（per-company 开关）上线默认 OFF
 *   → 导航不出入口（Layout 条件渲染）+ 创建权不可达；关闭时本页只读（历史特批单可查、不可新建）。
 *   特批走独立 doc_type SPECIAL_SHIPMENT，不污染正常 SHIPMENT 的必关联 SO 硬规则（二者隔离）。
 *
 * ★引擎实况（已勘 /api/transitions 2026-06-17）：SPECIAL_SHIPMENT doc_type 尚未注册、后端尚无
 *   feature flag 端点。开关暂以前端常量 FEATURE_SPECIAL_BATCH_SHIPMENT（默认 OFF）兜底，待后端
 *   ➕ /api/features（per-company）后改读后端配置。关 → 本页只读占位（历史可查、新建禁用）；
 *   开 → 复用 PurchaseDocPage（台账 → 抽屉 → 动作走 /api/transition），后端注册后自动点亮。
 */
import { Alert, Empty } from 'antd';
import PurchaseDocPage from '../purchase/PurchaseDocPage';

// 特批发货功能开关（决策⑫：上线默认隐藏 / OFF）。
// TODO(后端): 后端 ➕ /api/features（per-company feature.special_batch_shipment）后改读后端配置，
//   前端常量仅作未接入前的安全兜底（默认 OFF = 隐藏入口 + 禁新建）。
export const FEATURE_SPECIAL_BATCH_SHIPMENT = false;

// 状态药丸候选（含两段式：发货后待补单 → 补 SO 勾稽 → 关闭；仅筛选提示，真实边以 /api/transitions 为准）
const STATUS_ENUM = [
  { text: '发起（无 SO）DRAFT', value: 'DRAFT' },
  { text: '★财务特批审 FINANCE_SPECIAL_APPROVAL', value: 'FINANCE_SPECIAL_APPROVAL' },
  { text: '特批放行 APPROVED', value: 'APPROVED' },
  { text: '已发货 · 待补单 SHIPPED_PENDING_SO', value: 'SHIPPED_PENDING_SO' },
  { text: '已补单勾稽 RECONCILED', value: 'RECONCILED' },
  { text: '已关闭 CLOSED', value: 'CLOSED' },
  { text: '已取消 CANCELLED', value: 'CANCELLED' },
];

const PageHeader = () => (
  <div style={{ marginBottom: 16 }}>
    <h2 style={{ fontSize: 26, fontWeight: 300, letterSpacing: '-0.01em', color: '#000', margin: 0, lineHeight: 1.2 }}>
      特批发货（先发后补单）
    </h2>
    <span style={{ color: '#777169', fontSize: 13 }}>
      客户 / 销售 · 引擎单据 <code>SPECIAL_SHIPMENT</code> · 可隐藏模块（决策⑫，默认隐藏）
    </span>
  </div>
);

export default function SpecialShipmentPage() {
  // 开关 OFF：模块隐藏 → 本页只读占位（历史特批单可查、不可新建）。
  if (!FEATURE_SPECIAL_BATCH_SHIPMENT) {
    return (
      <div>
        <PageHeader />
        <Alert
          type="info" showIcon style={{ marginBottom: 16, borderRadius: 12 }}
          title="特批发货为可隐藏模块 · 当前未开通（默认隐藏）"
          description="特批发货（先发后补单）是「发货申请必须关联 SO」硬规则的唯一受控例外：客户未正式下单、因紧急 / 口头确认 / 战略客户需先发货 → ★FINANCE 财务特批审（取代必关联 SO 前置）→ 放行出库 → 挂「待补单」债务 → 客户正式下单后 SA 补录 SO 勾稽（回填 SO 号 / 抵减 SO 在途 / 补推金蝶）。按决策⑫上线默认 OFF（导航不出入口 + 禁新建），待甲方上线后实际反馈再 per-company 启用。正常发货（SHIPMENT，发货申请页）仍维持「必关联 SO」零容忍，二者走独立 doc_type 互不污染。"
        />
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="特批发货模块未开通（feature.special_batch_shipment = OFF）" />
      </div>
    );
  }

  // 开关 ON：复用通用单据页（台账 → 抽屉 → 动作走 /api/transition）。
  return (
    <PurchaseDocPage
      docType="SPECIAL_SHIPMENT"
      table="special_shipment"
      lineTable="special_shipment_line"
      lineFk="special_shipment_id"
      title="特批发货（先发后补单）"
      subtitle="无 SO 例外出库 · ★财务特批审 + 强制事后补单勾稽（决策⑫可隐藏模块）"
      numberField="shipment_number"
      statusEnum={STATUS_ENUM}
      editableStates={['DRAFT', 'SHIPPED_PENDING_SO']}
      lineTitle="入仓编号明细（逐行指定要发批次 · 串货隔离 · 网格录入）"
      newLabel="发起特批发货"
      primaryToStates={['FINANCE_SPECIAL_APPROVAL', 'APPROVED', 'RECONCILED', 'CLOSED']}
      intro={{
        title: '特批发货 = 客户 + 特批理由 + 风险承诺 / 授权人 + 预计补单期限 + 入仓编号明细（无 SO）。先发后补单：★FINANCE 财务特批审 → 放行出库（复用 03b 互检 + 扣库存）→ 已发货 · 待补单 → 客户正式下单后 SA 补录 SO 勾稽（回填 SO 号 / 抵减 SO 在途 / 补推金蝶）→ 关闭',
        description: '⚠️ 这是「发货申请必须关联 SO」硬规则的唯一受控例外（独立 doc_type，不污染正常 SHIPMENT 必关联硬规则）。① 发起无 SO（与正常发货根本区别），录特批理由 / 风险承诺 / 预计补单期限（默认 +30 天，逾期升级催办）/ 入仓编号明细（串货隔离同正常发货）；② ★FINANCE 财务特批审是最硬关卡，核未下单先发货的风险 / 授信 / 客户资质 / 特批理由，财务不批货坚决不出仓；③ 出库后挂「待补单」债务（工作台红色待办）直到补录 SO 勾稽；④ 必须勾稽才能闭环（回填 SO 号、抵减 SO 在途、补推 / 改推金蝶销售源）。金蝶：发货后先以「特批出库来源标记」推，补单后回链 SO 补推。动作按钮一律由引擎流程边生成 → /api/transition 唯一写入路径，不写死状态码。',
      }}
      todoNote="特批发货为新增独立 doc_type SPECIAL_SHIPMENT（决策⑫可隐藏模块，与正常 SHIPMENT 隔离、不动其必关联 SO 硬规则）。需后端段3c：① 新增 special_shipment 表（special_shipment_number 月度连号 SS{YYMM}-{seq} + customer_id / special_reason / risk_commitment / authorized_by / expected_so_date / sales_order_id[补单后回填] 等，发起态无 SO）+ 子表 special_shipment_line（FK special_shipment_id，入仓编号明细，复用 03b 库存批次串货隔离）；② WorkflowDefinition（DRAFT→FINANCE_SPECIAL_APPROVAL[★节点级 allowed_roles=[FINANCE]]→APPROVED→[复用 03b 出库]→SHIPPED_PENDING_SO→RECONCILED→CLOSED）；③ 出库 / 补单两段式金蝶推送（先特批来源标记、补单后回链 SO 改推销售源）；④ feature flag per-company 端点 /api/features（feature.special_batch_shipment 默认 OFF）——接入后本页 FEATURE_SPECIAL_BATCH_SHIPMENT 改读后端、Layout 入口随开关条件渲染。注册 + 开关 ON 后本页自动点亮。"
    />
  );
}
