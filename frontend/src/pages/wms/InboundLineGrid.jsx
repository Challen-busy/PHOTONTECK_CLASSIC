/**
 * InboundLineGrid —— 進庫詳細資料网格录入（PRD 03a-1 子表 + 03a-2 录单增强 14 律）
 *
 * 列由 goods_receipt_line 的 /api/schema 驱动（后端 ➕ 列自动出现），叠加录单效率增强：
 *   ① 扫码枪入格：顺序锁 型号→SN→数量→日期，扫一格聚焦下一格（PRD E6）
 *   ② 生产日期"向下复制"：一格输入向下灌相同值（访谈 02:220/274）
 *   ③ 统一包装多 PO 一键拆行：复制行、改 PO/数量、REMARK 红字"統一包裝"（PRD 场景5）
 *   ④ Excel 粘贴整块建行：粘贴 TSV → 按列顺序建多行（访谈 02:646）
 *   ⑤ OCR 兜底：可见占位按钮（14 律留口子；回填仍走人工，引擎无 OCR）
 *
 * 乐观 UI：改即写本地 value，由父组件提交时落 /api/transition；失败父组件就地标红、不静默。
 * FK 列（material_id/supplier_id）→ cell 选择器（loadFkOptions）。数字列右对齐（BizEditableTable 兜底）。
 *
 * ⚠️ 不写死成本列、不绕底座：本组件只产出子表行 value，写入由父页 sub_updates 走引擎唯一路径。
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { App, Button, Space, Tooltip, Tag } from 'antd';
import {
  ScanOutlined, CopyOutlined, BlockOutlined, SnippetsOutlined, CameraOutlined,
} from '@ant-design/icons';
import { BizEditableTable } from '../../components/biz';
import { getSchema } from '../../api';
import { loadFkOptions } from '../master/fkOptions';

// 扫码顺序锁：固定 型号→SN→数量→日期（访谈 01:388）
const SCAN_SEQUENCE = ['material_id', 'serial_lot_number', 'actual_quantity', 'production_date'];

// 子表不进网格的系统/自动列
const GRID_SKIP = new Set([
  'id', 'goods_receipt_id', 'created_at', 'updated_at', 'created_by_id', 'updated_by_id',
  'company_id', 'line_number', 'expected_quantity',
]);

// 列宽与展示提示（按字段名）
const COL_WIDTH = {
  inbound_number: 150, source_doc_number: 130, material_id: 150, serial_lot_number: 150,
  supplier_id: 130, goods_nature: 110, actual_quantity: 100, uom: 90,
  production_date: 130, date_code: 110, location_code: 110, remark: 180,
};

const NUMERIC_TYPES = new Set(['number', 'integer']);

export default function InboundLineGrid({ value = [], onChange }) {
  const { message } = App.useApp();
  const [fields, setFields] = useState([]);
  const [fkOpts, setFkOpts] = useState({});      // {字段: [{label,value}]}
  const [scanMode, setScanMode] = useState(false);
  const [scanStep, setScanStep] = useState(0);   // 扫码顺序锁当前步（型号→SN→数量→日期）

  // 拉子表 schema + FK 候选
  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const { data } = await getSchema('goods_receipt_line');
        if (!alive) return;
        const fs = (data?.fields || []).filter((f) => !GRID_SKIP.has(f.name) && !f.primary_key);
        setFields(fs);
        const opts = {};
        for (const f of fs.filter((x) => x.fk?.table)) {
          opts[f.name] = await loadFkOptions(f.fk.table, f.name);
        }
        if (alive) setFkOpts(opts);
      } catch {
        if (alive) setFields([]);
      }
    })();
    return () => { alive = false; };
  }, []);

  const rowKeyOf = (r) => r.id;

  // 向下复制某列：把当前行该列值灌到其后所有行（生产日期最常用）
  const copyDown = useCallback((field, fromRow) => {
    const rows = value.slice();
    const idx = rows.findIndex((r) => rowKeyOf(r) === rowKeyOf(fromRow));
    if (idx < 0) return;
    const v = rows[idx][field];
    for (let i = idx + 1; i < rows.length; i++) rows[i] = { ...rows[i], [field]: v };
    onChange(rows);
    message.success(`已向下复制「${field}」到 ${rows.length - idx - 1} 行`);
  }, [value, onChange, message]);

  // 统一包装拆行：复制选中行为新行（型号/SN/日期相同），清空 PO/数量待改，REMARK 标红字
  const splitUnifiedPackage = useCallback((fromRow) => {
    const rows = value.slice();
    const idx = rows.findIndex((r) => rowKeyOf(r) === rowKeyOf(fromRow));
    if (idx < 0) return;
    const src = rows[idx];
    const dup = {
      ...src,
      id: `new_${Date.now()}`,
      source_doc_number: '',           // 待改 PO#
      actual_quantity: 0,              // 待改数量
      inbound_number: '',              // 新入仓编号（提交时由后端编号命令生成）
      remark: '統一包裝',               // 红字标记（renderRemark 渲染红色）
    };
    rows.splice(idx + 1, 0, dup);
    onChange(rows);
    message.info('已拆出统一包装行：请改 PO# 与数量；REMARK 已标「統一包裝」');
  }, [value, onChange, message]);

  // Excel 粘贴整块建行：把剪贴板 TSV 按可见录入列顺序建多行
  const pasteRows = useCallback(async () => {
    let text = '';
    try { text = await navigator.clipboard.readText(); } catch { /* ignore */ }
    if (!text.trim()) { message.warning('剪贴板为空，请先在 Excel 复制要导入的区块'); return; }
    // 按子表列顺序映射粘贴块（第 1 列→第 1 个字段，依此类推；FK/数字列粘文本后需人工核对）
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

  // 扫码模式下，子表任一受控列改值时推进顺序锁（型号→SN→数量→日期）
  const advanceScan = useCallback((changedRow, prevRow) => {
    if (!scanMode) return;
    // 找出本次变化的扫码序列字段，取序列里最靠后的那个，下一步=其后一位
    let lastStep = -1;
    SCAN_SEQUENCE.forEach((f, i) => {
      if (changedRow?.[f] !== prevRow?.[f] && changedRow?.[f] != null && changedRow?.[f] !== '') {
        lastStep = Math.max(lastStep, i);
      }
    });
    if (lastStep >= 0) setScanStep((lastStep + 1) % SCAN_SEQUENCE.length);
  }, [scanMode]);

  // REMARK 红字（统一包装提示）
  const renderRemark = (v) => {
    const isUnified = typeof v === 'string' && v.includes('統一包裝');
    return (
      <span style={{ color: isUnified ? '#b42318' : '#000', fontWeight: isUnified ? 500 : 400 }}>
        {v || <span style={{ color: '#bfbbb5' }}>—</span>}
      </span>
    );
  };

  // schema → 网格列（FK→select、数字→digit、日期→date、其余 text）+ 行操作列
  const columns = useMemo(() => {
    const cols = fields.map((f) => {
      const base = {
        title: f.label || f.name,
        dataIndex: f.name,
        width: COL_WIDTH[f.name] || 130,
        formItemProps: !f.nullable && f.name !== 'production_date'
          ? { rules: [{ required: true, message: '必填' }] }
          : undefined,
      };
      if (f.name === 'remark') {
        return { ...base, render: (_, row) => renderRemark(row.remark) };
      }
      if (f.fk?.table) {
        return {
          ...base, valueType: 'select',
          fieldProps: { options: fkOpts[f.name] || [], showSearch: true, optionFilterProp: 'label' },
          render: (_, row) => {
            const opt = (fkOpts[f.name] || []).find((o) => o.value === row[f.name]);
            return opt ? opt.label : (row[f.name] != null ? `#${row[f.name]}` : <span style={{ color: '#bfbbb5' }}>—</span>);
          },
        };
      }
      if (NUMERIC_TYPES.has(f.type)) {
        return { ...base, valueType: 'digit', fieldProps: { precision: f.type === 'integer' ? 0 : 2 } };
      }
      if (f.type === 'date' || f.type === 'datetime') {
        const col = { ...base, valueType: f.type === 'datetime' ? 'dateTime' : 'date' };
        // 生产日期列：向下复制快捷
        if (f.name === 'production_date') {
          col.render = (_, row) => (
            <Space size={4}>
              <span>{row.production_date || <span style={{ color: '#bfbbb5' }}>—</span>}</span>
              {row.production_date && (
                <Tooltip title="向下复制此生产日期">
                  <Button type="link" size="small" icon={<CopyOutlined />}
                    onClick={() => copyDown('production_date', row)} />
                </Tooltip>
              )}
            </Space>
          );
        }
        return col;
      }
      return base;
    });
    // 行操作列：统一包装拆行
    cols.push({
      title: '行操作', dataIndex: '_rowact', width: 92, fixed: 'right', editable: false,
      render: (_, row) => (
        <Tooltip title="统一包装拆行（复制本行→改 PO/数量）">
          <Button type="link" size="small" icon={<BlockOutlined />}
            onClick={() => splitUnifiedPackage(row)}>拆行</Button>
        </Tooltip>
      ),
    });
    return cols;
  }, [fields, fkOpts, copyDown, splitUnifiedPackage]);

  // 扫码顺序锁提示当前应扫列（读 state，不在 render 读 ref）
  const nextScanField = scanMode
    ? (fields.find((f) => f.name === SCAN_SEQUENCE[scanStep])?.label || SCAN_SEQUENCE[scanStep])
    : null;

  return (
    <div>
      {/* 录单增强工具条（14 律录单效率） */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8, flexWrap: 'wrap' }}>
        <Button
          size="small" type={scanMode ? 'primary' : 'default'} icon={<ScanOutlined />}
          onClick={() => { setScanMode((s) => !s); setScanStep(0); }}
        >
          {scanMode ? '扫码模式·开' : '扫码枪录入'}
        </Button>
        <Button size="small" icon={<SnippetsOutlined />} onClick={pasteRows}>Excel 粘贴建行</Button>
        <Tooltip title="包装无条码时拍照 OCR 回填（待对接，回填仍需人工复核 0/O、I/E）">
          <Button size="small" icon={<CameraOutlined />} disabled>OCR 兜底</Button>
        </Tooltip>
        {scanMode && (
          <Tag color="processing" style={{ marginInlineStart: 4 }}>
            顺序锁：型号→SN→数量→日期 · 下一格「{nextScanField}」
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
        scroll={{ x: 'max-content', y: 360 }}
        recordCreatorProps={{ record: () => ({ id: `new_${Date.now()}`, actual_quantity: 0 }) }}
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
