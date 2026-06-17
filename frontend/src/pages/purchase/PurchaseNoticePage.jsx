/**
 * PurchaseNoticePage —— 采购通知 / 采购需求（PRD 04a-5）
 *
 * 复用 PURCHASE_NOTICE doc_type + purchase_notice_line 子表（✅引擎已存在）。
 * 头：关联 SO / 发起人 / 采购助理 PA / 需求交期 / 状态；明细网格：型号 / 数量 / 建议供应商 / 需求交期 / 包装条码要求。
 *
 * 本段对齐使 PA/SA 可手建采购通知；SO 审核 → 自动派生采购通知的 effect 归后端段3（SO 就绪后），本页支持手工建单。
 */
import PurchaseDocPage from './PurchaseDocPage';

const STATUS_ENUM = [
  { text: 'DRAFT 草稿', value: 'DRAFT' },
  { text: '待下单 PENDING_PO', value: 'PENDING_PO' },
  { text: '已下单 ORDERED', value: 'ORDERED' },
  { text: '关闭 CLOSED', value: 'CLOSED' },
];

export default function PurchaseNoticePage() {
  return (
    <PurchaseDocPage
      docType="PURCHASE_NOTICE"
      table="purchase_notice"
      lineTable="purchase_notice_line"
      lineFk="purchase_notice_id"
      title="采购通知"
      subtitle="SO 审核派生 + PA / SA 手建采购需求"
      numberField="notice_number"
      statusEnum={STATUS_ENUM}
      editableStates={['DRAFT']}
      lineTitle="采购需求明细（型号 / 数量 / 建议供应商 / 需求交期 / 包装条码要求 · 网格录入）"
      scanSequence={['material_id', 'quantity']}
      newLabel="新建采购通知"
      primaryToStates={['PENDING_PO', 'ORDERED']}
      intro={{
        title: '一张采购通知 = “PA 该下哪些 PO” 的需求项；来源① SO 审核派生（后端段3 effect）② PA / SA 手建（备货 / 补货）',
        description: 'SA 在通知里写清采购型号 / 数量 / 哪个客户 / 付款方式 / 签单公司；PA + PM 确认后据通知建 PO（PO 头回链 purchase_notice_id）。DRAFT 态可改头与明细；推进经待下单 → 已下单 → 关闭。',
      }}
      todoNote="采购通知复用引擎现有 PURCHASE_NOTICE doc_type + purchase_notice_line 子表（✅已存在）。若 /api/schema 失败，需后端段2b 确认轻量流程（DRAFT→待下单→已下单→关闭）+ notice_number 月度连号编号规则已注册。SO 审核 → 采购通知派生 effect 归后端段3。"
    />
  );
}
