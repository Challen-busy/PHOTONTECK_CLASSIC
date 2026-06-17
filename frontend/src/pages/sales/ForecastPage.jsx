/**
 * ForecastPage —— 客户 Forecast 接单对接（PRD 05-客户销售-Forecast接单 05d；决策⑫薄 / 占位）
 *
 * 决策⑫范围待定 → 本批做薄：客户在其自有供应商系统发滚动预测 + 我们接单 / 回货期，SA 抄录进来
 *   留痕、当备货 / SO 输入依据。首期不直连客户异构系统（开关 CUSTOMER_PORTAL_SYNC_ENABLED 默认
 *   OFF），只提供一张有结构的录入网格。预测 → 备货建议（04b）、接单 → 转 SO（05b）两条接力线
 *   由后端 effect 派生。
 *
 * 复用积木 PurchaseDocPage（台账 → 右抽屉不跳页 → 动作按钮；走 /api/transitions + /api/transition
 *   元数据驱动）。后端未注册 customer_forecast doc_type 时 /api/schema 失败 → 本页如实显示
 *  「功能已就绪 · 待后端开通」占位（14 律 §8 + 决策⑫薄实现），注册后自动点亮、不写死状态码。
 *
 * ★引擎实况（已勘 /api/transitions 2026-06-17）：CUSTOMER_FORECAST doc_type 尚未注册。
 *   后端段3c 注册（customer_forecast 表 + customer_forecast_line 滚动月份子表 FK forecast_id +
 *   三态 WorkflowDefinition DRAFT→ANSWERED→ARCHIVED）后本页自动点亮。
 */
import PurchaseDocPage from '../purchase/PurchaseDocPage';

// 状态药丸候选（轻量三态；仅台账筛选提示，真实边以 /api/transitions 为准）
const STATUS_ENUM = [
  { text: '录入 DRAFT', value: 'DRAFT' },
  { text: '已确认 CONFIRMED', value: 'CONFIRMED' },
  { text: '已被替代 SUPERSEDED', value: 'SUPERSEDED' },
];

export default function ForecastPage() {
  return (
    <PurchaseDocPage
      docType="CUSTOMER_FORECAST"
      table="customer_forecast"
      lineTable="customer_forecast_line"
      lineFk="customer_forecast_id"
      title="Forecast 接单"
      subtitle="客户滚动需求预测抄录 + 交叉应答 gap（决策⑫薄 / 首期手录不直连客户系统）"
      numberField="forecast_number"
      statusEnum={STATUS_ENUM}
      editableStates={['DRAFT']}
      lineTitle="型号 × 月份 × 预测量 + 交叉应答（网格录入）"
      newLabel="新建预测单"
      primaryToStates={['CONFIRMED']}
      intro={{
        title: 'Forecast 接单 = 客户 / 客户系统名 / 版本期次 + 型号 × 月份 × 预测量滚动网格 + 交叉应答（我方应答量 / 应答货期 → gap 量 / gap 天 → 提拉 / 推迟 / 正常）。决策⑫薄实现：首期手录抄写、不直连客户异构系统（开关默认 OFF）',
        description: 'SA 核心操作：把客户在其自有供应商系统发布的滚动预测抄录进来留痕，取我方内部货期（PA 回的）vs 客户需求做交叉应答、看 gap、标动作（提拉 / 推迟 / 正常）。两条接力线（默认提醒、不自动建单、不绕审批）：① 预测行「起备货」派生 04b 备货申请草稿（source_forecast_line_id 回链，发起人在 04b 补全风险点 / 金额走会审）；② 接单转 05b SO 草稿（客户订单号 → SO「编号」字段）。本单签单前前瞻、无财务关卡、不推金蝶。直连客户系统（拉 Forecast / 推回货期）为后期 ➕，开关 CUSTOMER_PORTAL_SYNC_ENABLED 默认 OFF。动作按钮一律由引擎流程边生成 → /api/transition 唯一写入路径，不写死状态码。',
      }}
      todoNote="Forecast 接单（决策⑫薄 / 占位）为新增 doc_type CUSTOMER_FORECAST（引擎无现成预测模型、无外部客户系统集成）。需后端段3c：① 新增 customer_forecast 表（forecast_number 月度连号 + customer_id / source_portal / forecast_version / product_line 等）+ 滚动月份子表 customer_forecast_line（FK forecast_id，型号 × 月份逐行排布，纯 SubTableEditor ✅；横向月份列组为可选 ➕）；② 三态 WorkflowDefinition（DRAFT→ANSWERED→ARCHIVED，节点级 allowed_roles 含 SA / SALES，规避 D-02e）；③ gap 量 / gap 天派生只读列；④ 预测行 → 04b 备货草稿 EXPLICIT effect（默认人工触发）。接单应答（forecast_acceptance → 转 SO）与接单台账可同期或后续薄补。注册后本页自动点亮。本批为薄 / 占位实现：未注册时显示「功能已就绪 · 待开通」（决策⑫范围待甲方拍板）。"
    />
  );
}
