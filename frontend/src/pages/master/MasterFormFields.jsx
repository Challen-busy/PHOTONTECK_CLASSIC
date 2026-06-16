/**
 * MasterFormFields —— 主数据建档/改档表单字段（schema 驱动，落 UX 律 14 录单）
 *
 *  - 从 /api/schema 的 fields 自动生成 ProForm 控件：
 *      string→ProFormText, text→ProFormTextArea, number/integer→ProFormDigit,
 *      boolean→ProFormSwitch, date/datetime→ProFormDatePicker, fk→ProFormSelect(cell 选择器)
 *  - 枚举类（status / region / grade / control_mode / supplier_type / label_type 等）
 *    用受控选项渲下拉（值翻译走 ENUM_OPTIONS）。
 *  - 系统/审计字段（id、company_id、created_by、updated_by、status、单号列）不进表单
 *    （由引擎 _create_blank 自动填）。
 *
 * 不含提交逻辑（提交在 MasterDataPage.onFinish 走 /api/transition），本组件只渲控件。
 */
import { useEffect, useState } from 'react';
import {
  ProFormText, ProFormTextArea, ProFormDigit,
  ProFormSwitch, ProFormSelect, ProFormDatePicker,
} from '@ant-design/pro-components';
import { loadFkOptions } from './fkOptions';

// 表单不录入的系统/自动字段（引擎自动填或只读展示）
const SYSTEM_FIELDS = new Set([
  'id', 'company_id', 'created_by_id', 'updated_by_id',
  'created_at', 'updated_at', 'status', 'line_number',
]);

// 业务枚举选项（值翻译与 PRD 02 / 09 一致；后端为 String 列，前端给受控候选）
const ENUM_OPTIONS = {
  region: [
    { label: 'HK', value: 'HK' }, { label: '内地', value: 'CN' }, { label: '海外', value: 'OVERSEAS' },
  ],
  grade: [
    { label: '大客户', value: 'KEY' }, { label: '小客户', value: 'SMALL' },
  ],
  supplier_type: [
    { label: '原厂', value: 'OEM' }, { label: '代理', value: 'AGENT' },
  ],
  control_mode: [
    { label: 'SN（逐件）', value: 'SN' }, { label: 'LOT（批次）', value: 'LOT' },
  ],
  hs_region: [
    { label: '原产国', value: 'ORIGIN' }, { label: '中国', value: 'CN' },
  ],
  location_type: [
    { label: '普通', value: 'NORMAL' }, { label: '流转仓', value: 'TRANSIT' },
    { label: 'RMA', value: 'RMA' }, { label: '样品', value: 'SAMPLE' },
    { label: '待处理', value: 'PENDING' }, { label: 'NG', value: 'NG' },
  ],
};

// 字段名 → 中文占位/提示（少量关键字段，其余用 label）
function placeholderFor(f) {
  return `请输入${f.label || f.name}`;
}

function FkSelect({ field, fkTable }) {
  const [options, setOptions] = useState([]);
  useEffect(() => {
    let alive = true;
    loadFkOptions(fkTable, field.name).then((opts) => { if (alive) setOptions(opts); });
    return () => { alive = false; };
  }, [fkTable, field.name]);
  return (
    <ProFormSelect
      name={field.name}
      label={field.label || field.name}
      options={options}
      showSearch
      rules={!field.nullable ? [{ required: true, message: `请选择${field.label || field.name}` }] : undefined}
      fieldProps={{ optionFilterProp: 'label' }}
    />
  );
}

/** 单个 schema field → ProForm 控件 */
function renderFormField(field) {
  if (SYSTEM_FIELDS.has(field.name) || field.primary_key) return null;

  const required = !field.nullable && !field.has_default;
  const requiredRule = required ? [{ required: true, message: `请填写${field.label || field.name}` }] : undefined;
  const key = field.name;

  // 外键 → cell 选择器
  if (field.fk?.table) {
    return <FkSelect key={key} field={field} fkTable={field.fk.table} />;
  }

  // 受控枚举（按字段名 / hs_code.region 特例）
  const enumKey = field.name === 'region' && field.label?.includes('原产') ? 'hs_region' : field.name;
  if (ENUM_OPTIONS[enumKey]) {
    return (
      <ProFormSelect
        key={key} name={field.name} label={field.label || field.name}
        options={ENUM_OPTIONS[enumKey]} rules={requiredRule}
      />
    );
  }

  switch (field.type) {
    case 'boolean':
      return <ProFormSwitch key={key} name={field.name} label={field.label || field.name} />;
    case 'integer':
    case 'number':
      return (
        <ProFormDigit
          key={key} name={field.name} label={field.label || field.name}
          rules={requiredRule}
          fieldProps={{ precision: field.type === 'integer' ? 0 : undefined, style: { width: '100%' } }}
        />
      );
    case 'date':
    case 'datetime':
      return (
        <ProFormDatePicker
          key={key} name={field.name} label={field.label || field.name}
          rules={requiredRule}
          fieldProps={{ style: { width: '100%' }, showTime: field.type === 'datetime' }}
        />
      );
    case 'text':
      return (
        <ProFormTextArea
          key={key} name={field.name} label={field.label || field.name}
          rules={requiredRule} placeholder={placeholderFor(field)}
          fieldProps={{ autoSize: { minRows: 2, maxRows: 4 } }}
        />
      );
    default:
      return (
        <ProFormText
          key={key} name={field.name} label={field.label || field.name}
          rules={requiredRule} placeholder={placeholderFor(field)}
        />
      );
  }
}

/**
 * 渲染一组表单字段（建档/改档）。
 * @param {object[]} fields schema.fields
 * @param {string[]} hidden 额外隐藏的字段名（如改档时锁定的编号列）
 */
export default function MasterFormFields({ fields = [], hidden = [] }) {
  const hideSet = new Set(hidden);
  return fields
    .filter((f) => !hideSet.has(f.name))
    .map((f) => renderFormField(f))
    .filter(Boolean);
}
