/**
 * 通用单据编辑器 — 四区结构
 *
 *   展示区: Hero + 节点说明 + 详细字段(只读) + 子表summary + 关联主对象 + 反向关联
 *   动作区: 每个可执行动作一个 tab；切换只影响前端显示；
 *            选中某动作 → 显示该 next 的 editable_fields 表单 + 子表编辑 + 硬规则提示 + 提交按钮
 *            点提交才真正调后端 /transition
 */

import { useEffect, useMemo, useState, forwardRef, useImperativeHandle, useRef } from 'react';
import {
  Card, Input, InputNumber, DatePicker, Select, Table, Button, Space, Spin,
  message, Empty, Timeline, Collapse, Badge,
} from 'antd';
import {
  SaveOutlined, PlusOutlined, DeleteOutlined, EditOutlined, LockOutlined,
  ArrowRightOutlined, LinkOutlined, FileTextOutlined, HistoryOutlined, SettingOutlined,
  InfoCircleOutlined,
} from '@ant-design/icons';
import dayjs from 'dayjs';
import api from '../api';
import { query, previewTransition, commitTransition, getHistory } from '../api';
import { useAuth } from '../auth';
import ChangeCard from './ChangeCard';

const CARD_SHADOW =
  'rgba(0,0,0,0.06) 0px 0px 0px 1px, rgba(0,0,0,0.04) 0px 1px 2px, rgba(0,0,0,0.04) 0px 2px 4px';

function Pill({ bg, color, children, style }) {
  return (
    <span style={{
      display: 'inline-block', padding: '2px 10px', borderRadius: 4,
      background: bg, color, fontSize: 12, fontWeight: 500,
      letterSpacing: '0.02em', ...style,
    }}>{children}</span>
  );
}

// ===== 枚举值中文 =====
const VALUE_LABELS = {
  voucher_type: { GENERAL: "记账凭证", CASH: "收款凭证", PAYMENT: "付款凭证", TRANSFER: "转账凭证" },
  account_type: { ASSET: "资产", LIABILITY: "负债", EQUITY: "所有者权益", REVENUE: "收入", EXPENSE: "费用", COGS: "营业成本", OTHER: "其他" },
  balance_direction: { DEBIT: "借", CREDIT: "贷" },
  code_type: { LONG_TERM: "长期代码", TEMPORARY: "临时代码" },
  warehouse_type: { MAIN: "主仓", BONDED: "保税区", BRANCH: "分仓" },
  tax_type: { NONE: "无税", VAT: "增值税" },
  product_line: { QUANTUM: "量子", OPTICAL_COMM: "光通信", SENSING: "传感", INDUSTRIAL: "工业", OTHER: "其他" },
  order_type: { STANDARD: "标准", TRADE: "贸易(背靠背)" },
  role: { BOSS: "老板", OPERATIONS: "运营", FINANCE: "财务", SALES_ENGINEER: "销售工程师", SALES_ASSISTANT: "销售助理", PRODUCT_MANAGER: "产品经理", PRODUCT_ASSISTANT: "产品助理", LOGISTICS: "物流", ADMIN: "管理员", FAE: "现场应用工程师" },
  shipping_method: { FOB: "FOB离岸", CIF: "CIF到岸", DAP: "送货到厂", EXW: "工厂交货" },
  default_shipping_method: { FOB: "FOB离岸", CIF: "CIF到岸", DAP: "送货到厂", EXW: "工厂交货" },
  cost_method: { WEIGHTED_AVG: "全月加权平均", MOVING_AVG: "移动加权平均", FIFO: "先进先出" },
  quality_status: { OK: "合格", DAMAGED: "损坏", SHORT: "短缺", EXCESS: "多发" },
  transaction_type: { PURCHASE_IN: "采购入库", SALES_OUT: "销售出库", STOCK_IN: "其他入库", STOCK_OUT: "其他出库", TRANSFER: "调拨", ADJUST_PLUS: "盘盈", ADJUST_MINUS: "盘亏" },
};

function formatValue(fieldName, value) {
  if (value == null || value === '') return '';
  const map = VALUE_LABELS[fieldName];
  if (map && map[value]) return map[value];
  if (typeof value === 'boolean') return value ? '是' : '否';
  return String(value);
}

const TABLE_MAP = {
  SALES_ORDER: 'sales_order', PURCHASE_ORDER: 'purchase_order',
  SHIPMENT: 'shipment_request', VOUCHER: 'voucher', VOUCHER_ADJUSTMENT: 'voucher',
  GOODS_RECEIPT: 'goods_receipt', PROJECT: 'project',
  FRAMEWORK_CONTRACT: 'framework_contract',
  ACCOUNTS_RECEIVABLE: 'accounts_receivable', ACCOUNTS_PAYABLE: 'accounts_payable',
  INVENTORY: 'inventory', INVENTORY_VIRTUAL: 'inventory', INVENTORY_COUNT: 'inventory',
  INVENTORY_COSTING: 'inventory_transaction',
};

// ===== FK 行的"标识符"提取 =====
const ID_FIELDS = ['name', 'full_name', 'short_name', 'code', 'sku', 'order_number', 'voucher_number',
  'shipment_number', 'receipt_number', 'invoice_number', 'contract_number', 'username', 'batch_number'];
