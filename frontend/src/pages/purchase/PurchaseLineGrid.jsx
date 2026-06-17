/**
 * PurchaseLineGrid —— 采购域单据子表网格（schema 驱动 · 录单增强 14 律）
 *
 * 通用：列由 lineTable 的 /api/schema 驱动（后端 ➕ 列自动出现，对原厂单价/佣金等买价列
 * 由后端字段防火墙对 SALES/SA 遮蔽 → schema 不返回即不渲，本组件不写死价格列）。
 *
 * 录单增强（落 UX 律 14 §3）：
 *   ① Excel 粘贴整块建行：粘贴 TSV → 按可见录入列顺序建多行（访谈 02:646）
 *   ② 扫码枪入格：调用方传 scanSequence 时开「扫码模式」顺序锁，扫一格聚焦下一格（PRD E6）
 *   ③ FK 列 → cell 选择器（loadFkOptions），数字列右对齐（BizEditableTable 兜底）
 *
 * ★段1b 教训：子表派生 _ 列（仅展示用）一律以 `_` 前缀命名，提交前由父页 buildSubUpdates
 *   统一 strip 掉 `_` 前缀键（防 buildSubUpdates 剥键丢真值）。本网格直接编辑真列名，
 *   不引入派生写入列；展示用映射在 render 内完成，不落 value。
 *
 * ⚠️ 不绕底座：本组件只产出子表行 value，写入由父页 sub_updates 走引擎唯一路径 /api/transition。
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { App, Button, Tag, Tooltip } from 'antd';
import { ScanOutlined, SnippetsOutlined, CameraOutlined } from '@ant-design/icons';
import { BizEditableTable } from '../../components/biz';
import { getSchema } from '../../api';
import { loadFkOptions } from '../master/fkOptions';

const NUMERIC_TYPES = new Set(['number', 'integer']);

// 子表不进网格的系统/自动列（父 FK 由调用方传 lineFk）
const BASE_SKIP = new Set([
  'id', 'created_at', 'updated_at', 'created_by_id', 'updated_by_id',
  'company_id', 'line_number',
]);

// 业务枚举（与 PRD 04a-2 取值集一致；后端为 String 列，前端给受控候选）
const ENUM_OPTIONS = {
  currency: [
    { label: 'USD', value: 'USD' }, { label: 'CNY', value: 'CNY' },
    { label: 'HKD', value: 'HKD' }, { label: 'EUR', value: 'EUR' },
  ],
  uom: [
    { label: 'pcs', value: 'pcs' }, { label: '包', value: '包' },
    { label: '盘', value: '盘' }, { label: 'm', value: 'm' },
  ],
  mode: [
    { label: 'Resell', value: 'Resell' }, { label: 'Sample', value: 'Sample' },
    { label: 'Buffer', value: 'Buffer' },
  ],
};

const COL_WIDTH = {
  material_id: 160, product_description: 200, description: 200, quantity: 110,
  target_unit_price: 120, unit_price: 120, currency: 100, uom: 90,
  lead_time: 120, shipment_terms: 140, payment_terms: 150, inquiry_date: 130,
  customer_id: 150, supplier_id: 150, sales: 120, commission: 110, mode: 110,
  remarks: 200, notes: 180, preferred_supplier_id: 160,
  required_delivery_date: 130, requested_delivery_date: 130,
  sales_order_line_id: 150, packaging_requirements: 160, barcode_requirements: 160,
};

/**
 * @param {object[]} value          子表行
 * @param {function} onChange        行变更回调
 * @param {string}   lineTable       子表名（如 sales_inquiry_line）
 * @param {string}   lineFk          父 FK 列名（如 inquiry_id），跳过不进网格
 * @param {string[]} scanSequence    扫码顺序锁字段序列（不传则不显示扫码模式）
 * @param {string[]} extraSkip       额外跳过列
 */
