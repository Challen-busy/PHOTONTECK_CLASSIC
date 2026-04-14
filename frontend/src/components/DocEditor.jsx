/**
 * 通用单据编辑器 — 四区结构
 *
 *   展示区: Hero + 节点说明 + 详细字段(只读) + 子表summary + 关联主对象 + 反向关联
 *   动作区: 每个可执行动作一个 tab；切换只影响前端显示；
 *            选中某动作 → 显示该 next 的 editable_fields 表单 + 子表编辑 + 硬规则提示 + 提交按钮
 *            点提交才真正调后端 /transition
 */

import { useEffect, useMemo, useState } from 'react';
import {
  Card, Input, InputNumber, DatePicker, Select, Table, Button, Space, Spin,
  message, Tag, Empty, Timeline, Collapse, Badge,
} from 'antd';
import {
  SaveOutlined, PlusOutlined, DeleteOutlined, EditOutlined, LockOutlined,
  ArrowRightOutlined,
} from '@ant-design/icons';
import dayjs from 'dayjs';
import api from '../api';
import { query, agentCheck, agentExecute, getHistory } from '../api';
import { useAuth } from '../auth';
import ChangeCard from './ChangeCard';

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

// ===== 节点说明清洗（去掉给Agent看的格式标记） =====
function cleanDescription(text) {
  if (!text) return '';
  return text.split('\n')
    .filter(line => !line.trim().startsWith('# '))      // 去掉 "# 节点 节点"
    .map(line => line.replace(/^\s*-\s*【[^】]*】/, '• '))  // 去掉 "-【X → Y】" 前缀，换成 •
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
  const readOnlyStyle = { padding: '4px 11px', background: '#fafafa', borderRadius: 6, border: '1px solid #f0f0f0', fontSize: 13, minHeight: 30 };

  // 只读：无论值是否为空，都渲染为 div，避免 null 值传给 DatePicker 等控件引起的内部报错
  if (disabled) {
    if (value == null || value === '') {
      return <div style={{ ...readOnlyStyle, color: '#ccc' }}>—</div>;
    }
    if (name === 'status' && stateLabels && stateLabels[value]) {
      return <div style={{ ...readOnlyStyle, background: '#e6f4ff', borderColor: '#91caff', fontWeight: 500 }}>{stateLabels[value]}</div>;
    }
    if (fk) {
      const opt = (fkOptions || []).find(o => o.id === value);
      return <div style={readOnlyStyle}>{opt ? rowLabel(opt) : `#${value}`}</div>;
    }
    return <div style={{ ...readOnlyStyle, whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>{formatValue(name, value)}</div>;
  }

  if (fk) {
    return (
      <Select value={value} onChange={onChange} disabled={disabled}
        style={{ width: '100%' }} showSearch allowClear optionFilterProp="label"
        placeholder={`选择${field.label || fk.table}`}
        options={(fkOptions || []).map(o => ({ value: o.id, label: rowLabel(o) }))} />
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
function SubTableEditor({ subInfo, parentId, onUpdate, readOnly = false }) {
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

  if (loading) return <Spin />;
  if (!schema) return null;

  const skipFields = new Set(['id', subInfo.parent_fk, 'created_at', 'updated_at', 'created_by_id', 'updated_by_id']);
  const cols = schema.fields.filter(f => !skipFields.has(f.name));
  const numericFields = cols.filter(c => c.type === 'number' || c.type === 'integer');
  const totals = {};
  numericFields.forEach(f => { totals[f.name] = rows.reduce((sum, r) => sum + (Number(r[f.name]) || 0), 0); });

  const addRow = () => {
    const newRow = { _new: true, _tempId: Date.now(), [subInfo.parent_fk]: parentId };
    cols.forEach(c => { newRow[c.name] = c.type === 'number' || c.type === 'integer' ? 0 : ''; });
    setRows([...rows, newRow]);
  };
  const deleteRow = (row) => {
    if (row._new) setRows(rows.filter(r => r._tempId !== row._tempId));
    else setRows(rows.map(r => r.id === row.id ? { ...r, _delete: true } : r));
  };
  const editCell = (row, field, value) => {
    if (row._new) setRows(rows.map(r => r._tempId === row._tempId ? { ...r, [field]: value } : r));
    else setRows(rows.map(r => r.id === row.id ? { ...r, [field]: value, _modified: true } : r));
  };
  const save = async () => {
    const updates = rows.filter(r => r._new || r._modified || r._delete).map(r => {
      const fields = {};
      cols.forEach(c => { if (r[c.name] !== undefined) fields[c.name] = r[c.name]; });
      fields[subInfo.parent_fk] = parentId;
      return { table: subInfo.table, id: r._new ? undefined : r.id, _delete: r._delete, fields, parent_fk: subInfo.parent_fk };
    });
    if (updates.length === 0) { message.info('无变更'); return; }
    onUpdate(updates);
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
        : <FieldInput field={col} value={row[col.name]} onChange={val => editCell(row, col.name, val)} fkOptions={fkOptions[col.name]} disabled={false} />,
    })),
    ...(readOnly ? [] : [{
      title: '', key: '_a', width: 50, fixed: 'right',
      render: (_, row) => <Button size="small" danger icon={<DeleteOutlined />} onClick={() => deleteRow(row)} />,
    }]),
  ];

  const dirty = rows.some(r => r._new || r._modified || r._delete);
  const subTitle = subInfo.table_label || subInfo.table;
  return (
    <Card size="small" title={`${subTitle} · ${visibleRows.length}行`}
      style={{ marginBottom: 8, borderRadius: 8 }}
      extra={!readOnly && (
        <Space>
          <Button size="small" icon={<PlusOutlined />} onClick={addRow}>添加</Button>
          {dirty && <Button size="small" type="primary" icon={<SaveOutlined />} onClick={save}>保存子表</Button>}
        </Space>
      )}>
      <Table dataSource={visibleRows} columns={tableColumns} rowKey={r => r.id || r._tempId}
        size="small" pagination={false} scroll={{ x: 'max-content' }}
        summary={() => Object.keys(totals).length > 0 ? (
          <Table.Summary.Row style={{ background: '#fafafa' }}>
            <Table.Summary.Cell index={0} colSpan={cols.length - Object.keys(totals).length}><strong>合计</strong></Table.Summary.Cell>
            {cols.filter(c => c.type === 'number' || c.type === 'integer').map(c => (
              <Table.Summary.Cell key={c.name} index={0}><strong>{totals[c.name].toLocaleString()}</strong></Table.Summary.Cell>
            ))}
            {!readOnly && <Table.Summary.Cell />}
          </Table.Summary.Row>
        ) : null}
      />
    </Card>
  );
}

// ===== FK 信息卡片（关联主对象）=====
function ForwardFkCard({ field, target_table_label, row, labels = {}, fieldLabel }) {
  const keyFields = [];
  for (const f of ID_FIELDS) if (row[f]) { keyFields.push({ k: f, v: row[f] }); break; }
  const extras = [];
  for (const f of ['total_amount', 'amount', 'credit_limit', 'used_amount', 'status', 'role', 'currency', 'country', 'contact_person']) {
    if (row[f] != null && row[f] !== '') extras.push({ k: f, v: formatValue(f, row[f]) });
  }
  return (
    <Card size="small" style={{ borderRadius: 8, background: '#f0f5ff', borderColor: '#adc6ff' }}>
      <div style={{ fontSize: 11, color: '#888', marginBottom: 4 }}>{fieldLabel || field}</div>
      <div style={{ fontWeight: 600, fontSize: 14, color: '#1a1a2e', marginBottom: 6 }}>
        {keyFields[0]?.v || `#${row.id}`}
        {target_table_label && <span style={{ fontSize: 10, color: '#999', marginLeft: 6 }}>({target_table_label})</span>}
      </div>
      <div style={{ fontSize: 11, color: '#666', display: 'flex', flexWrap: 'wrap', gap: 8 }}>
        {extras.slice(0, 4).map(({ k, v }) => (
          <span key={k}><span style={{ color: '#aaa' }}>{labels[k] || k}:</span> {v}</span>
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
    if (Object.keys(editingFields).length === 0) { message.info('无变更'); return; }
    setBusy(true);
    try {
      const { data } = await api.post('/transition', { doc_type: docType, doc_id: docId, field_updates: editingFields });
      if (data.success) {
        const n = Object.keys(data.changed_fields || {}).length;
        message.success(`已保存 ${n} 项`);
        setEditingFields({}); load();
      } else if (data.rule_failures) {
        message.error('校验未通过');
        data.rule_failures.forEach(f => message.warning(f));
      } else message.error(data.error || '保存失败');
    } catch (e) { message.error('保存失败'); }
    setBusy(false);
  };

  const saveSubTable = async (updates) => {
    setBusy(true);
    try {
      const { data } = await api.post('/transition', { doc_type: docType, doc_id: docId, field_updates: {}, sub_updates: updates });
      if (data.success) {
        message.success(`子表更新: ${(data.sub_changes || []).join(', ')}`);
        load();
      } else message.error(data.error || '保存失败');
    } catch { message.error('保存失败'); }
    setBusy(false);
  };

  const requestAction = async (action) => {
    // 提交前：只带上该动作允许的字段（跨 tab 填写的其他字段忽略）
    const allowed = new Set(action.editable_fields || []);
    const filtered = {};
    Object.entries(editingFields).forEach(([k, v]) => { if (allowed.has(k)) filtered[k] = v; });
    setBusy(true);
    try {
      const { data: card } = await agentCheck({
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
      const { data } = await agentExecute(card, comment);
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
      if (selectedEditableSet.has(f.name)) {
        g.editable.push(f);
      } else if (cat === 'hero_id' && !g.hero_id) g.hero_id = f;
      else if (cat === 'hero_party' && !g.hero_party) g.hero_party = f;
      else if (cat === 'hero_amount' && !g.hero_amount) g.hero_amount = f;
      else if (cat === 'system') g.system.push(f);
      else g.detail.push(f);
    });
    return g;
  }, [schema, selectedEditableSet, isAdminRole]);

  if (loading) return <Spin size="large" style={{ display: 'block', margin: '40px auto' }} />;
  if (!schema || !doc) return <Empty description="加载失败" />;

  const idValue = grouped.hero_id ? doc[grouped.hero_id.name] : null;
  const partyValue = grouped.hero_party ? (fkOptions[grouped.hero_party.name] || []).find(o => o.id === doc[grouped.hero_party.name]) : null;
  const amountValue = grouped.hero_amount ? doc[grouped.hero_amount.name] : null;
  const currency = doc.currency || '';
  const statusLabel = stateLabels[doc.status] || doc.status;
  const dirty = Object.keys(editingFields).length > 0;
  // 子表编辑：只要有任何动作可选，就允许编辑（真正提交靠点按钮）
  const hasOps = actions.length > 0;
  const selectedEditableList = grouped.editable;
  const selectedEditableCount = selectedEditableList.length;
  const cleanedDesc = cleanDescription(nodeDescription);

  const renderField = (f, editable) => {
    const value = editingFields[f.name] !== undefined ? editingFields[f.name] : doc[f.name];
    return (
      <div key={f.name}>
        <div style={{ fontSize: 12, color: editable ? '#1890ff' : '#888', marginBottom: 4 }}>
          {f.label || f.name}
          {editable ? <EditOutlined style={{ marginLeft: 4, color: '#1890ff' }} /> : <LockOutlined style={{ marginLeft: 4, color: '#ccc', fontSize: 11 }} />}
          {!f.nullable && editable && <span style={{ color: '#ff4d4f' }}> *</span>}
        </div>
        <FieldInput field={f} value={value}
          onChange={v => editable ? setEditingFields({ ...editingFields, [f.name]: v }) : null}
          disabled={!editable} fkOptions={fkOptions[f.name]} stateLabels={stateLabels} />
      </div>
    );
  };

  return (
    <div>
      {/* === Hero 卡片 === */}
      <Card style={{
        borderRadius: 12, marginBottom: 12,
        background: 'linear-gradient(135deg, #1a1a2e 0%, #2d3748 100%)',
        color: '#fff', border: 'none',
      }} styles={{ body: { padding: '16px 20px' } }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 24, flexWrap: 'wrap' }}>
          {grouped.hero_id && (
            <div>
              <div style={{ fontSize: 11, opacity: 0.7 }}>{grouped.hero_id.label}</div>
              <div style={{ fontSize: 20, fontWeight: 600, fontFamily: 'ui-monospace, monospace' }}>{idValue || `#${docId}`}</div>
            </div>
          )}
          {grouped.hero_party && (
            <div>
              <div style={{ fontSize: 11, opacity: 0.7 }}>{grouped.hero_party.label}</div>
              <div style={{ fontSize: 16, fontWeight: 500 }}>{partyValue ? rowLabel(partyValue) : '—'}</div>
            </div>
          )}
          {grouped.hero_amount && amountValue != null && (
            <div>
              <div style={{ fontSize: 11, opacity: 0.7 }}>{grouped.hero_amount.label}</div>
              <div style={{ fontSize: 20, fontWeight: 600, color: '#ffd700' }}>{currency} {Number(amountValue).toLocaleString()}</div>
            </div>
          )}
          <div style={{ flex: 1 }} />
          <div style={{ textAlign: 'right' }}>
            <div style={{ fontSize: 11, opacity: 0.7 }}>当前节点</div>
            <Tag color="gold" style={{ fontSize: 14, padding: '4px 12px', margin: 0 }}>{statusLabel}</Tag>
          </div>
        </div>
      </Card>

      {/* === 节点说明（人话）=== */}
      {cleanedDesc && (
        <Card size="small" style={{ borderRadius: 8, marginBottom: 12, background: '#fffbe6', borderColor: '#ffe58f' }}>
          <div style={{ fontSize: 13, whiteSpace: 'pre-wrap', color: '#594800' }}>📌 {cleanedDesc}</div>
        </Card>
      )}

      {/* ============ 展示区 ============ */}
      <div style={{ marginBottom: 12 }}>
        <div style={{ fontSize: 12, color: '#888', marginBottom: 6, paddingLeft: 4 }}>📄 展示区</div>

        {/* 详细字段（只读）*/}
        {grouped.detail.length > 0 && (
          <Card size="small" title="详细信息" style={{ borderRadius: 8, marginBottom: 8 }}>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 12 }}>
              {grouped.detail.map(f => renderField(f, false))}
            </div>
          </Card>
        )}

        {/* 关联主对象（forward FK 卡片）*/}
        {related.forward.length > 0 && (
          <Card size="small" title="🔗 关联对象" style={{ borderRadius: 8, marginBottom: 8 }}>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: 8 }}>
              {related.forward.map((f, i) => {
                const fieldDef = schema.fields.find(x => x.name === f.field);
                return <ForwardFkCard key={i} {...f} fieldLabel={fieldDef?.label || f.field} />;
              })}
            </div>
          </Card>
        )}

        {/* 子表：没有任何可选动作时全部只读展示（否则放到下面动作区编辑）*/}
        {!hasOps && schema.sub_tables.map(sub => (
          <SubTableEditor key={sub.table} subInfo={sub} parentId={docId} onUpdate={saveSubTable} readOnly={true} />
        ))}

        {/* 反向关联（折叠）*/}
        {related.reverse.length > 0 && (
          <Collapse style={{ marginBottom: 8, background: '#fff' }} size="small"
            items={[{
              key: 'rev', label: <span><Badge count={related.reverse.reduce((s, r) => s + r.count, 0)} style={{ backgroundColor: '#999' }} /> 反向关联（其他表里指向这单的）</span>,
              children: related.reverse.map((r, i) => (
                <Card key={i} size="small" title={`${r.table_label || r.table}（${r.count} 条）`} style={{ marginBottom: 6 }}>
                  {r.samples.length === 0 ? <span style={{ color: '#999', fontSize: 12 }}>无</span> : (() => {
                    const skipCols = new Set(['id', 'created_at', 'updated_at', 'created_by_id', 'updated_by_id', 'company_id', r.fk_field]);
                    const keys = Object.keys(r.samples[0]).filter(k => !skipCols.has(k)).slice(0, 6);
                    return (
                      <Table size="small" pagination={false} dataSource={r.samples} rowKey="id"
                        columns={keys.map(k => ({
                          title: (r.labels && r.labels[k]) || k,
                          dataIndex: k, key: k, ellipsis: true,
                          render: (v, row) => {
                            // FK 字段用后端解析的中文名
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

        {/* 操作历史（折叠）*/}
        {history.length > 0 && (
          <Collapse style={{ background: '#fff' }} size="small"
            items={[{
              key: 'h', label: `📜 操作历史（${history.length}条）`,
              children: <Timeline items={history.map(l => ({
                color: ['CANCELLED', 'REJECTED', 'REVERSED'].includes(l.to_state) ? 'red' : ['COMPLETED', 'CLOSED', 'PAID'].includes(l.to_state) ? 'green' : 'blue',
                children: (
                  <div style={{ fontSize: 13 }}>
                    <strong>{l.transition}</strong>
                    <span style={{ marginLeft: 8, color: '#888' }}>
                      {stateLabels[l.from_state] || l.from_state || '新建'} → {stateLabels[l.to_state] || l.to_state}
                    </span>
                    <div style={{ color: '#999', fontSize: 11 }}>{l.timestamp?.replace('T', ' ').slice(0, 19)}</div>
                  </div>
                ),
              }))} />,
            }]} />
        )}

        {/* 系统信息（折叠，仅 admin 看）*/}
        {grouped.system.length > 0 && (
          <Collapse style={{ background: '#fff', marginTop: 8 }} size="small"
            items={[{
              key: 'sys', label: <span style={{ color: '#888' }}>⚙ 系统信息（{grouped.system.length}）</span>,
              children: (
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 12 }}>
                  {grouped.system.map(f => renderField(f, false))}
                </div>
              ),
            }]} />
        )}
      </div>

      {/* ============ 动作区（选动作 → 看字段 → 提交推进）============ */}
      {hasOps && (
        <div style={{ marginBottom: 12 }}>
          <div style={{ fontSize: 12, color: '#52c41a', marginBottom: 6, paddingLeft: 4 }}>
            ➡ 动作区（点 tab 切换查看；点最下方按钮才会真正推进）
          </div>
          <Card size="small" style={{ borderRadius: 8, borderColor: '#b7eb8f' }} styles={{ body: { padding: 0 } }}>
            {/* 动作 tabs */}
            <div style={{ display: 'flex', borderBottom: '1px solid #f0f0f0', background: '#fafafa', flexWrap: 'wrap' }}>
              {actions.map((a, i) => (
                <div key={`${a.action_label}-${a.to_state}-${i}`}
                  onClick={() => { setSelectedActionIdx(i); setPendingCard(null); }}
                  style={{
                    padding: '10px 16px', cursor: 'pointer',
                    borderBottom: selectedActionIdx === i ? '2px solid #52c41a' : '2px solid transparent',
                    background: selectedActionIdx === i ? '#fff' : 'transparent',
                    fontWeight: selectedActionIdx === i ? 600 : 400,
                    fontSize: 13,
                  }}>
                  {a.action_label}
                  <span style={{ color: '#999', fontSize: 11, marginLeft: 6 }}>
                    → {stateLabels[a.to_state] || a.to_state}
                  </span>
                  {(a.editable_fields || []).length > 0 && (
                    <Tag color="blue" style={{ marginLeft: 6, fontSize: 10 }}>{a.editable_fields.length} 字段</Tag>
                  )}
                </div>
              ))}
            </div>

            {/* 选中动作的内容 */}
            {selectedAction && (
              <div style={{ padding: 14 }}>
                {/* 该动作可编辑字段 */}
                {selectedEditableCount > 0 ? (
                  <Card size="small" title="需填字段" style={{ marginBottom: 10, borderColor: '#91caff' }}
                    extra={dirty && <Tag color="orange">{Object.keys(editingFields).length} 项已填</Tag>}>
                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: 12 }}>
                      {selectedEditableList.map(f => renderField(f, true))}
                    </div>
                  </Card>
                ) : (
                  <div style={{ padding: '8px 12px', color: '#888', fontSize: 12, background: '#fafafa', borderRadius: 6, marginBottom: 10 }}>
                    此动作不需录入字段，点下方按钮直接推进
                  </div>
                )}

                {/* 子表（可编辑，所有动作共享）*/}
                {schema.sub_tables.map(sub => (
                  <SubTableEditor key={sub.table} subInfo={sub} parentId={docId} onUpdate={saveSubTable} readOnly={false} />
                ))}

                {/* 备注 + 提交 */}
                <Input.TextArea value={comment} onChange={e => setComment(e.target.value)}
                  placeholder="备注（可选）" autoSize={{ minRows: 1, maxRows: 3 }} style={{ marginBottom: 10, marginTop: 10 }} />
                <Space>
                  <Button type="primary" size="large" icon={<ArrowRightOutlined />}
                    onClick={() => requestAction(selectedAction)} loading={busy}>
                    {selectedAction.action_label} → {stateLabels[selectedAction.to_state] || selectedAction.to_state}
                  </Button>
                  {dirty && <Button onClick={() => setEditingFields({})}>清空已填</Button>}
                </Space>

                {pendingCard && (
                  <div style={{ marginTop: 12 }}>
                    <ChangeCard card={pendingCard} onApprove={approveCard}
                      onReject={() => { setPendingCard(null); message.info('已拒绝'); }} disabled={busy} />
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
