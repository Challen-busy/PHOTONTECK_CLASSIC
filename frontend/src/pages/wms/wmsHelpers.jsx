/* eslint-disable react-refresh/only-export-components -- 纯渲染辅助函数模块（非组件），不参与 HMR 组件刷新 */
/**
 * wmsHelpers —— WMS 入库/库存页纯函数与常量（无 JSX 组件，便于 HMR 与复用）
 *
 *  - WMS_STATUS_STYLE  入库单/库存/流水状态色集（值集与引擎对齐；扩态自动落默认色）
 *  - renderCellByField schema field → 台账单元格内容（千分位/日期/状态药丸/空值灰杠）
 *  - schemaToColumns   /api/schema fields → BizTable columns（系统列隐藏、数字右对齐、首列冻结）
 *
 * 设计取向：列一律由 schema 渲染（不写死成本列；成本列由后端字段防火墙对 SALES 遮蔽，schema 不返回即不出列）。
 */
import { StatusPillInline } from './StatusPill';

export { WMS_STATUS_STYLE } from './wmsStatusStyle';

const MONO = 'ui-monospace, SFMono-Regular, Menlo, monospace';

const TYPE_TO_VALUETYPE = {
  integer: 'digit', number: 'digit', datetime: 'dateTime',
  date: 'date', boolean: 'select', json: 'jsonCode', text: 'textarea', string: 'text',
};

// 台账默认隐藏的系统/审计列（仍可在抽屉详情看）
export const HIDDEN_IN_TABLE = new Set([
  'created_by_id', 'updated_by_id', 'company_id', 'created_at', 'updated_at',
  'workflow_id', 'workflow_version', 'is_auto_generated',
]);

/** 单元格渲染：状态药丸 / 千分位右对齐 / 日期裁切 / 空值灰杠 */
export function renderCellByField(field, v, statusFields = ['status', 'movement_type']) {
  if (v == null || v === '') return <span style={{ color: '#bfbbb5' }}>—</span>;
  if (statusFields.includes(field.name)) return <StatusPillInline value={v} />;
  if (field.type === 'boolean') return v ? '是' : '否';
  if (field.type === 'number' || field.type === 'integer') {
    return <span style={{ fontFamily: MONO }}>{Number(v).toLocaleString()}</span>;
  }
  if ((field.type === 'datetime' || field.type === 'date') && typeof v === 'string') {
    return v.slice(0, field.type === 'date' ? 10 : 19).replace('T', ' ');
  }
  if (typeof v === 'object') return <span style={{ color: '#777169' }}>{JSON.stringify(v).slice(0, 60)}</span>;
  return String(v);
}

/**
 * /api/schema fields → BizTable columns（schema 驱动；成本列若被防火墙遮蔽则 fields 里本就没有）。
 */
export function schemaToColumns(fields = [], opts = {}) {
  const {
    frozen = [], statusFilter = [], statusEnum = {},
    actionCol, statusFields = ['status', 'movement_type'],
  } = opts;
  const usable = fields.filter((f) => !f.primary_key && !HIDDEN_IN_TABLE.has(f.name));
  const ordered = [
    ...frozen.map((n) => usable.find((f) => f.name === n)).filter(Boolean),
    ...usable.filter((f) => !frozen.includes(f.name)),
  ];
  const cols = ordered.map((f, idx) => {
    const isFrozen = frozen.includes(f.name);
    const isNum = f.type === 'number' || f.type === 'integer';
    const isStatus = statusFields.includes(f.name);
    const col = {
      title: f.label || f.name,
      dataIndex: f.name,
      width: f.name === 'id' ? 70 : isFrozen ? 160 : 140,
      fixed: isFrozen && idx < frozen.length ? 'left' : undefined,
      ellipsis: f.type === 'text' || f.type === 'string',
      align: isNum ? 'right' : undefined,
      valueType: TYPE_TO_VALUETYPE[f.type] || 'text',
      render: (_, row) => renderCellByField(f, row[f.name], statusFields),
    };
    if (statusFilter.includes(f.name)) {
      col.valueType = 'select';
      col.valueEnum = (statusEnum[f.name] || []).reduce((acc, o) => {
        acc[o.value] = { text: o.text };
        return acc;
      }, {});
    } else if (!isStatus && isNum) {
      col.search = false;
    }
    return col;
  });
  if (actionCol) cols.push(actionCol);
  return cols;
}