function rowLabel(row) {
  if (!row) return '';
  for (const f of ID_FIELDS) if (row[f]) return row[f];
  return `#${row.id}`;
}

// ===== 节点说明清洗 =====
function cleanDescription(text) {
  if (!text) return '';
  return text.split('\n')
    .filter(line => !line.trim().startsWith('# '))
    .map(line => line.replace(/^\s*-\s*【[^】]*】/, '• '))
    .join('\n').trim();
}

// ===== 字段分类 =====
const HIDDEN_FIELDS = new Set(['id', 'created_by_id', 'updated_by_id', 'created_at', 'updated_at']);
const SYSTEM_FIELDS = new Set(['company_id', 'workflow_id', 'workflow_version', 'is_auto_generated', 'source_doc_id', 'source_doc_type', 'posted_by_id', 'posted_at', 'closed_by_id', 'closed_at']);
const IDENTIFIER_RE = /_number$|^code$|^sku$|^batch_number$|^tracking_number$|^invoice_number$/;
const HERO_FK_FIELDS = new Set(['customer_id', 'supplier_id']);
const HERO_AMOUNT_FIELDS = new Set(['total_amount', 'amount']);

function classifyField(name, isAdmin) {
  if (HIDDEN_FIELDS.has(name)) return 'hidden';
  if (SYSTEM_FIELDS.has(name)) return isAdmin ? 'system' : 'hidden';
  if (['status', 'stage'].includes(name)) return 'hero_status';
  if (IDENTIFIER_RE.test(name)) return 'hero_id';
  if (HERO_FK_FIELDS.has(name)) return 'hero_party';
  if (HERO_AMOUNT_FIELDS.has(name)) return 'hero_amount';
  return 'detail';
}

