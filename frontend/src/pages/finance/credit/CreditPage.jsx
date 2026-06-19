/**
 * CreditPage —— 信用管理（finance-gl 信用波，完全替代金蝶信用管理 P0）
 *
 * 四 Tab，全后端 _company_filter 隔离（账簿=当前会话公司）：
 *   · 信用档案 —— customer_credit（信用额度/单笔限额/逾期阈值/信用状态/检查规则）；编辑走 upsert_customer_credit 命令；重算占用走 finance.recompute_credit。
 *   · 信用状况查询 —— /api/reports/credit-status（额度/已占用/可用/使用率/预警）。
 *   · 信用超标记录 —— /api/reports/credit-overlimit（validator 触发超标时落库）。
 *   · 信用检查规则 —— credit_check_rule + 明细（哪些单据在哪个时点用什么策略检查/占用信用，只读）。
 *
 * ★信用控制总开关 = company.credit_control_enabled（默认关，金蝶口径「需先启用信用控制」）。
 *   关闭时应收单审核 validator 全 pass；开启后按检查规则的控制策略 提示/严格控制 校验可用额度。
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  App, Card, Tabs, Table, Tag, Button, Space, Drawer, Form, InputNumber, Input, Select, Alert,
} from 'antd';
import { ReloadOutlined, EditOutlined, CalculatorOutlined } from '@ant-design/icons';
import { useAuth } from '../../../auth';
import {
  query, getCreditStatus, getCreditOverlimit, recomputeCredit, upsertCustomerCredit,
} from '../../../api';
import { MONO, fmtMoney } from '../financeHelpers';

const STATUS = { NORMAL: { label: '正常', color: 'green' }, FROZEN: { label: '冻结', color: 'red' } };
const OVER_TYPE = {
  CREDIT_LIMIT: '超信用额度', SINGLE_LIMIT: '超单笔限额', OVERDUE: '逾期超标', FROZEN: '信用冻结',
};
const STRATEGY = { NONE: '不控制', WARN: '提示', STRICT: '严格控制' };
const num = (v) => (v == null ? 0 : Number(v));

export default function CreditPage() {
  const { user } = useAuth();
  const { message } = App.useApp();
  const [tab, setTab] = useState('profile');

  return (
    <div>
      <div style={{ marginBottom: 16, display: 'flex', alignItems: 'baseline', gap: 12, flexWrap: 'wrap' }}>
        <h2 style={{ fontSize: 26, fontWeight: 300, letterSpacing: '-0.01em', color: '#000', margin: 0, lineHeight: 1.2 }}>
          信用管理
        </h2>
        <span style={{ color: '#777169', fontSize: 13 }}>
          财务 / 信用管理 · 信用档案 / 状况 / 超标 / 检查规则 · 账簿 = {user?.company_name || `公司 #${user?.company_id ?? ''}`}
        </span>
      </div>
      <Card styles={{ body: { padding: '12px 16px' } }}>
        <Tabs
          activeKey={tab}
          onChange={setTab}
          items={[
            { key: 'profile', label: '信用档案', children: <ProfileTab message={message} /> },
            { key: 'status', label: '信用状况查询', children: <StatusTab message={message} /> },
            { key: 'overlimit', label: '信用超标记录', children: <OverlimitTab message={message} /> },
            { key: 'rule', label: '信用检查规则', children: <RuleTab message={message} /> },
          ]}
        />
      </Card>
    </div>
  );
}

/* ── 信用档案 ── */
function ProfileTab({ message }) {
  const [rows, setRows] = useState([]);
  const [customers, setCustomers] = useState([]);
  const [rules, setRules] = useState([]);
  const [loading, setLoading] = useState(false);
  const [open, setOpen] = useState(false);
  const [form] = Form.useForm();
  const custById = useMemo(() => new Map(customers.map((c) => [c.id, c])), [customers]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [cc, cu, ru] = await Promise.all([
        query('customer_credit', { limit: 1000, order_by: '-id' }),
        query('customer', { limit: 1000, order_by: 'code' }),
        query('credit_check_rule', { limit: 200, order_by: 'id' }),
      ]);
      setRows(cc.data?.data || []);
      setCustomers(cu.data?.data || []);
      setRules(ru.data?.data || []);
    } catch (e) {
      message.error('加载失败：' + (e.response?.data?.detail || e.message));
    } finally {
      setLoading(false);
    }
  }, [message]);
  useEffect(() => { load(); }, [load]);

  const onEdit = (row) => {
    form.resetFields();
    form.setFieldsValue({
      customer_id: row?.customer_id, credit_limit: num(row?.credit_limit), single_limit: num(row?.single_limit),
      currency: row?.currency || 'CNY', credit_status: row?.credit_status || 'NORMAL',
      overdue_days: row?.overdue_days || 0, overdue_amount: num(row?.overdue_amount),
      warning_threshold_pct: row?.warning_threshold_pct || 80, check_rule_id: row?.check_rule_id || undefined,
      credit_rating: row?.credit_rating || '',
    });
    setOpen(true);
  };
  const onSave = async () => {
    const v = await form.validateFields();
    try {
      await upsertCustomerCredit(v);
      message.success('已保存信用档案');
      setOpen(false);
      load();
    } catch (e) { message.error('保存失败：' + (e.response?.data?.detail || e.message)); }
  };
  const onRecompute = async () => {
    try {
      const { data } = await recomputeCredit(undefined);
      message.success(`重算完成：更新 ${data?.result?.profiles_updated ?? 0} 户`);
      load();
    } catch (e) { message.error('重算失败：' + (e.response?.data?.detail || e.message)); }
  };

  const columns = [
    { title: '客户', dataIndex: 'customer_id', render: (v) => custById.get(v)?.name || `#${v}` },
    { title: '币别', dataIndex: 'currency', width: 70 },
    { title: '信用额度', dataIndex: 'credit_limit', align: 'right', render: (v) => <span style={{ fontFamily: MONO }}>{fmtMoney(v)}</span> },
    { title: '已占用', dataIndex: 'used_amount', align: 'right', render: (v) => <span style={{ fontFamily: MONO }}>{fmtMoney(v)}</span> },
    { title: '可用', align: 'right', render: (_, r) => { const a = num(r.credit_limit) - num(r.used_amount); return <span style={{ fontFamily: MONO, color: a < 0 ? '#cf1322' : undefined }}>{fmtMoney(a)}</span>; } },
    { title: '单笔限额', dataIndex: 'single_limit', align: 'right', render: (v) => num(v) > 0 ? <span style={{ fontFamily: MONO }}>{fmtMoney(v)}</span> : <span style={{ color: '#bfbbb5' }}>不限</span> },
    { title: '信用状态', dataIndex: 'credit_status', width: 90, render: (v) => { const s = STATUS[v] || STATUS.NORMAL; return <Tag color={s.color}>{s.label}</Tag>; } },
    { title: '等级', dataIndex: 'credit_rating', width: 70, render: (v) => v || <span style={{ color: '#bfbbb5' }}>—</span> },
    { title: '操作', width: 80, render: (_, r) => <Button size="small" icon={<EditOutlined />} onClick={() => onEdit(r)}>改</Button> },
  ];

  return (
    <>
      <Alert type="info" showIcon style={{ marginBottom: 12 }}
        message="信用控制总开关 = 公司级 credit_control_enabled（默认关）。开启后应收单审核按检查规则校验可用额度（提示/严格控制）。" />
      <Space style={{ marginBottom: 12 }}>
        <Button type="primary" icon={<EditOutlined />} onClick={() => onEdit(null)}>新建/维护信用档案</Button>
        <Button icon={<CalculatorOutlined />} onClick={onRecompute}>重算占用</Button>
        <Button icon={<ReloadOutlined />} onClick={load}>刷新</Button>
      </Space>
      <Table rowKey="id" size="small" loading={loading} dataSource={rows} columns={columns} pagination={{ pageSize: 20 }} />
      <Drawer title="信用档案" width={480} open={open} onClose={() => setOpen(false)}
        extra={<Button type="primary" onClick={onSave}>保存</Button>}>
        <Form form={form} layout="vertical">
          <Form.Item name="customer_id" label="客户" rules={[{ required: true, message: '选客户' }]}>
            <Select showSearch optionFilterProp="label" placeholder="选客户"
              options={customers.map((c) => ({ value: c.id, label: `${c.name}${c.code ? `（${c.code}）` : ''}` }))} />
          </Form.Item>
          <Form.Item name="credit_limit" label="信用额度" rules={[{ required: true }]}><InputNumber style={{ width: '100%' }} min={0} /></Form.Item>
          <Form.Item name="single_limit" label="单笔限额（0=不限）"><InputNumber style={{ width: '100%' }} min={0} /></Form.Item>
          <Form.Item name="currency" label="币别"><Select options={['CNY', 'USD', 'HKD'].map((c) => ({ value: c, label: c }))} /></Form.Item>
          <Form.Item name="credit_status" label="信用状态"><Select options={[{ value: 'NORMAL', label: '正常' }, { value: 'FROZEN', label: '冻结' }]} /></Form.Item>
          <Form.Item name="warning_threshold_pct" label="预警阈值 %"><InputNumber style={{ width: '100%' }} min={0} max={100} /></Form.Item>
          <Form.Item name="overdue_days" label="逾期天数阈值（0=不控）"><InputNumber style={{ width: '100%' }} min={0} /></Form.Item>
          <Form.Item name="overdue_amount" label="逾期额度阈值（0=不控）"><InputNumber style={{ width: '100%' }} min={0} /></Form.Item>
          <Form.Item name="check_rule_id" label="检查规则（空=用公司默认）">
            <Select allowClear placeholder="默认" options={rules.map((r) => ({ value: r.id, label: `${r.name}（${r.code}）` }))} />
          </Form.Item>
          <Form.Item name="credit_rating" label="信用等级"><Input placeholder="如 A / B / C" /></Form.Item>
        </Form>
      </Drawer>
    </>
  );
}