export default function PurchaseLineGrid({
  value = [], onChange, lineTable, lineFk,
  scanSequence, extraSkip = [],
}) {
  const { message } = App.useApp();
  const [fields, setFields] = useState([]);
  const [fkOpts, setFkOpts] = useState({});
  const [schemaErr, setSchemaErr] = useState(false);
  const [scanMode, setScanMode] = useState(false);
  const [scanStep, setScanStep] = useState(0);

  const skip = useMemo(() => {
    const s = new Set(BASE_SKIP);
    if (lineFk) s.add(lineFk);
    extraSkip.forEach((k) => s.add(k));
    return s;
  }, [lineFk, extraSkip]);

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const { data } = await getSchema(lineTable);
        if (!alive) return;
        const fs = (data?.fields || []).filter((f) => !skip.has(f.name) && !f.primary_key);
        setFields(fs);
        setSchemaErr(false);
        const opts = {};
        for (const f of fs.filter((x) => x.fk?.table)) {
          opts[f.name] = await loadFkOptions(f.fk.table, f.name);
        }
        if (alive) setFkOpts(opts);
      } catch {
        if (alive) { setFields([]); setSchemaErr(true); }
      }
    })();
    return () => { alive = false; };
  }, [lineTable, skip]);

  // Excel 粘贴整块建行：剪贴板 TSV 按可见录入列顺序映射多行
  const pasteRows = useCallback(async () => {
    let text = '';
    try { text = await navigator.clipboard.readText(); } catch { /* ignore */ }
    if (!text.trim()) { message.warning('剪贴板为空，请先在 Excel 复制要导入的区块'); return; }
    const colNames = fields.map((f) => f.name);
    const lines = text.replace(/\r/g, '').split('\n').filter((l) => l.length);
    const newRows = lines.map((line, li) => {
      const cells = line.split('\t');
      const row = { id: `new_${Date.now()}_${li}` };
      cells.forEach((c, ci) => { if (colNames[ci] != null) row[colNames[ci]] = c.trim(); });
      return row;
    });
    onChange([...value, ...newRows]);
    message.success(`已粘贴建 ${newRows.length} 行（按列顺序映射，请核对 FK/数字列）`);
  }, [fields, value, onChange, message]);

  // 扫码模式下，子表受控列改值时推进顺序锁
  const advanceScan = useCallback((changedRow, prevRow) => {
    if (!scanMode || !scanSequence) return;
    let lastStep = -1;
    scanSequence.forEach((f, i) => {
      if (changedRow?.[f] !== prevRow?.[f] && changedRow?.[f] != null && changedRow?.[f] !== '') {
        lastStep = Math.max(lastStep, i);
      }
    });
    if (lastStep >= 0) setScanStep((lastStep + 1) % scanSequence.length);
  }, [scanMode, scanSequence]);

  // schema → 网格列（FK→select、枚举→select、数字→digit、日期→date、其余 text）
  const columns = useMemo(() => fields.map((f) => {
    const required = !f.nullable && !f.has_default;
    const base = {
      title: f.label || f.name,
      dataIndex: f.name,
      width: COL_WIDTH[f.name] || 130,
      formItemProps: required ? { rules: [{ required: true, message: '必填' }] } : undefined,
    };
    if (f.fk?.table) {
      return {
        ...base, valueType: 'select',
        fieldProps: { options: fkOpts[f.name] || [], showSearch: true, optionFilterProp: 'label' },
        render: (_, row) => {
          const opt = (fkOpts[f.name] || []).find((o) => o.value === row[f.name]);
          return opt ? opt.label
            : (row[f.name] != null ? `#${row[f.name]}` : <span style={{ color: '#bfbbb5' }}>—</span>);
        },
      };
    }
    if (ENUM_OPTIONS[f.name]) {
      return { ...base, valueType: 'select', fieldProps: { options: ENUM_OPTIONS[f.name] } };
    }
    if (NUMERIC_TYPES.has(f.type)) {
      return { ...base, valueType: 'digit', fieldProps: { precision: f.type === 'integer' ? 0 : 2 } };
    }
    if (f.type === 'date' || f.type === 'datetime') {
      return { ...base, valueType: f.type === 'datetime' ? 'dateTime' : 'date' };
    }
    return base;
  }), [fields, fkOpts]);

  const nextScanField = scanMode && scanSequence
    ? (fields.find((f) => f.name === scanSequence[scanStep])?.label || scanSequence[scanStep])
    : null;

  if (schemaErr) {
    return (
      <div style={{ color: '#bfbbb5', fontSize: 13, padding: '8px 0' }}>
        子表 <code>{lineTable}</code> 结构待后端开通（schema 未就绪）。
      </div>
    );
  }

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8, flexWrap: 'wrap' }}>
        {scanSequence && (
          <Button
            size="small" type={scanMode ? 'primary' : 'default'} icon={<ScanOutlined />}
            onClick={() => { setScanMode((s) => !s); setScanStep(0); }}
          >
            {scanMode ? '扫码模式·开' : '扫码枪录入'}
          </Button>
        )}
        <Button size="small" icon={<SnippetsOutlined />} onClick={pasteRows}>Excel 粘贴建行</Button>
        <Tooltip title="原厂报价单/list 拍照 OCR 回填（待对接，回填仍需人工复核）">
          <Button size="small" icon={<CameraOutlined />} disabled>OCR 兜底</Button>
        </Tooltip>
        {scanMode && scanSequence && (
          <Tag color="processing" style={{ marginInlineStart: 4 }}>
            顺序锁 · 下一格「{nextScanField}」
          </Tag>
        )}
        <span style={{ flex: 1 }} />
        <span style={{ color: '#777169', fontSize: 12 }}>{value.length} 行</span>
      </div>

      <BizEditableTable
        value={value}
        onChange={onChange}
        rowKey="id"
        columns={columns}
        scroll={{ x: 'max-content', y: 340 }}
        recordCreatorProps={{ record: () => ({ id: `new_${Date.now()}` }) }}
        editable={{
          type: 'multiple',
          editableKeys: value.map((r) => r.id),
          onValuesChange: (record, recordList) => {
            const prev = value.find((r) => r.id === record.id);
            onChange(recordList);
            advanceScan(record, prev);
          },
        }}
      />
    </div>
  );
}