// ===== 字段输入控件 =====
function FieldInput({ field, value, onChange, disabled, fkOptions, stateLabels }) {
  if (!field) return null;
  const { name, type, fk } = field;
  const readOnlyStyle = {
    padding: '6px 12px',
    background: 'rgba(245, 242, 239, 0.4)',
    borderRadius: 8,
    border: '1px solid rgba(0, 0, 0, 0.05)',
    fontSize: 13,
    minHeight: 32,
    letterSpacing: '0.01em',
    color: '#000',
  };

  if (disabled) {
    if (value == null || value === '') {
      return <div style={{ ...readOnlyStyle, color: '#bfbbb5' }}>—</div>;
    }
    if (name === 'status' && stateLabels && stateLabels[value]) {
      return (
        <div style={{
          ...readOnlyStyle,
          background: '#eaf1fb', borderColor: '#a8c4e7',
          color: '#1f5aa8', fontWeight: 500,
        }}>
          {stateLabels[value]}
        </div>
      );
    }
    if (fk) {
      const opt = (fkOptions || []).find(o => o.id === value);
      return <div style={readOnlyStyle}>{opt ? rowLabel(opt) : `#${value}`}</div>;
    }
    return <div style={{ ...readOnlyStyle, whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>{formatValue(name, value)}</div>;
  }

  if (fk) {
    return (
      <Select
        value={value} onChange={onChange} disabled={disabled}
        style={{ width: '100%' }} showSearch allowClear optionFilterProp="label"
        placeholder={`选择${field.label || fk.table}`}
        options={(fkOptions || []).map(o => ({ value: o.id, label: rowLabel(o) }))}
      />
    );
  }
  if (type === 'boolean') return <Select value={value} onChange={onChange} disabled={disabled} style={{ width: '100%' }} options={[{ value: true, label: '是' }, { value: false, label: '否' }]} />;
  if (type === 'date' || type === 'datetime') return <DatePicker value={value ? dayjs(value) : undefined} onChange={v => onChange(v?.format(type === 'datetime' ? 'YYYY-MM-DDTHH:mm:ss' : 'YYYY-MM-DD'))} disabled={disabled} style={{ width: '100%' }} />;
  if (type === 'number' || type === 'integer') return <InputNumber value={value} onChange={onChange} disabled={disabled} style={{ width: '100%' }} />;
  if (type === 'json') return <Input.TextArea value={typeof value === 'object' ? JSON.stringify(value, null, 2) : value} onChange={e => { try { onChange(JSON.parse(e.target.value)); } catch { onChange(e.target.value); } }} disabled={disabled} rows={3} />;
  if (type === 'text') return <Input.TextArea value={value} onChange={e => onChange(e.target.value)} disabled={disabled} rows={2} />;
  return <Input value={value} onChange={e => onChange(e.target.value)} disabled={disabled} />;
}

// ===== 子表编辑器 =====
const SubTableEditor = forwardRef(function SubTableEditor({ subInfo, parentId, readOnly = false }, ref) {
  const [schema, setSchema] = useState(null);
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [fkOptions, setFkOptions] = useState({});

  useEffect(() => {
    (async () => {
      setLoading(true);
      const [s, r] = await Promise.all([
        api.get(`/schema/${subInfo.table}`),
        query(subInfo.table, { filters: { [subInfo.parent_fk]: parentId }, limit: 100 }),
      ]);
      setSchema(s.data);
      setRows(r.data.data || []);
      const fkFields = s.data.fields.filter(f => f.fk && f.name !== subInfo.parent_fk);
      const opts = {};
      for (const f of fkFields) {
        try {
          const { data: fkData } = await query(f.fk.table, { limit: 200 });
          opts[f.name] = fkData.data || [];
        } catch { opts[f.name] = []; }
      }
      setFkOptions(opts);
      setLoading(false);
    })();
  }, [subInfo.table, parentId]);

  useImperativeHandle(ref, () => ({
    getPendingUpdates() {
      if (!schema) return [];
      const skip = new Set(['id', subInfo.parent_fk, 'created_at', 'updated_at', 'created_by_id', 'updated_by_id']);
      const editableCols = schema.fields.filter(f => !skip.has(f.name));
      return rows.filter(r => r._new || r._modified || r._delete).map(r => {
        const fields = {};
        editableCols.forEach(c => { if (r[c.name] !== undefined) fields[c.name] = r[c.name]; });
        fields[subInfo.parent_fk] = parentId;
        return { table: subInfo.table, id: r._new ? undefined : r.id, _delete: r._delete, fields, parent_fk: subInfo.parent_fk };
      });
    },
  }), [rows, schema, subInfo, parentId]);

  if (loading) return <Spin />;
  if (!schema) return null;

  const skipFields = new Set(['id', subInfo.parent_fk, 'created_at', 'updated_at', 'created_by_id', 'updated_by_id']);
  const cols = schema.fields.filter(f => !skipFields.has(f.name));

  const autoFields = new Set(['line_number']);
  const hasAutoTotal = cols.some(c => c.name === 'quantity') && cols.some(c => c.name === 'unit_price');
  if (hasAutoTotal) autoFields.add('total_price');

  const numericFields = cols.filter(c => c.type === 'number' || c.type === 'integer');
  const notSummable = n => n.includes('number') || n.startsWith('unit_') || n.endsWith('_id');
  const summableCols = numericFields.filter(f => !notSummable(f.name));
  const totals = {};
  const visibleForSum = rows.filter(r => !r._delete);
  summableCols.forEach(f => { totals[f.name] = visibleForSum.reduce((sum, r) => sum + (Number(r[f.name]) || 0), 0); });

  const addRow = () => {
    const newRow = { _new: true, _tempId: Date.now(), [subInfo.parent_fk]: parentId };
    const visible = rows.filter(r => !r._delete);
    cols.forEach(c => {
      if (c.name === 'line_number') {
        newRow[c.name] = visible.reduce((max, r) => Math.max(max, Number(r.line_number) || 0), 0) + 1;
      } else {
        newRow[c.name] = c.type === 'number' || c.type === 'integer' ? 0 : '';
      }
    });
    setRows([...rows, newRow]);
  };
  const deleteRow = (row) => {
    if (row._new) setRows(rows.filter(r => r._tempId !== row._tempId));
    else setRows(rows.map(r => r.id === row.id ? { ...r, _delete: true } : r));
  };
  const editCell = (row, field, value) => {
    const updated = { [field]: value };
    if (hasAutoTotal && (field === 'quantity' || field === 'unit_price')) {
      const qty = field === 'quantity' ? Number(value) || 0 : Number(row.quantity) || 0;
      const price = field === 'unit_price' ? Number(value) || 0 : Number(row.unit_price) || 0;
      updated.total_price = Math.round(qty * price * 100) / 100;
    }
    if (row._new) setRows(rows.map(r => r._tempId === row._tempId ? { ...r, ...updated } : r));
    else setRows(rows.map(r => r.id === row.id ? { ...r, ...updated, _modified: true } : r));
  };
  const visibleRows = rows.filter(r => !r._delete);
  const tableColumns = [
    ...cols.map(col => ({
      title: col.label || col.name, dataIndex: col.name, key: col.name,
      width: col.type === 'number' ? 110 : 140,
      render: (v, row) => readOnly
        ? (col.fk
          ? (() => { const opt = (fkOptions[col.name] || []).find(o => o.id === v); return opt ? rowLabel(opt) : (v != null ? `#${v}` : ''); })()
          : <span>{formatValue(col.name, v)}</span>)
        : autoFields.has(col.name)
          ? <span style={{ color: '#4e4e4e', padding: '0 8px' }}>{formatValue(col.name, row[col.name])}</span>
          : <FieldInput field={col} value={row[col.name]} onChange={val => editCell(row, col.name, val)} fkOptions={fkOptions[col.name]} disabled={false} />,
    })),
    ...(readOnly ? [] : [{
      title: '', key: '_a', width: 50, fixed: 'right',
      render: (_, row) => <Button size="small" danger icon={<DeleteOutlined />} onClick={() => deleteRow(row)} />,
    }]),
  ];

  const subTitle = subInfo.table_label || subInfo.table;
  return (
    <Card
      size="small"
      title={(
        <span style={{ fontSize: 13, fontWeight: 500, letterSpacing: '0.01em' }}>
          {subTitle}
          <span style={{ color: '#777169', marginLeft: 6, fontWeight: 400 }}>
            · {visibleRows.length} 行
          </span>
        </span>
      )}
      style={{ marginBottom: 10, borderRadius: 12, boxShadow: CARD_SHADOW, border: 'none' }}
      extra={!readOnly && (
        <Button size="small" icon={<PlusOutlined />} onClick={addRow}>添加</Button>
      )}
    >
      <Table
        dataSource={visibleRows}
        columns={tableColumns}
        rowKey={r => r.id || r._tempId}
        size="small"
        pagination={false}
        scroll={{ x: 'max-content' }}
        summary={() => summableCols.length > 0 ? (
          <Table.Summary.Row style={{ background: '#f5f2ef' }}>
            {cols.map((c, i) => (
              <Table.Summary.Cell key={c.name} index={i}>
                {i === 0 ? <strong style={{ fontWeight: 500 }}>合计</strong>
                : totals[c.name] != null ? <strong style={{ fontWeight: 500 }}>{totals[c.name].toLocaleString()}</strong>
                : null}
              </Table.Summary.Cell>
            ))}
            {!readOnly && <Table.Summary.Cell index={cols.length} />}
          </Table.Summary.Row>
        ) : null}
      />
    </Card>
  );
});

// ===== FK 信息卡片 =====
function ForwardFkCard({ field, target_table_label, row, labels = {}, fieldLabel }) {
  const keyFields = [];
  for (const f of ID_FIELDS) if (row[f]) { keyFields.push({ k: f, v: row[f] }); break; }
  const extras = [];
  for (const f of ['total_amount', 'amount', 'credit_limit', 'used_amount', 'status', 'role', 'currency', 'country', 'contact_person']) {
    if (row[f] != null && row[f] !== '') extras.push({ k: f, v: formatValue(f, row[f]) });
  }
  return (
    <Card
      size="small"
      style={{
        borderRadius: 12,
        background: 'rgba(245, 242, 239, 0.5)',
        border: '1px solid rgba(0, 0, 0, 0.05)',
        borderLeft: '3px solid #1f5aa8',
      }}
    >
      <div style={{
        fontSize: 11, color: '#777169', marginBottom: 4,
        letterSpacing: '0.02em',
      }}>
        {fieldLabel || field}
      </div>
      <div style={{
        fontWeight: 500, fontSize: 14, color: '#000',
        marginBottom: 6, letterSpacing: '0.01em',
      }}>
        {keyFields[0]?.v || `#${row.id}`}
        {target_table_label && (
          <span style={{ fontSize: 10, color: '#bfbbb5', marginLeft: 6, fontWeight: 400 }}>
            ({target_table_label})
          </span>
        )}
      </div>
      <div style={{
        fontSize: 11, color: '#4e4e4e',
        display: 'flex', flexWrap: 'wrap', gap: 10,
        letterSpacing: '0.01em',
      }}>
        {extras.slice(0, 4).map(({ k, v }) => (
          <span key={k}>
            <span style={{ color: '#bfbbb5' }}>{labels[k] || k}:</span>{' '}
            <span style={{ color: '#000' }}>{v}</span>
          </span>
        ))}
      </div>
    </Card>
  );
}

// ===== 主组件 =====
export default function DocEditor({ docType, docId, currentState, actions = [], onRefresh, nodeDescription = '' }) {
  const { user } = useAuth();
  const isAdminRole = user && ['ADMIN', 'BOSS', 'OPERATIONS', 'FINANCE'].includes(user.role);

  const [schema, setSchema] = useState(null);
  const [doc, setDoc] = useState(null);
  const [loading, setLoading] = useState(true);
  const [editingFields, setEditingFields] = useState({});
  const [fkOptions, setFkOptions] = useState({});
  const [history, setHistory] = useState([]);
  const [related, setRelated] = useState({ forward: [], reverse: [] });
  const [comment, setComment] = useState('');
  const [pendingCard, setPendingCard] = useState(null);
  const [busy, setBusy] = useState(false);
  const [stateLabels, setStateLabels] = useState({});
  const [selectedActionIdx, setSelectedActionIdx] = useState(0);
  const [subRefreshKey, setSubRefreshKey] = useState(0);
  const subTableRefs = useRef({});

  const selectedAction = actions[selectedActionIdx] || null;
  const selectedEditableSet = useMemo(() => new Set(selectedAction?.editable_fields || []), [selectedAction]);

  const tableName = TABLE_MAP[docType];

  const load = async () => {
    if (!tableName || !docId) return;
    setLoading(true);
    const [s, d, h, rel] = await Promise.all([
      api.get(`/schema/${tableName}`),
      query(tableName, { filters: { id: docId }, limit: 1 }),
      getHistory(docType, docId),
      api.get(`/related/${tableName}/${docId}`).catch(() => ({ data: { forward: [], reverse: [] } })),
    ]);
    setSchema(s.data);
    setDoc(d.data.data?.[0] || null);
    setHistory(h.data);
    setRelated(rel.data || { forward: [], reverse: [] });

    try {
      const { data: wfs } = await api.get('/workflows');
      const wf = wfs.find(w => w.doc_type === docType);
      if (wf) {
        const labels = {};
        (wf.states || []).forEach(st => { labels[st.code] = st.name; });
        setStateLabels(labels);
      }
    } catch {}

    const fkFields = s.data.fields.filter(f => f.fk);
    const opts = {};
    for (const f of fkFields) {
      try {
        const { data: fkData } = await query(f.fk.table, { limit: 200 });
        opts[f.name] = fkData.data || [];
      } catch { opts[f.name] = []; }
    }
    setFkOptions(opts);
    setLoading(false);
  };
  useEffect(() => { load(); }, [docType, docId, actions.length]);

  const saveFields = async () => {
    const allSubUpdates = [];
    Object.values(subTableRefs.current).forEach(r => {
      if (r?.getPendingUpdates) allSubUpdates.push(...r.getPendingUpdates());
    });
    if (Object.keys(editingFields).length === 0 && allSubUpdates.length === 0) {
      message.info('无变更'); return;
    }
    setBusy(true);
    try {
      const { data } = await api.post('/transition', {
        doc_type: docType, doc_id: docId,
        field_updates: editingFields,
        sub_updates: allSubUpdates,
      });
      if (data.success) {
        const n = Object.keys(data.changed_fields || {}).length;
        const s = (data.sub_changes || []).length;
        message.success(`已保存${n ? ` ${n}项字段` : ''}${s ? ` ${s}项子表` : ''}`);
        setEditingFields({});
        setSubRefreshKey(k => k + 1);
        load();
      } else if (data.rule_failures) {
        message.error('校验未通过');
        data.rule_failures.forEach(f => message.warning(f));
      } else message.error(data.error || '保存失败');
    } catch (e) { message.error('保存失败'); }
    setBusy(false);
  };

  const requestAction = async (action) => {
    setBusy(true);

    const allSubUpdates = [];
    Object.values(subTableRefs.current).forEach(r => {
      if (r?.getPendingUpdates) allSubUpdates.push(...r.getPendingUpdates());
    });
    if (allSubUpdates.length > 0) {
      try {
        const { data } = await api.post('/transition', {
          doc_type: docType, doc_id: docId,
          field_updates: {}, sub_updates: allSubUpdates,
        });
        if (!data.success) {
          message.error(data.error || '子表保存失败');
          setBusy(false);
          return;
        }
        setSubRefreshKey(k => k + 1);
      } catch {
        message.error('子表保存失败');
        setBusy(false);
        return;
      }
    }

    const allowed = new Set(action.editable_fields || []);
    const filtered = {};
    Object.entries(editingFields).forEach(([k, v]) => { if (allowed.has(k)) filtered[k] = v; });
    try {
      const { data: card } = await previewTransition({
        doc_type: docType, doc_id: docId,
        to_state: action.to_state, action_label: action.action_label,
        field_updates: filtered,
      });
      setPendingCard({ ...card, _comment: comment });
    } catch { message.error('检查失败'); }
    setBusy(false);
  };

  const approveCard = async (card) => {
    setBusy(true);
    try {
      const { data } = await commitTransition(card, comment);
      if (data.success) {
        message.success(`${card.action_label || card.transition_name}: ${data.from_state || ''} → ${data.to_state}`);
        setPendingCard(null); setEditingFields({}); setComment('');
        onRefresh?.(); load();
      } else if (data.rule_failures) {
        message.error('校验未通过');
        data.rule_failures.forEach(f => message.warning(f));
      } else message.error(data.error);
    } catch { message.error('执行失败'); }
    setBusy(false);
  };

  const grouped = useMemo(() => {
    if (!schema) return { hero_id: null, hero_party: null, hero_amount: null, detail: [], system: [], editable: [] };
    const g = { hero_id: null, hero_party: null, hero_amount: null, detail: [], system: [], editable: [] };
    schema.fields.forEach(f => {
      const cat = classifyField(f.name, isAdminRole);
      if (cat === 'hidden' || cat === 'hero_status') return;
      if (cat === 'hero_id' && !g.hero_id) {
        g.hero_id = f;
        if (selectedEditableSet.has(f.name)) g.editable.push(f);
      } else if (cat === 'hero_party' && !g.hero_party) {
        g.hero_party = f;
        if (selectedEditableSet.has(f.name)) g.editable.push(f);
      } else if (cat === 'hero_amount' && !g.hero_amount) {
        g.hero_amount = f;
        if (selectedEditableSet.has(f.name)) g.editable.push(f);
      } else if (selectedEditableSet.has(f.name)) {
        g.editable.push(f);
      } else if (cat === 'system') g.system.push(f);
      else g.detail.push(f);
    });
    return g;
  }, [schema, selectedEditableSet, isAdminRole]);

  if (loading) return <Spin size="large" style={{ display: 'block', margin: '40px auto' }} />;
  if (!schema || !doc) return <Empty description="加载失败" />;

  const idValue = grouped.hero_id ? doc[grouped.hero_id.name] : null;
  const partyValue = grouped.hero_party
    ? (fkOptions[grouped.hero_party.name] || []).find(o => o.id === doc[grouped.hero_party.name])
    : null;
  const amountValue = grouped.hero_amount ? doc[grouped.hero_amount.name] : null;
  const currency = doc.currency || '';
  const statusLabel = stateLabels[doc.status] || doc.status;
  const dirty = Object.keys(editingFields).length > 0;
  const hasOps = actions.length > 0;
  const subEditable = actions.some(a => (a.editable_fields || []).length > 0);
  const selectedEditableList = grouped.editable;
  const selectedEditableCount = selectedEditableList.length;
  const cleanedDesc = cleanDescription(nodeDescription);

  const renderField = (f, editable) => {
    const value = editingFields[f.name] !== undefined ? editingFields[f.name] : doc[f.name];
    return (
      <div key={f.name}>
        <div style={{
          fontSize: 12, color: editable ? '#000' : '#777169',
          marginBottom: 5, fontWeight: editable ? 500 : 400,
          letterSpacing: '0.02em',
          display: 'flex', alignItems: 'center', gap: 4,
        }}>
          <span>{f.label || f.name}</span>
          {editable
            ? <EditOutlined style={{ color: '#4e4e4e', fontSize: 10 }} />
            : <LockOutlined style={{ color: '#bfbbb5', fontSize: 10 }} />}
          {!f.nullable && editable && <span style={{ color: '#b42318' }}> *</span>}
        </div>
        <FieldInput
          field={f}
          value={value}
          onChange={v => editable ? setEditingFields({ ...editingFields, [f.name]: v }) : null}
          disabled={!editable}
          fkOptions={fkOptions[f.name]}
          stateLabels={stateLabels}
        />
      </div>
    );
  };

  // 节标题：左色条 + 小标签
  const SectionLabel = ({ color, children, icon }) => (
    <div style={{
      fontSize: 11, color, marginBottom: 8, paddingLeft: 10,
      borderLeft: `3px solid ${color}`,
      fontWeight: 500, letterSpacing: '0.06em', textTransform: 'uppercase',
      display: 'flex', alignItems: 'center', gap: 6,
    }}>
      {icon}
      {children}
    </div>
  );

  return (
    <div>
      {/* === Hero 卡片 === */}
      <Card
        style={{
          borderRadius: 16, marginBottom: 14,
          background: 'linear-gradient(135deg, #000 0%, #1a1a1a 100%)',
          color: '#fff', border: 'none',
          boxShadow: 'rgba(0,0,0,0.12) 0px 8px 24px',
        }}
        styles={{ body: { padding: '18px 22px' } }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 28, flexWrap: 'wrap' }}>
          {grouped.hero_id && (
            <div>
              <div style={{
                fontSize: 11, color: 'rgba(255,255,255,0.55)',
                letterSpacing: '0.04em', textTransform: 'uppercase', marginBottom: 2,
              }}>
                {grouped.hero_id.label}
              </div>
              <div style={{
                fontSize: 22, fontWeight: 400,
                fontFamily: 'ui-monospace, monospace',
                letterSpacing: '0.01em',
              }}>
                {idValue || `#${docId}`}
              </div>
            </div>
          )}
          {grouped.hero_party && (
            <div>
              <div style={{
                fontSize: 11, color: 'rgba(255,255,255,0.55)',
                letterSpacing: '0.04em', textTransform: 'uppercase', marginBottom: 2,
              }}>
                {grouped.hero_party.label}
              </div>
              <div style={{ fontSize: 16, fontWeight: 500, letterSpacing: '0.01em' }}>
                {partyValue ? rowLabel(partyValue) : '—'}
              </div>
            </div>
          )}
          {grouped.hero_amount && amountValue != null && (
            <div>
              <div style={{
                fontSize: 11, color: 'rgba(255,255,255,0.55)',
                letterSpacing: '0.04em', textTransform: 'uppercase', marginBottom: 2,
              }}>
                {grouped.hero_amount.label}
              </div>
              <div style={{
                fontSize: 22, fontWeight: 300, color: '#f5f2ef',
                letterSpacing: '-0.01em',
              }}>
                {currency} {Number(amountValue).toLocaleString()}
              </div>
            </div>
          )}
          <div style={{ flex: 1 }} />
          <div style={{ textAlign: 'right' }}>
            <div style={{
              fontSize: 11, color: 'rgba(255,255,255,0.55)',
              letterSpacing: '0.04em', textTransform: 'uppercase', marginBottom: 4,
            }}>
              当前节点
            </div>
            <span style={{
              display: 'inline-block',
              padding: '5px 14px',
              borderRadius: 9999,
              background: '#f5f2ef',
              color: '#000',
              fontSize: 13,
              fontWeight: 500,
              letterSpacing: '0.01em',
            }}>
              {statusLabel}
            </span>
          </div>
        </div>
      </Card>

      {/* === 节点说明 === */}
      {cleanedDesc && (
        <Card
          size="small"
          style={{
            borderRadius: 12, marginBottom: 12,
            background: 'rgba(245, 242, 239, 0.5)',
            border: '1px solid rgba(0, 0, 0, 0.05)',
            borderLeft: '3px solid #b8860b',
          }}
          styles={{ body: { padding: '10px 14px' } }}
        >
          <div style={{
            fontSize: 13, whiteSpace: 'pre-wrap', color: '#4e4e4e',
            letterSpacing: '0.01em', lineHeight: 1.55,
            display: 'flex', gap: 8, alignItems: 'flex-start',
          }}>
            <InfoCircleOutlined style={{ color: '#b8860b', marginTop: 3, flexShrink: 0 }} />
            <span>{cleanedDesc}</span>
          </div>
        </Card>
      )}

      {/* ============ 展示区 ============ */}
      <div style={{ marginBottom: 14 }}>
        <SectionLabel color="#777169" icon={<FileTextOutlined />}>展示区</SectionLabel>

        {/* 详细字段（只读）*/}
        {grouped.detail.length > 0 && (
          <Card
            size="small"
            title={<span style={{ fontSize: 13, fontWeight: 500 }}>详细信息</span>}
            style={{ borderRadius: 12, marginBottom: 10, boxShadow: CARD_SHADOW, border: 'none' }}
          >
            <div style={{
              display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 14,
            }}>
              {grouped.detail.map(f => renderField(f, false))}
            </div>
          </Card>
        )}

        {/* 关联主对象 */}
        {related.forward.length > 0 && (
          <Card
            size="small"
            title={(
              <span style={{ fontSize: 13, fontWeight: 500 }}>
                <LinkOutlined style={{ color: '#777169', marginRight: 6 }} />
                关联对象
              </span>
            )}
            style={{ borderRadius: 12, marginBottom: 10, boxShadow: CARD_SHADOW, border: 'none' }}
          >
            <div style={{
              display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: 10,
            }}>
              {related.forward.map((f, i) => {
                const fieldDef = schema.fields.find(x => x.name === f.field);
                return <ForwardFkCard key={i} {...f} fieldLabel={fieldDef?.label || f.field} />;
              })}
            </div>
          </Card>
        )}

        {/* 子表 - 无动作时只读展示 */}
        {!hasOps && schema.sub_tables.map(sub => (
          <SubTableEditor key={sub.table} subInfo={sub} parentId={docId} readOnly={true} />
        ))}

        {/* 反向关联 */}
        {related.reverse.length > 0 && (
          <Collapse
            style={{ marginBottom: 10, background: '#fff', boxShadow: CARD_SHADOW, borderRadius: 12, border: 'none' }}
            size="small"
            items={[{
              key: 'rev',
              label: (
                <span style={{ fontSize: 13, fontWeight: 500, letterSpacing: '0.01em' }}>
                  <Badge
                    count={related.reverse.reduce((s, r) => s + r.count, 0)}
                    style={{ backgroundColor: '#777169', marginRight: 8 }}
                  />
                  反向关联（其他表里指向这单的）
                </span>
              ),
              children: related.reverse.map((r, i) => (
                <Card
                  key={i} size="small"
                  title={(
                    <span style={{ fontSize: 12, fontWeight: 500 }}>
                      {r.table_label || r.table}
                      <span style={{ color: '#777169', marginLeft: 6, fontWeight: 400 }}>· {r.count} 条</span>
                    </span>
                  )}
                  style={{ marginBottom: 8, borderRadius: 10, border: '1px solid rgba(0,0,0,0.05)' }}
                >
                  {r.samples.length === 0 ? (
                    <span style={{ color: '#bfbbb5', fontSize: 12 }}>无</span>
                  ) : (() => {
                    const skipCols = new Set(['id', 'created_at', 'updated_at', 'created_by_id', 'updated_by_id', 'company_id', r.fk_field]);
                    const keys = Object.keys(r.samples[0]).filter(k => !skipCols.has(k)).slice(0, 6);
                    return (
                      <Table
                        size="small" pagination={false} dataSource={r.samples} rowKey="id"
                        columns={keys.map(k => ({
                          title: (r.labels && r.labels[k]) || k,
                          dataIndex: k, key: k, ellipsis: true,
                          render: (v, row) => {
                            if (r.fk_resolved && r.fk_resolved[k] && r.fk_resolved[k][v] != null) {
                              return r.fk_resolved[k][v];
                            }
                            return formatValue(k, v);
                          },
                        }))}
                      />
                    );
                  })()}
                </Card>
              )),
            }]}
          />
        )}

        {/* 操作历史 */}
        {history.length > 0 && (
          <Collapse
            style={{ background: '#fff', boxShadow: CARD_SHADOW, borderRadius: 12, border: 'none' }}
            size="small"
            items={[{
              key: 'h',
              label: (
                <span style={{ fontSize: 13, fontWeight: 500, letterSpacing: '0.01em' }}>
                  <HistoryOutlined style={{ color: '#777169', marginRight: 6 }} />
                  操作历史
                  <span style={{ color: '#777169', marginLeft: 6, fontWeight: 400 }}>· {history.length} 条</span>
                </span>
              ),
              children: (
                <Timeline
                  items={history.map(l => ({
                    color: ['CANCELLED', 'REJECTED', 'REVERSED'].includes(l.to_state) ? '#b42318'
                         : ['COMPLETED', 'CLOSED', 'PAID'].includes(l.to_state) ? '#1f8f3a'
                         : '#1f5aa8',
                    children: (
                      <div style={{ fontSize: 13 }}>
                        <strong style={{ fontWeight: 500, color: '#000', letterSpacing: '0.01em' }}>
                          {l.transition}
                        </strong>
                        <span style={{ marginLeft: 8, color: '#777169', fontSize: 12 }}>
                          {stateLabels[l.from_state] || l.from_state || '新建'} → {stateLabels[l.to_state] || l.to_state}
                        </span>
                        <div style={{
                          color: '#bfbbb5', fontSize: 11, marginTop: 2,
                          fontFamily: 'ui-monospace, monospace',
                        }}>
                          {l.timestamp?.replace('T', ' ').slice(0, 19)}
                        </div>
                      </div>
                    ),
                  }))}
                />
              ),
            }]}
          />
        )}

        {/* 系统信息 */}
        {grouped.system.length > 0 && (
          <Collapse
            style={{ background: '#fff', marginTop: 10, boxShadow: CARD_SHADOW, borderRadius: 12, border: 'none' }}
            size="small"
            items={[{
              key: 'sys',
              label: (
                <span style={{ fontSize: 13, color: '#4e4e4e', fontWeight: 500, letterSpacing: '0.01em' }}>
                  <SettingOutlined style={{ marginRight: 6 }} />
                  系统信息
                  <span style={{ color: '#bfbbb5', marginLeft: 6, fontWeight: 400 }}>· {grouped.system.length}</span>
                </span>
              ),
              children: (
                <div style={{
                  display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 14,
                }}>
                  {grouped.system.map(f => renderField(f, false))}
                </div>
              ),
            }]}
          />
        )}
      </div>

      {/* ============ 动作区 ============ */}
      {hasOps && (
        <div style={{ marginBottom: 12 }}>
          <SectionLabel color="#1f8f3a" icon={<ArrowRightOutlined />}>
            动作区 · 点 tab 切换查看；点最下方按钮才会真正推进
          </SectionLabel>
          <Card
            size="small"
            style={{
              borderRadius: 12,
              border: '1px solid rgba(31, 143, 58, 0.18)',
              boxShadow: CARD_SHADOW,
            }}
            styles={{ body: { padding: 0 } }}
          >
            {/* 动作 tabs */}
            <div style={{
              display: 'flex',
              borderBottom: '1px solid rgba(0,0,0,0.05)',
              background: 'rgba(245, 242, 239, 0.4)',
              flexWrap: 'wrap',
            }}>
              {actions.map((a, i) => {
                const sel = selectedActionIdx === i;
                return (
                  <div
                    key={`${a.action_label}-${a.to_state}-${i}`}
                    onClick={() => { setSelectedActionIdx(i); setPendingCard(null); }}
                    style={{
                      padding: '12px 18px', cursor: 'pointer',
                      borderBottom: sel ? '2px solid #000' : '2px solid transparent',
                      background: sel ? '#fff' : 'transparent',
                      fontWeight: sel ? 500 : 400,
                      color: sel ? '#000' : '#4e4e4e',
                      fontSize: 13,
                      letterSpacing: '0.01em',
                      transition: 'background 0.15s',
                    }}
                  >
                    {a.action_label}
                    <span style={{ color: '#777169', fontSize: 11, marginLeft: 6 }}>
                      → {stateLabels[a.to_state] || a.to_state}
                    </span>
                    {(a.editable_fields || []).length > 0 && (
                      <Pill
                        bg="#eaf1fb" color="#1f5aa8"
                        style={{ marginLeft: 8, fontSize: 10, padding: '0 6px' }}
                      >
                        {a.editable_fields.length} 字段
                      </Pill>
                    )}
                  </div>
                );
              })}
            </div>

            {/* 选中动作的内容 */}
            {selectedAction && (
              <div style={{ padding: 16 }}>
                {selectedEditableCount > 0 ? (
                  <Card
                    size="small"
                    title={<span style={{ fontSize: 13, fontWeight: 500 }}>需填字段</span>}
                    style={{
                      marginBottom: 12, borderRadius: 10,
                      border: '1px solid rgba(31, 90, 168, 0.2)',
                    }}
                    extra={dirty && <Pill bg="#fbf5e4" color="#b8860b">{Object.keys(editingFields).length} 项已填</Pill>}
                  >
                    <div style={{
                      display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: 14,
                    }}>
                      {selectedEditableList.map(f => renderField(f, true))}
                    </div>
                  </Card>
                ) : (
                  <div style={{
                    padding: '10px 14px', color: '#777169', fontSize: 12,
                    background: 'rgba(245, 242, 239, 0.5)',
                    borderRadius: 8, marginBottom: 12,
                    letterSpacing: '0.01em',
                    border: '1px solid rgba(0, 0, 0, 0.05)',
                  }}>
                    此动作不需录入字段，点下方按钮直接推进
                  </div>
                )}

                {/* 子表 */}
                {schema.sub_tables.map(sub => (
                  <SubTableEditor
                    key={`${sub.table}-${subRefreshKey}`}
                    ref={el => { subTableRefs.current[sub.table] = el; }}
                    subInfo={sub} parentId={docId} readOnly={!subEditable}
                  />
                ))}

                {/* 备注 + 提交 */}
                <Input.TextArea
                  value={comment}
                  onChange={e => setComment(e.target.value)}
                  placeholder="备注（可选）"
                  autoSize={{ minRows: 1, maxRows: 3 }}
                  style={{ marginBottom: 12, marginTop: 12, borderRadius: 10 }}
                />
                <Space wrap>
                  <Button icon={<SaveOutlined />} onClick={saveFields} loading={busy}>
                    保存
                  </Button>
                  <Button
                    type="primary"
                    size="large"
                    icon={<ArrowRightOutlined />}
                    onClick={() => requestAction(selectedAction)}
                    loading={busy}
                  >
                    {selectedAction.action_label}
                    <span style={{ opacity: 0.7, marginLeft: 6, fontWeight: 400 }}>
                      → {stateLabels[selectedAction.to_state] || selectedAction.to_state}
                    </span>
                  </Button>
                  {dirty && <Button onClick={() => setEditingFields({})}>清空已填</Button>}
                </Space>

                {pendingCard && (
                  <div style={{ marginTop: 14 }}>
                    <ChangeCard
                      card={pendingCard}
                      onApprove={approveCard}
                      onReject={() => { setPendingCard(null); message.info('已拒绝'); }}
                      disabled={busy}
                    />
                  </div>
                )}
              </div>
            )}
          </Card>
        </div>
      )}
    </div>
  );
}
