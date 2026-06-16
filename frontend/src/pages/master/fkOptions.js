/**
 * fkOptions —— 主数据表单的外键 cell 选择器候选集加载（UX 律 14：fk→cell 选择器）
 *
 * 引擎 /api/query 返回的是裸 FK id（不带 join 显示名），故选择器在前端按
 * 「显示名优先列」把 id→人类可读标签映射出来。优先列与后端 tools.py 的
 * search_fields / 显示约定一致：short_name > name > line_name > internal_code >
 * uom_code > hs_number > code > sku > description。
 *
 * 纯查询（只读 /api/query），不写、不绕底座。
 */
import { query } from '../../api';

// FK 目标表 → 候选集查询表（schema.fk.table 即可直接用）
const DISPLAY_FIELDS = [
  'short_name', 'name', 'line_name', 'internal_code',
  'uom_code', 'hs_number', 'code', 'sku', 'description', 'uom_name',
];

export function displayName(row) {
  if (!row) return '';
  for (const f of DISPLAY_FIELDS) {
    if (row[f] != null && row[f] !== '') return String(row[f]);
  }
  return row.id != null ? `#${row.id}` : '';
}

// 角色过滤：fk 指向 user_account 时按业务角色收窄候选（PM/PA/FAE/SALES）
// 字段名 → 角色（与 PRD 02 cell 选择器「角色=…」一致）
export const FK_ROLE_HINT = {
  owner_sales_id: 'SALES_ASSISTANT',
  responsible_pa_id: 'PRODUCT_ASSISTANT',
  backup_pa_id: 'PRODUCT_ASSISTANT',
  pm_id: 'PRODUCT_MANAGER',
  fae_id: 'PRODUCT_ENGINEER',
  pa_id: 'PRODUCT_ASSISTANT',
};

/**
 * 取一个 FK 字段的候选 options（[{label,value}]）。
 * @param {string} fkTable schema.fk.table（如 supplier / user_account / hs_code）
 * @param {string} fieldName 当前字段名（用于 user_account 角色过滤）
 */
export async function loadFkOptions(fkTable, fieldName) {
  try {
    const { data } = await query(fkTable, { limit: 100 });
    let rows = data?.data || [];
    const roleHint = FK_ROLE_HINT[fieldName];
    if (fkTable === 'user_account' && roleHint) {
      rows = rows.filter((r) => !r.role || r.role === roleHint || r.role === 'ADMIN');
    }
    return rows.map((r) => ({ label: displayName(r), value: r.id }));
  } catch {
    return [];
  }
}
