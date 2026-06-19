/**
 * ARReceiptPage —— 收款单（finance-gl 应收款管理，doc_type AR_RECEIPT，完全替代金蝶收款单）
 *
 * 落 UX 律 14：台账(Table over /api/query) → 录入抽屉(不跳页) → 动作按钮(走 /api/transition 唯一写入路径)。
 *   头：客户 F7 / 币别 / 汇率 / 收款日期 / 结算方式 F7 / 银行账户 / 付款方 / 收款金额 / 开关「是否预收」/ 备注。
 *       本位币双金额 base_amount = amount × exchange_rate（前端实时算，提交带上）。
 *   状态机 DRAFT 暂存 → AUDITED 审核（审核后业财映射生凭证：借 1002 银行 / 贷 1122 应收<冲减>或 2203 预收<is_advance>，
 *       Phase2 effect）。审核态只读，仅可反审核。
 *
 * ⚠️ 不绕底座：建单 doc_id=null→START 取号落 DRAFT；头走 field_updates；推进走 /api/transition
 *   （to_state/action_label 由 /api/transitions 按当前状态+角色过滤生成，不写死）。失败如实回显，不伪造成功。
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  App, Card, Button, Space, Table, Tag, Drawer, Input, DatePicker, Select, InputNumber,
  Switch, Form, Row, Col, Statistic, Empty,
} from 'antd';
import { PlusOutlined, ReloadOutlined, HistoryOutlined } from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import dayjs from 'dayjs';
import { useAuth } from '../../../auth';
import { query, transition, getTransitions } from '../../../api';
import { loadFkOptions } from '../../master/fkOptions';
import { MONO, fmtMoney, num, statusLabel } from '../financeHelpers';

const DOC_TYPE = 'AR_RECEIPT';
const TABLE = 'ar_receipt';

const EDITABLE_STATES = new Set(['DRAFT', '']);
const CURRENCIES = ['USD', 'HKD', 'CNY', 'EUR'];
const WRITEOFF_STATUS = {
  UNVERIFIED: { label: '未核销', color: 'default' },
  PARTIAL: { label: '部分核销', color: 'gold' },
  VERIFIED: { label: '已核销', color: 'green' },
};
const RECEIPT_STATUS = {
  DRAFT: { label: '暂存', color: 'default' },
  AUDITED: { label: '已审核', color: 'green' },
};
const round2 = (x) => Math.round((Number(x) || 0) * 100) / 100;

export default function ARReceiptPage() {
  const { user } = useAuth();
  const { message } = App.useApp();
  const navigate = useNavigate();
  const [form] = Form.useForm();

  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(false);
  const [kw, setKw] = useState('');
  const [allActions, setAllActions] = useState([]);

  const [customers, setCustomers] = useState([]);
  const [methods, setMethods] = useState([]);

  const [open, setOpen] = useState(false);
  const [detail, setDetail] = useState(null);
  const [editMode, setEditMode] = useState(false);
  const [busy, setBusy] = useState(false);

  const [amount, setAmount] = useState(0);
  const [exchangeRate, setExchangeRate] = useState(1);

  const status = detail?.status ?? '';
  const editable = editMode && EDITABLE_STATES.has(status);
  const baseAmount = round2(num(amount) * (num(exchangeRate) || 1));

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await query(TABLE, { order_by: '-id', limit: 500 });
      const recs = data?.data || [];
      const { data: cd } = await query('customer', { limit: 1000 });
      const custById = new Map((cd?.data || []).map((c) => [c.id, c]));
      setRows(recs.map((r) => {
        const c = custById.get(r.customer_id) || {};
        return { ...r, _customer: c.short_name || c.name || (r.customer_id ? `客户#${r.customer_id}` : '—') };
      }));
    } catch (e) {
      message.error('收款单台账加载失败：' + (e.response?.data?.detail || e.message));
      setRows([]);
    } finally { setLoading(false); }
  }, [message]);

  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    getTransitions().then(({ data }) => {
      setAllActions((data || []).filter((a) => a.doc_type === DOC_TYPE));
    }).catch(() => setAllActions([]));
    (async () => {
      setCustomers(await loadFkOptions('customer', 'customer_id'));
      setMethods(await loadFkOptions('settlement_method', 'settlement_method_id'));
    })();
  }, []);

  const openDetail = useCallback((row, edit = false) => {
    setDetail(row);
    setEditMode(edit && (!row || EDITABLE_STATES.has(row.status)));
    setAmount(num(row?.amount));
    setExchangeRate(num(row?.exchange_rate) || 1);
    form.setFieldsValue({
      customer_id: row?.customer_id ?? null,
      currency: row?.currency || 'USD',
      exchange_rate: num(row?.exchange_rate) || 1,
      receipt_date: row?.receipt_date ? dayjs(row.receipt_date) : dayjs(),
      settlement_method_id: row?.settlement_method_id ?? null,
      bank_account: row?.bank_account || '',
      payer_name: row?.payer_name || '',
      amount: num(row?.amount),
      is_advance: !!row?.is_advance,
      remark: row?.remark || '',
    });
    setOpen(true);
  }, [form]);

  const openNew = useCallback(() => {
    setDetail(null); setEditMode(true);
    setAmount(0); setExchangeRate(1);
    form.resetFields();
    form.setFieldsValue({ currency: 'USD', exchange_rate: 1, receipt_date: dayjs(), amount: 0, is_advance: false });
    setOpen(true);
  }, [form]);

  const docActions = useMemo(
    () => (status ? allActions.filter((a) => a.from_state === status) : []),
    [allActions, status]
  );

  const buildFieldUpdates = useCallback((values) => {
    const fu = {};
    for (const [k, v] of Object.entries(values)) {
      if (v === undefined || v === '' || v === null) continue;
      fu[k] = dayjs.isDayjs(v) ? v.format('YYYY-MM-DD') : v;
    }
    // base_amount = 原币 × 汇率（纯算术，用户可见）。base_currency 本位币不在前端写死——
    // 由 Phase2 业财映射 effect 按本公司会计政策（CAS→CNY / HKFRS→HKD）权威回填。
    fu.base_amount = round2(num(values.amount) * (num(values.exchange_rate) || 1));
    return fu;
  }, []);

  const onSave = useCallback(async () => {
    let values;
    try { values = await form.validateFields(); } catch { return; }
    setBusy(true);
    try {
      const { data } = await transition({
        doc_type: DOC_TYPE, doc_id: detail?.id ?? null,
        field_updates: buildFieldUpdates(values), sub_updates: [],
        comment: detail?.id ? '收款单更新' : '收款单录入',
      });
      if (data?.success === false) { message.error(data.error || data.detail || '保存失败（引擎拒绝）'); return; }
      // 新建落 START（同事务取收款单号）→ 推进到 DRAFT（暂存可编辑态）。
      // START→DRAFT 边仅推进不带字段，故头随建单一次 create 写入。
      if (!detail?.id && data?.doc_id && data?.to_state === 'START') {
        const { data: d2 } = await transition({
          doc_type: DOC_TYPE, doc_id: data.doc_id, to_state: 'DRAFT', action_label: '新建',
          field_updates: {}, sub_updates: [], comment: '进入暂存',
        });
        if (d2?.success === false) {
          message.warning('已建单（号已取），但进入暂存失败：' + (d2.error || d2.detail || ''));
        }
      }
      message.success(detail?.id ? '已保存' : '已建单（号已取）');
      setOpen(false); load();
    } catch (e) {
      message.error(e.response?.data?.detail || '保存失败（引擎写路径未就绪）');
    } finally { setBusy(false); }
  }, [form, detail, buildFieldUpdates, message, load]);

  const runAction = useCallback(async (action) => {
    if (!detail?.id) { message.warning('请先保存单据再推进'); return; }
    setBusy(true);
    try {
      let field_updates = {};
      if (status === 'DRAFT' && editMode) {
        const values = await form.validateFields();
        field_updates = buildFieldUpdates(values);
      }
      const { data } = await transition({
        doc_type: DOC_TYPE, doc_id: detail.id,
        to_state: action.to_state, action_label: action.action_label,
        field_updates, sub_updates: [], comment: action.action_label,
      });
      if (data?.success === false) {
        if (data.rule_failures) { message.error('校验未通过'); data.rule_failures.forEach((f) => message.warning(f)); }
        else message.error(data.error || data.detail || '推进失败');
        return;
      }
      message.success(`${action.action_label} 成功`);
      setOpen(false); load();
    } catch (e) {
      message.error(e.response?.data?.detail || '推进失败');
    } finally { setBusy(false); }
  }, [detail, status, editMode, form, buildFieldUpdates, message, load]);

  const filtered = useMemo(() => {
    const q = kw.trim().toLowerCase();
    if (!q) return rows;
    return rows.filter((r) =>
      String(r.receipt_number || '').toLowerCase().includes(q)
      || String(r._customer || '').toLowerCase().includes(q));
  }, [rows, kw]);

  const columns = [
    { title: '收款单号', dataIndex: 'receipt_number', width: 150, fixed: 'left', render: (v, r) => v ? <span style={{ fontFamily: MONO }}>{v}</span> : <span style={{ color: '#bfbbb5', fontFamily: MONO }}>#{r.id}</span> },
    { title: '客户', dataIndex: '_customer', width: 180 },
    { title: '收款日期', dataIndex: 'receipt_date', width: 110, render: (v) => v || <span style={{ color: '#bfbbb5' }}>—</span> },
    { title: '收款金额', dataIndex: 'amount', width: 130, align: 'right', render: money },
    { title: '币种', dataIndex: 'currency', width: 64 },
    { title: '本位币', dataIndex: 'base_amount', width: 130, align: 'right', render: money },
    { title: '预收', dataIndex: 'is_advance', width: 70, render: (v) => v ? <Tag color="purple">预收</Tag> : <span style={{ color: '#bfbbb5' }}>—</span> },
    { title: '已核销', dataIndex: 'written_off_amount', width: 110, align: 'right', render: money },
    {
      title: '核销状态', dataIndex: 'writeoff_status', width: 100,
      render: (v) => { const s = WRITEOFF_STATUS[v] || { label: v || '—', color: 'default' }; return <Tag color={s.color}>{s.label}</Tag>; },
    },
    {
      title: '单据状态', dataIndex: 'status', width: 90,
      render: (v) => { const s = RECEIPT_STATUS[v] || { label: statusLabel(v), color: 'default' }; return <Tag color={s.color}>{s.label}</Tag>; },
    },
    { title: '关联凭证', dataIndex: 'voucher_id', width: 100, render: (v) => v ? <Tag color="geekblue">凭证#{v}</Tag> : <Tag>未生成</Tag> },
    {
      title: '操作', dataIndex: '_a', width: 150, fixed: 'right',
      render: (_, r) => (
        <Space size={4}>
          <Button type="link" size="small" onClick={(e) => { e.stopPropagation(); openDetail(r, false); }}>详情</Button>
          {EDITABLE_STATES.has(r.status) && (
            <Button type="link" size="small" onClick={(e) => { e.stopPropagation(); openDetail(r, true); }}>编辑</Button>
          )}
          <Button type="link" size="small" icon={<HistoryOutlined />} onClick={(e) => { e.stopPropagation(); navigate(`/history/${DOC_TYPE}/${r.id}`); }}>历史</Button>
        </Space>
      ),
    },
  ];

  return (
    <div>
      <div style={{ marginBottom: 16, display: 'flex', alignItems: 'baseline', gap: 12, flexWrap: 'wrap' }}>
        <h2 style={{ fontSize: 26, fontWeight: 300, letterSpacing: '-0.01em', color: '#000', margin: 0, lineHeight: 1.2 }}>收款单</h2>
        <span style={{ color: '#777169', fontSize: 13 }}>
          财务 / 应收款管理 · 客户实收款登记（完全替代金蝶收款单）· 账簿 = {user?.company_name || `公司 #${user?.company_id ?? ''}`}
        </span>
      </div>

      <Card size="small" style={{ borderRadius: 14 }} styles={{ body: { padding: 0 } }}>
        <div style={{ display: 'flex', gap: 8, padding: 12, alignItems: 'center' }}>
          <Button type="primary" icon={<PlusOutlined />} onClick={openNew}>新建收款单</Button>
          <span style={{ flex: 1 }} />
          <Input.Search allowClear placeholder="收款单号 / 客户" value={kw} onChange={(e) => setKw(e.target.value)} style={{ width: 240 }} />
          <Button icon={<ReloadOutlined />} loading={loading} onClick={load}>刷新</Button>
        </div>
        {!loading && !rows.length ? (
          <Empty style={{ padding: 40 }} description="暂无收款单，点「新建收款单」录入" />
        ) : (
          <Table size="small" rowKey="id" loading={loading} dataSource={filtered} columns={columns}
            pagination={{ pageSize: 30, showSizeChanger: true }}
            scroll={{ x: 'max-content', y: 'calc(100vh - 320px)' }} sticky
            onRow={(r) => ({ onClick: () => openDetail(r, false), style: { cursor: 'pointer' } })} />
        )}
      </Card>

      <Drawer
        open={open} onClose={() => setOpen(false)} width={760} destroyOnClose
        title={`收款单 · ${editMode ? (detail?.id ? '编辑' : '新建') : '详情'}${detail?.receipt_number ? ` · ${detail.receipt_number}` : ''}`}
        extra={
          <Space>
            {detail?.id && <Tag color={(RECEIPT_STATUS[status] || {}).color}>{(RECEIPT_STATUS[status] || {}).label || statusLabel(status)}</Tag>}
            {docActions.map((a) => (
              <Button key={`${a.action_label}-${a.to_state}`} size="small" loading={busy}
                type={a.to_state === 'AUDITED' ? 'primary' : 'default'}
                danger={a.to_state === 'DRAFT'} onClick={() => runAction(a)}>{a.action_label}</Button>
            ))}
            {editable && <Button type="primary" loading={busy} onClick={onSave}>{detail?.id ? '保存' : '建单'}</Button>}
          </Space>
        }
      >
        <Form form={form} layout="vertical" disabled={!editable}>
          <Row gutter={16}>
            <Col span={12}><Form.Item name="customer_id" label="客户" rules={[{ required: true, message: '请选客户' }]}>
              <Select showSearch optionFilterProp="label" placeholder="客户 F7" options={customers} /></Form.Item></Col>
            <Col span={6}><Form.Item name="currency" label="币别" rules={[{ required: true }]}>
              <Select options={CURRENCIES.map((c) => ({ label: c, value: c }))} /></Form.Item></Col>
            <Col span={6}><Form.Item name="exchange_rate" label="汇率">
              <InputNumber style={{ width: '100%' }} min={0} precision={6} onChange={(v) => setExchangeRate(num(v) || 1)} /></Form.Item></Col>
          </Row>
          <Row gutter={16}>
            <Col span={8}><Form.Item name="receipt_date" label="收款日期"><DatePicker style={{ width: '100%' }} /></Form.Item></Col>
            <Col span={8}><Form.Item name="settlement_method_id" label="结算方式">
              <Select showSearch optionFilterProp="label" allowClear placeholder="结算方式 F7" options={methods} /></Form.Item></Col>
            <Col span={8}><Form.Item name="bank_account" label="银行账户"><Input placeholder="收款银行账户" /></Form.Item></Col>
          </Row>
          <Row gutter={16}>
            <Col span={8}><Form.Item name="payer_name" label="付款方"><Input /></Form.Item></Col>
            <Col span={8}><Form.Item name="amount" label="收款金额" rules={[{ required: true, message: '请填收款金额' }]}>
              <InputNumber style={{ width: '100%' }} min={0} precision={2} onChange={(v) => setAmount(num(v))} /></Form.Item></Col>
            <Col span={8}><Form.Item name="is_advance" label="是否预收" valuePropName="checked">
              <Switch checkedChildren="预收" unCheckedChildren="非预收" /></Form.Item></Col>
          </Row>
          <Form.Item name="remark" label="备注"><Input.TextArea rows={2} /></Form.Item>
        </Form>

        <Row gutter={24} style={{ marginTop: 8 }}>
          <Col><Statistic title="收款金额（原币）" value={fmtMoney(amount)} valueStyle={{ fontFamily: MONO, fontSize: 18, color: '#389e0d' }} /></Col>
          <Col><Statistic title={`本位币（×${exchangeRate}）`} value={fmtMoney(baseAmount)} valueStyle={{ fontFamily: MONO, fontSize: 18 }} /></Col>
        </Row>
      </Drawer>
    </div>
  );
}

function money(v) {
  const n = Number(v);
  if (!n) return <span style={{ color: '#d9d4cd' }}>—</span>;
  return <span style={{ fontFamily: MONO }}>{fmtMoney(v)}</span>;
}
