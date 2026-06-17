/**
 * ServiceTicketPage —— 售后技术工单（PRD 05-客户销售-售后技术工单 05c ⭐）
 *
 * 轻量四态工单：客户报来技术问题/故障 → 建工单（客户/型号/问题/负责 FAE）→ FAE 答疑/判定/
 *   维修建议 → 关闭；需实物退换报原厂 → 旁路转 RMA（rma_id 关联，实物流转在 04b RMA 单）。
 *   产品部 FAE/PM 主处理、SALES/SA 提报。本单无财务硬关卡（纯技术流程），不推金蝶。
 *
 * 复用积木 PurchaseDocPage（台账 → 右抽屉不跳页 → 顶部动作按钮；动作一律由 /api/transitions
 *   按 doc_type+当前状态+角色过滤真实边 → /api/transition 唯一写入路径，不写死状态码）。
 *   多型号工单走可选子表 service_ticket_line（SubTableEditor 网格，多 SN 多行）。
 *
 * ★引擎实况（已勘 /api/transitions 2026-06-17）：SERVICE_TICKET doc_type 尚未在后端注册。
 *   后端段3c 注册（新增 service_ticket 表 + service_ticket_line 子表 FK service_ticket_id +
 *   一行 WorkflowDefinition OPEN→IN_PROGRESS→RESOLVED→CLOSED + ESCALATED_RMA 旁路）后本页
 *   自动点亮；未注册时 /api/schema 失败 → 显示「功能已就绪 · 待后端开通」占位（14 律 §8）。
 *   状态枚举仅作台账筛选提示，真实可走边以 /api/transitions 为准（不臆造推进）。
 */
import PurchaseDocPage from '../purchase/PurchaseDocPage';

// 状态药丸候选（轻量四态 + RMA 升级旁路；仅台账筛选提示，真实边以 /api/transitions 为准）
const STATUS_ENUM = [
  { text: '提报 OPEN', value: 'OPEN' },
  { text: '处理中 IN_PROGRESS', value: 'IN_PROGRESS' },
  { text: '★转 RMA ESCALATED_RMA', value: 'ESCALATED_RMA' },
  { text: '已解决 RESOLVED', value: 'RESOLVED' },
  { text: '已关闭 CLOSED', value: 'CLOSED' },
  { text: '已取消 CANCELLED', value: 'CANCELLED' },
];

export default function ServiceTicketPage() {
  return (
    <PurchaseDocPage
      docType="SERVICE_TICKET"
      table="service_ticket"
      lineTable="service_ticket_line"
      lineFk="service_ticket_id"
      title="售后技术工单"
      subtitle="客户报修 → FAE 答疑 / 质量判定 / 维修建议 → 关闭；需实物退换报原厂 → 旁路转 RMA（实物流转在 04b）"
      numberField="ticket_number"
      statusEnum={STATUS_ENUM}
      editableStates={['OPEN', 'IN_PROGRESS', 'ESCALATED_RMA', 'RESOLVED']}
      lineTitle="工单明细（多型号 / 多 SN 时启用 · 网格录入）"
      newLabel="新建工单"
      primaryToStates={['IN_PROGRESS', 'RESOLVED', 'CLOSED']}
      intro={{
        title: '售后技术工单 = 客户 / 型号 / 问题描述 / 负责 FAE（必填）+ 问题类型 / 处理方式 / 质量判定 / 维修建议 + 可选 SN-LOT / 关联 SO / 关联 RMA。轻量四态：提报 → FAE 处理 → 已解决 → 关闭；需实物退换报原厂走 ESCALATED_RMA 旁路（实物在 04b RMA 单）',
        description: '产品部 FAE / PM 为主处理人，SALES / SA 提报。① 提报建单必填客户 / 型号 / 问题描述 / 负责 FAE，缺任一不能提交；② FAE 接单处理填处理方式 + 处理过程 + 质量判定（良 / 不良），能远程答疑直接解决、需技术判定给维修建议；③ 判定要走实物退换 / 报原厂 → ESCALATED_RMA 旁路关联 / 派生 04b RMA（rma_id 回链），技术结论沉淀在本工单；④ 关闭前处理方式 + 处理过程 + 关闭结论必填（留痕）。SALES 看本人客户工单且无成本 / 价格列（本单无价格主线）。本单无财务硬关卡、不推金蝶（仅升级 RMA 时由 04b 入库审核推）。动作按钮一律由引擎流程边生成 → /api/transition 唯一写入路径，不写死状态码。',
      }}
      todoNote="售后技术工单为新增 doc_type SERVICE_TICKET（引擎 02 §2.9 排除「退货 / 售后」业务，引擎无现成脚手架）。需后端段3c：① 新增 service_ticket 表（ticket_number 月度连号 ST{YYMM}-{seq} + customer_id / material_id / issue_summary / issue_type / assignee_id / product_line / resolution_type / resolution_notes / quality_verdict / repair_advice / rma_id / sales_order_id 等）；② 可选子表 service_ticket_line（FK service_ticket_id，多型号 / 多 SN）；③ 一行 WorkflowDefinition（OPEN→IN_PROGRESS→RESOLVED→CLOSED 四态 + ESCALATED_RMA 旁路 + OPEN→CLOSED 直关 + RESOLVED→IN_PROGRESS 重开，节点级 allowed_roles 含 FAE / PM / SALES / SA，规避 D-02e 边级角色坑）；④ 可选 ESCALATED_RMA 推进 EXPLICIT effect 派生 04b RMA 草稿 + service_ticket_id 回链。注册后本页自动点亮（schema / transitions 驱动）。"
    />
  );
}