/* ── 信用状况查询 ── */
function StatusTab({ message }) {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(false);
  const [onlyOver, setOnlyOver] = useState(false);
  const load = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await getCreditStatus({ only_over: onlyOver });
      setRows(data?.data || []);
    } catch (e) { message.error('加载失败：' + (e.response?.data?.detail || e.message)); }
    finally { setLoading(false); }
  }, [message, onlyOver]);
  useEffect(() => { load(); }, [load]);

  const columns = [
    { title: '客户', dataIndex: 'customer_name', render: (v, r) => v || `#${r.customer_id}` },
    { title: '币别', dataIndex: 'currency', width: 70 },
    { title: '信用额度', dataIndex: 'credit_limit', align: 'right', render: (v) => <span style={{ fontFamily: MONO }}>{fmtMoney(v)}</span> },
    { title: '已占用', dataIndex: 'used_amount', align: 'right', render: (v) => <span style={{ fontFamily: MONO }}>{fmtMoney(v)}</span> },
    { title: '可用', dataIndex: 'available', align: 'right', render: (v) => <span style={{ fontFamily: MONO, color: v < 0 ? '#cf1322' : undefined }}>{fmtMoney(v)}</span> },
    { title: '使用率', dataIndex: 'usage_pct', width: 110, render: (v, r) => <Tag color={r.is_over ? 'red' : r.is_warning ? 'orange' : 'green'}>{v}%</Tag> },
    { title: '单笔限额', dataIndex: 'single_limit', align: 'right', render: (v) => num(v) > 0 ? fmtMoney(v) : <span style={{ color: '#bfbbb5' }}>不限</span> },
    { title: '状态', dataIndex: 'credit_status', width: 80, render: (v) => { const s = STATUS[v] || STATUS.NORMAL; return <Tag color={s.color}>{s.label}</Tag>; } },
  ];
  return (
    <>
      <Space style={{ marginBottom: 12 }}>
        <Button type={onlyOver ? 'primary' : 'default'} danger={onlyOver} onClick={() => setOnlyOver((v) => !v)}>{onlyOver ? '仅看超标/预警 ✓' : '仅看超标/预警'}</Button>
        <Button icon={<ReloadOutlined />} onClick={load}>刷新</Button>
      </Space>
      <Table rowKey="customer_id" size="small" loading={loading} dataSource={rows} columns={columns} pagination={{ pageSize: 20 }} />
    </>
  );
}

