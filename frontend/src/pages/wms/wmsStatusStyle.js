/**
 * WMS 状态色集（引擎真实 state code；PRD 03a 状态机 + 库存 7 态 + 流水类型）。
 * 扩态自动落默认色（StatusPill 兜底）。单独成文件避免组件/纯函数互相依赖成环。
 */
export const WMS_STATUS_STYLE = {
  // GOODS_RECEIPT 单据态（引擎实况：PENDING / PA_REVIEW / STOCKED_IN / CANCELLED）
  PENDING:    { bg: '#fbf5e4', color: '#b8860b' },
  PA_REVIEW:  { bg: '#eaf1fb', color: '#1f5aa8' },
  STOCKED_IN: { bg: '#ebf5ee', color: '#1f8f3a' },
  CANCELLED:  { bg: '#fdecea', color: '#b42318' },
  // SHIPMENT 出库单 10 态（引擎实况 seed：DRAFT→FINANCE_APPROVAL→EXCEPTION_APPROVAL→
  // PACKING_LABELING→PICKING_RECHECK→SALES_OUTBOUND→CUSTOMER_RECEIVED/RETURN_REQUESTED/CANCELLED）
  DRAFT:             { bg: '#fbf5e4', color: '#b8860b' },
  FINANCE_APPROVAL:  { bg: '#eaf1fb', color: '#1f5aa8' },
  EXCEPTION_APPROVAL:{ bg: '#fdecea', color: '#b42318' },
  PACKING_LABELING:  { bg: '#f1ebfa', color: '#6b46c1' },
  PICKING_RECHECK:   { bg: '#e7f3f5', color: '#0e7490' },
  SALES_OUTBOUND:    { bg: '#ebf5ee', color: '#1f8f3a' },
  CUSTOMER_RECEIVED: { bg: '#ebf5ee', color: '#1f8f3a' },
  RETURN_REQUESTED:  { bg: '#fdecea', color: '#b42318' },
  // 库存 7 态（AVAILABLE/RESERVED 引擎已有；其余 PRD E2 扩展，后端补值后自动显示）
  AVAILABLE:   { bg: '#ebf5ee', color: '#1f8f3a' },
  RESERVED:    { bg: '#fbf5e4', color: '#b8860b' },
  QUARANTINE:  { bg: '#fbf5e4', color: '#b8860b' },
  NG:          { bg: '#fdecea', color: '#b42318' },
  SAMPLE:      { bg: '#f1ebfa', color: '#6b46c1' },
  VENDOR_HOLD: { bg: '#e7f3f5', color: '#0e7490' },
  SCRAP:       { bg: '#f5f5f5', color: '#1a1a1a' },
  DAMAGED:     { bg: '#fdecea', color: '#b42318' },
  // 流水类型
  IN:           { bg: '#ebf5ee', color: '#1f8f3a' },
  OUT:          { bg: '#fdecea', color: '#b42318' },
  RESERVE:      { bg: '#fbf5e4', color: '#b8860b' },
  RELEASE:      { bg: '#e7f3f5', color: '#0e7490' },
  TRANSFER_IN:  { bg: '#ebf5ee', color: '#1f8f3a' },
  TRANSFER_OUT: { bg: '#fdecea', color: '#b42318' },
  COUNT_ADJUST: { bg: '#f1ebfa', color: '#6b46c1' },
  STATUS_CHANGE:{ bg: '#eaf1fb', color: '#1f5aa8' },
};
