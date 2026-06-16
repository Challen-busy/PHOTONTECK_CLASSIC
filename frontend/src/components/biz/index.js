/**
 * biz/ —— AntD Pro 业务标准积木（UX 律 14 强制复用同一套壳）
 *
 *   BizTable        台账列表（ProTable：查询条 + 分页 + 列配置 + 密度 + rowSelection 批量 + 冻结列）
 *   BizDrawerForm   详情/录单抽屉（DrawerForm，不跳页）
 *   BizEditableTable 明细网格（EditableProTable：Tab/Enter、数字右对齐、Excel 式多行）
 *
 * 引擎映射（14 §组件落地）：BizTable≈DataExplorer 台账、BizDrawerForm+BizEditableTable≈DocEditor 主表+子表。
 */
export { default as BizTable } from './BizTable';
export { default as BizDrawerForm } from './BizDrawerForm';
export { default as BizEditableTable } from './BizEditableTable';