/* ── 信用超标记录 ── */
function OverlimitTab({ message }) {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(false);
  const load = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await getCreditOverlimit({});
      setRows(data?.data || []);
    } catch (e) { message.error('加载失败：' + (e.response?.data?.detail || e.message)); }
    finally { setLoading(false); }
  }, [message]);
  useEffect(() => { load(); }, [load]);

  const columns = [
    { title: '客户', dataIndex: 'customer_name', render: (v, r) => v || `#${r.customer_id}` },
    { title: '单据', dataIndex: 'doc_no', render: (v) => <span style={{ fontFamily: MONO }}>{v || '—'}</span> },
    { title: '业务日', dataIndex: 'biz_date', width: 110 },
    { title: '本单占用', dataIndex: 'occupy_amount', align: 'right', render: (v) => <span style={{ fontFamily: MONO }}>{fmtMoney(v)}</span> },
    { title: '可用(前)', dataIndex: 'available_before', align: 'right', render: (v) => <span style={{ fontFamily: MONO }}>{fmtMoney(v)}</span> },
    { title: '超标额', dataIndex: 'over_amount', align: 'right', render: (v) => <span style={{ fontFamily: MONO, color: '#cf1322' }}>{fmtMoney(v)}</span> },
    { title: '超标类型', dataIndex: 'over_type', width: 110, render: (v) => OVER_TYPE[v] || v },
    { title: '策略', dataIndex: 'control_strategy', width: 90, render: (v) => STRATEGY[v] || v },
    { title: '动作', dataIndex: 'action', width: 80, render: (v) => <Tag color={v === 'BLOCK' ? 'red' : 'orange'}>{v === 'BLOCK' ? '阻断' : '提示'}</Tag> },
  ];
  return (
    <>
      <Space style={{ marginBottom: 12 }}><Button icon={<ReloadOutlined />} onClick={load}>刷新</Button></Space>
      <Table rowKey="id" size="small" loading={loading} dataSource={rows} columns={columns} pagination={{ pageSize: 20 }} />
    </>
  );
}

/* ── 信用检查规则（只读） ── */
function RuleTab({ message }) {
  const [rules, setRules] = useState([]);
  const [lines, setLines] = useState([]);
  const [loading, setLoading] = useState(false);
  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [ru, li] = await Promise.all([
        query('credit_check_rule', { limit: 200, order_by: 'id' }),
        query('credit_check_rule_line', { limit: 500, order_by: 'id' }),
      ]);
      setRules(ru.data?.data || []);
      setLines(li.data?.data || []);
    } catch (e) { message.error('加载失败：' + (e.response?.data?.detail || e.message)); }
    finally { setLoading(false); }
  }, [message]);
  useEffect(() => { load(); }, [load]);

  const linesByRule = useMemo(() => {
    const m = new Map();
    lines.forEach((l) => { if (!m.has(l.credit_check_rule_id)) m.set(l.credit_check_rule_id, []); m.get(l.credit_check_rule_id).push(l); });
    return m;
  }, [lines]);

  const lineCols = [
    { title: '单据名称', dataIndex: 'doc_name' },
    { title: '单据类型', dataIndex: 'doc_type', render: (v) => <span style={{ fontFamily: MONO, fontSize: 12 }}>{v}</span> },
    { title: '时点', dataIndex: 'check_point', width: 80, render: (v) => ({ SAVE: '保存', SUBMIT: '提交', AUDIT: '审核' }[v] || v) },
    { title: '控制策略', dataIndex: 'control_strategy', width: 100, render: (v) => <Tag color={v === 'STRICT' ? 'red' : v === 'WARN' ? 'orange' : 'default'}>{STRATEGY[v] || v}</Tag> },
    { title: '占用额度', dataIndex: 'update_credit', width: 80, render: (v) => v ? '✓' : '—' },
    { title: '检查额度', dataIndex: 'check_credit_limit', width: 80, render: (v) => v ? '✓' : '—' },
    { title: '检查单笔', dataIndex: 'check_single_limit', width: 80, render: (v) => v ? '✓' : '—' },
    { title: '检查逾期', dataIndex: 'check_overdue', width: 80, render: (v) => v ? '✓' : '—' },
  ];
  return (
    <>
      <Alert type="info" showIcon style={{ marginBottom: 12 }} message="检查规则定义哪些单据在哪个时点用什么控制策略校验/占用信用额度。P0 默认规则：应收单·审核·提示。改严格控制可阻断超额单据。" />
      <Space style={{ marginBottom: 12 }}><Button icon={<ReloadOutlined />} onClick={load}>刷新</Button></Space>
      {rules.map((r) => (
        <Card key={r.id} size="small" style={{ marginBottom: 12 }}
          title={<span>{r.name} <span style={{ fontFamily: MONO, color: '#777169', fontSize: 12 }}>（{r.code}）</span>{r.is_default && <Tag color="blue" style={{ marginLeft: 8 }}>默认</Tag>}</span>}>
          <Table rowKey="id" size="small" loading={loading} pagination={false}
            dataSource={linesByRule.get(r.id) || []} columns={lineCols} />
        </Card>
      ))}
    </>
  );
}
