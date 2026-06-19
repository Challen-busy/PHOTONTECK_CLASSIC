/**
 * ARBillPage —— 应收单（finance-gl 应收款管理，doc_type ACCOUNTS_RECEIVABLE，完全替代金蝶应收单）
 *
 * 落 UX 律 14：台账(Table over /api/query) → 录入抽屉(不跳页) → 动作按钮(走 /api/transition 唯一写入路径)。
 *   头：客户 F7 / 币别 / 汇率 / 业务日期 / 到期日 / 立账类型(业务应收·其他应收) / 收款条件 / 销售员 F7 / 销售组织 /
 *       开关「价外税」「按含税单价录入」。本位币双金额 base_amount = amount × exchange_rate（前端实时算，提交带上）。
 *   明细网格(ar_bill_line)：物料 F7 / 计价数量 / 单价 / 税率组(带出税率) / 不含税 / 税额 / 价税合计 —— 按头开关实时算：
 *       价外税：不含税=数量×单价；税额=不含税×税率%；价税合计=不含税+税额。
 *       价内税(含税单价)：价税合计=数量×单价；不含税=价税合计/(1+税率%)；税额=价税合计−不含税。
 *   收款计划子表(ar_receipt_plan_line)：到期日 / 比例% / 计划金额（手填，比例合计应=100）。
 *   状态机 DRAFT 暂存 → SUBMITTED 提交 → AUDITED 审核（审核后业财映射生应收凭证，Phase2 effect）。
 *
 * ⚠️ 不绕底座：建单 doc_id=null→START 取号落 DRAFT；头走 field_updates，两张子表走 sub_updates；
 *   推进走 /api/transition（to_state/action_label 由 /api/transitions 按当前状态+角色过滤生成，不写死）。
 *   审核态只读，仅可反审核。失败如实回显引擎 error / rule_failures，不伪造成功。
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  App, Card, Button, Space, Table, Tag, Drawer, Input, DatePicker, Select, InputNumber,
  Switch, Form, Row, Col, Statistic, Divider, Empty, Tabs,
} from 'antd';
import { PlusOutlined, ReloadOutlined, HistoryOutlined, DeleteOutlined } from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import dayjs from 'dayjs';
import { useAuth } from '../../../auth';
import { query, transition, getTransitions } from '../../../api';
import { loadFkOptions } from '../../master/fkOptions';
import { MONO, fmtMoney, num, statusLabel } from '../financeHelpers';

const DOC_TYPE = 'ACCOUNTS_RECEIVABLE';
const TABLE = 'accounts_receivable';
const LINE_TABLE = 'ar_bill_line';
const LINE_FK = 'accounts_receivable_id';
const PLAN_TABLE = 'ar_receipt_plan_line';
const PLAN_FK = 'accounts_receivable_id';

const EDITABLE_STATES = new Set(['DRAFT', '']); // '' = 尚未建单（新建录入态）

const CURRENCIES = ['USD', 'HKD', 'CNY', 'EUR'];
const BILL_TYPE_OPTS = [
  { label: '业务应收', value: 'BUSINESS_AR' },
  { label: '其他应收', value: 'OTHER_AR' },
];
// 税率组 → 税率%（弱引用税率组码；带出可覆盖）。HK 准则一般 EXEMPT(0)。
const TAX_GROUPS = [
  { label: 'VAT13 (13%)', value: 'VAT13', rate: 13 },
  { label: 'VAT9 (9%)', value: 'VAT9', rate: 9 },
  { label: 'VAT6 (6%)', value: 'VAT6', rate: 6 },
  { label: 'EXEMPT (0%)', value: 'EXEMPT', rate: 0 },
];
const WRITEOFF_STATUS = {
  UNVERIFIED: { label: '未核销', color: 'default' },
  PARTIAL: { label: '部分核销', color: 'gold' },
  VERIFIED: { label: '已核销', color: 'green' },
};
const BILL_STATUS = {
  DRAFT: { label: '暂存', color: 'default' },
  SUBMITTED: { label: '已提交', color: 'blue' },
  AUDITED: { label: '已审核', color: 'green' },
  PENDING: { label: '待收(旧)', color: 'gold' },
  PARTIAL: { label: '部分收款(旧)', color: 'blue' },
  PAID: { label: '已收清(旧)', color: 'green' },
};

const round2 = (x) => Math.round((Number(x) || 0) * 100) / 100;

let _seq = 0;
const newLine = (over = {}) => ({
  _key: `new_${++_seq}`, id: `new_${++_seq}`,
  material_id: null, material_code: '', material_name: '',
  quantity: 0, uom: '', unit_price: 0,
  tax_rate_group: '', tax_rate: 0,
  untaxed_amount: 0, tax_amount: 0, amount: 0, remark: '',
  ...over,
});
const newPlan = (over = {}) => ({
  _key: `newp_${++_seq}`, id: `newp_${++_seq}`,
  due_date: null, ratio: 0, plan_amount: 0, received_amount: 0, remark: '',
  ...over,
});

// 单行金额按头开关重算（价外税 / 价内含税单价）。
function recalcLine(row, isPriceTaxInclusive) {
  const qty = num(row.quantity);
  const price = num(row.unit_price);
  const rate = num(row.tax_rate) / 100;
  if (isPriceTaxInclusive) {
    const amount = round2(qty * price);            // 价税合计 = 数量 × 含税单价
    const untaxed = round2(amount / (1 + rate));
    const tax = round2(amount - untaxed);
    return { ...row, amount, untaxed_amount: untaxed, tax_amount: tax };
  }
  const untaxed = round2(qty * price);             // 不含税 = 数量 × 不含税单价
  const tax = round2(untaxed * rate);
  return { ...row, untaxed_amount: untaxed, tax_amount: tax, amount: round2(untaxed + tax) };
}

export default function ARBillPage() {
  const { user } = useAuth();
  const { message } = App.useApp();
  const navigate = useNavigate();
  const [form] = Form.useForm();

  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(false);
  const [kw, setKw] = useState('');
  const [allActions, setAllActions] = useState([]);

  // F7 候选缓存
  const [customers, setCustomers] = useState([]);
  const [materials, setMaterials] = useState([]);
  const [engineers, setEngineers] = useState([]);
  const [companies, setCompanies] = useState([]);

  // 抽屉
  const [open, setOpen] = useState(false);
  const [detail, setDetail] = useState(null);      // 当前单据头（null=新建）
  const [editMode, setEditMode] = useState(false);
  const [lineRows, setLineRows] = useState([]);
  const [planRows, setPlanRows] = useState([]);
  const [busy, setBusy] = useState(false);

  // 头表单实时值（用于本位币/合计联动）
  const [exchangeRate, setExchangeRate] = useState(1);
  const [isPriceTaxInclusive, setIsPriceTaxInclusive] = useState(false);

  const status = detail?.status ?? '';
  const editable = editMode && EDITABLE_STATES.has(status);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await query(TABLE, { order_by: '-id', limit: 500 });
      const ars = data?.data || [];
      const { data: cd } = await query('customer', { limit: 1000 });
      const custById = new Map((cd?.data || []).map((c) => [c.id, c]));
      setRows(ars.map((ar) => {
        const c = custById.get(ar.customer_id) || {};
        return { ...ar, _customer: c.short_name || c.name || (ar.customer_id ? `客户#${ar.customer_id}` : '—') };
      }));
    } catch (e) {
      message.error('应收单台账加载失败：' + (e.response?.data?.detail || e.message));
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
      setMaterials(await loadFkOptions('material', 'material_id'));
      setEngineers(await loadFkOptions('user_account', 'sales_engineer_id'));
      setCompanies(await loadFkOptions('company', 'sales_org_id'));
    })();
  }, []);

  const loadLines = useCallback(async (headId) => {
    if (!headId) { setLineRows([]); setPlanRows([]); return; }
    try {
      const { data: ld } = await query(LINE_TABLE, { filters: { [LINE_FK]: headId }, order_by: 'line_number', limit: 200 });
      setLineRows((ld?.data || []).map((r) => ({ ...r })));
      const { data: pd } = await query(PLAN_TABLE, { filters: { [PLAN_FK]: headId }, order_by: 'line_number', limit: 200 });
      setPlanRows((pd?.data || []).map((r) => ({ ...r })));
    } catch { setLineRows([]); setPlanRows([]); }
  }, []);

  const openDetail = useCallback((row, edit = false) => {
    setDetail(row);
    const isEdit = edit && (!row || EDITABLE_STATES.has(row.status));
    setEditMode(isEdit);
    setExchangeRate(num(row?.exchange_rate) || 1);
    setIsPriceTaxInclusive(!!row?.is_price_tax_inclusive);
    loadLines(row?.id);
    form.setFieldsValue({
      customer_id: row?.customer_id ?? null,
      currency: row?.currency || 'USD',
      exchange_rate: num(row?.exchange_rate) || 1,
      bill_type: row?.bill_type || 'BUSINESS_AR',
      bill_date: row?.bill_date ? dayjs(row.bill_date) : dayjs(),
      due_date: row?.due_date ? dayjs(row.due_date) : null,
      payment_terms_text: row?.payment_terms_text || '',
      sales_engineer_id: row?.sales_engineer_id ?? null,
      sales_org_id: row?.sales_org_id ?? null,
      sales_dept: row?.sales_dept || '',
      is_tax_included: row?.is_tax_included ?? true,
      is_price_tax_inclusive: !!row?.is_price_tax_inclusive,
      remark: row?.remark || '',
    });
    setOpen(true);
  }, [loadLines, form]);

  const openNew = useCallback(() => {
    setDetail(null); setEditMode(true);
    setLineRows([newLine()]); setPlanRows([]);
    setExchangeRate(1); setIsPriceTaxInclusive(false);
    form.resetFields();
    form.setFieldsValue({
      currency: 'USD', exchange_rate: 1, bill_type: 'BUSINESS_AR',
      bill_date: dayjs(), is_tax_included: true, is_price_tax_inclusive: false,
    });
    setOpen(true);
  }, [form]);

  const docActions = useMemo(
    () => (status ? allActions.filter((a) => a.from_state === status) : []),
    [allActions, status]
  );

  // 合计（原币 + 本位币）。
  const totals = useMemo(() => {
    let untaxed = 0, tax = 0, amount = 0;
    for (const r of lineRows) {
      if (r._delete) continue;
      untaxed += num(r.untaxed_amount); tax += num(r.tax_amount); amount += num(r.amount);
    }
    untaxed = round2(untaxed); tax = round2(tax); amount = round2(amount);
    return { untaxed, tax, amount, base_amount: round2(amount * (exchangeRate || 1)) };
  }, [lineRows, exchangeRate]);

  // 明细网格改值 → 单行重算。
  const onLineChange = useCallback((idx, key, val) => {
    setLineRows((prev) => {
      const next = prev.slice();
      const row = { ...next[idx], [key]: val };
      // 选物料带出编码/名称/单位
      if (key === 'material_id') {
        const opt = materials.find((o) => o.value === val);
        if (opt) { row.material_name = opt.label; }
      }
      // 选税率组带出税率
      if (key === 'tax_rate_group') {
        const g = TAX_GROUPS.find((t) => t.value === val);
        if (g) row.tax_rate = g.rate;
      }
      next[idx] = recalcLine(row, isPriceTaxInclusive);
      return next;
    });
  }, [materials, isPriceTaxInclusive]);

  // 切「按含税单价录入」开关 → 全部行按新口径重算。
  const onTogglePriceTaxInclusive = useCallback((v) => {
    setIsPriceTaxInclusive(v);
    setLineRows((prev) => prev.map((r) => recalcLine(r, v)));
  }, []);

  const buildSubUpdates = useCallback((srcRows, table, fk) => {
    return srcRows.map((r, i) => {
      const { id, _delete, _key, [fk]: _f, ...rest } = r;
      const isNew = id == null || String(id).startsWith('new');
      const fields = { ...rest, line_number: rest.line_number || i + 1 };
      Object.keys(fields).forEach((k) => {
        if (k.startsWith('_')) { delete fields[k]; return; }
        if (fields[k] === '' || fields[k] === undefined) delete fields[k];
        if (dayjs.isDayjs(fields[k])) fields[k] = fields[k].format('YYYY-MM-DD');
      });
      return isNew
        ? { table, parent_fk: fk, fields }
        : { table, id, _delete: _delete || undefined, fields };
    });
  }, []);

  // 头表单值 → field_updates（带本位币双金额 + 行合计）。
  const buildFieldUpdates = useCallback((values) => {
    const fu = {};
    for (const [k, v] of Object.entries(values)) {
      if (v === undefined || v === '' || v === null) continue;
      fu[k] = dayjs.isDayjs(v) ? v.format('YYYY-MM-DD') : v;
    }
    fu.amount = totals.amount;
    fu.untaxed_amount = totals.untaxed;
    fu.tax_amount = totals.tax;
    // base_amount = 原币 × 汇率（纯算术，用户可见）。base_currency 本位币不在前端写死——
    // 由 Phase2 业财映射 effect 按本公司会计政策（CAS→CNY / HKFRS→HKD）权威回填。
    fu.base_amount = totals.base_amount;
    return fu;
  }, [totals]);

  // 保存（建/改）。
  //   新建：引擎建单 doc_id=null 入 START（同事务取应收单号），再 START→DRAFT 推进落「暂存」可编辑态。
  //     START→DRAFT 边 editable_fields=[]（仅推进，不带字段），故头/明细随「建单」一次 create 写入，
  //     推进调用不再带 field_updates（否则被引擎「字段不可编辑」拒绝）。
  //   编辑：DRAFT 态原地编辑（不切状态，引擎以全部出边可编辑字段并集校验 → 头/明细可改）。
  const onSave = useCallback(async () => {
    let values;
    try { values = await form.validateFields(); } catch { return; }
    setBusy(true);
    try {
      const sub_updates = [
        ...buildSubUpdates(lineRows, LINE_TABLE, LINE_FK),
        ...buildSubUpdates(planRows, PLAN_TABLE, PLAN_FK),
      ];
      const { data } = await transition({
        doc_type: DOC_TYPE, doc_id: detail?.id ?? null,
        field_updates: buildFieldUpdates(values), sub_updates,
        comment: detail?.id ? '应收单更新' : '应收单录入',
      });
      if (data?.success === false) {
        message.error(data.error || data.detail || '保存失败（引擎拒绝）'); return;
      }
      // 新建落 START → 推进到 DRAFT（暂存可编辑态）。
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
  }, [form, detail, buildFieldUpdates, buildSubUpdates, lineRows, planRows, message, load]);

  // 推进（提交 / 审核 / 撤回 / 反审核）。
  const runAction = useCallback(async (action) => {
    if (!detail?.id) { message.warning('请先保存单据再推进'); return; }
    setBusy(true);
    try {
      // DRAFT 态推进前先把当前编辑落库。
      let sub_updates = [];
      let field_updates = {};
      if (status === 'DRAFT' && editMode) {
        const values = await form.validateFields();
        field_updates = buildFieldUpdates(values);
        sub_updates = [
          ...buildSubUpdates(lineRows, LINE_TABLE, LINE_FK),
          ...buildSubUpdates(planRows, PLAN_TABLE, PLAN_FK),
        ];
      }
      const { data } = await transition({
        doc_type: DOC_TYPE, doc_id: detail.id,
        to_state: action.to_state, action_label: action.action_label,
        field_updates, sub_updates, comment: action.action_label,
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
  }, [detail, status, editMode, form, buildFieldUpdates, buildSubUpdates, lineRows, planRows, message, load]);

  const filtered = useMemo(() => {
    const q = kw.trim().toLowerCase();
    if (!q) return rows;
    return rows.filter((r) =>
      String(r.bill_number || '').toLowerCase().includes(q)
      || String(r._customer || '').toLowerCase().includes(q));
  }, [rows, kw]);

  const columns = [
    { title: '应收单号', dataIndex: 'bill_number', width: 150, fixed: 'left', render: (v, r) => v ? <span style={{ fontFamily: MONO }}>{v}</span> : <span style={{ color: '#bfbbb5', fontFamily: MONO }}>#{r.id}</span> },
    { title: '客户', dataIndex: '_customer', width: 180 },
    { title: '立账类型', dataIndex: 'bill_type', width: 100, render: (v) => BILL_TYPE_OPTS.find((o) => o.value === v)?.label || v || '—' },
    { title: '业务日期', dataIndex: 'bill_date', width: 110, render: (v) => v || <span style={{ color: '#bfbbb5' }}>—</span> },
    { title: '到期日', dataIndex: 'due_date', width: 110, render: (v) => v || <span style={{ color: '#bfbbb5' }}>—</span> },
    { title: '价税合计', dataIndex: 'amount', width: 130, align: 'right', render: money },
    { title: '税额', dataIndex: 'tax_amount', width: 110, align: 'right', render: money },
    { title: '币种', dataIndex: 'currency', width: 64 },
    { title: '已核销', dataIndex: 'written_off_amount', width: 110, align: 'right', render: money },
    {
      title: '核销状态', dataIndex: 'writeoff_status', width: 100,
      render: (v) => { const s = WRITEOFF_STATUS[v] || { label: v || '—', color: 'default' }; return <Tag color={s.color}>{s.label}</Tag>; },
    },
    {
      title: '单据状态', dataIndex: 'status', width: 100,
      render: (v) => { const s = BILL_STATUS[v] || { label: statusLabel(v), color: 'default' }; return <Tag color={s.color}>{s.label}</Tag>; },
    },
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

  // 明细网格列（自建可编辑 cell；改值走 onLineChange 重算）。
  const lineColumns = [
    { title: '行', width: 44, render: (_, __, i) => <span style={{ color: '#999' }}>{i + 1}</span> },
    {
      title: '物料', dataIndex: 'material_id', width: 180,
      render: (v, r, i) => editable ? (
        <Select showSearch optionFilterProp="label" allowClear size="small" style={{ width: '100%' }}
          placeholder="物料 F7" value={v} options={materials}
          onChange={(val) => onLineChange(i, 'material_id', val)} />
      ) : (materials.find((o) => o.value === v)?.label || (v ? `#${v}` : r.material_name || '—')),
    },
    {
      title: '计价数量', dataIndex: 'quantity', width: 110, align: 'right',
      render: (v, _, i) => editable ? (
        <InputNumber size="small" style={{ width: '100%' }} value={v} min={0}
          onChange={(val) => onLineChange(i, 'quantity', val)} />
      ) : <span style={{ fontFamily: MONO }}>{fmtMoney(v)}</span>,
    },
    {
      title: '单价', dataIndex: 'unit_price', width: 120, align: 'right',
      render: (v, _, i) => editable ? (
        <InputNumber size="small" style={{ width: '100%' }} value={v} min={0} precision={4}
          onChange={(val) => onLineChange(i, 'unit_price', val)} />
      ) : <span style={{ fontFamily: MONO }}>{v}</span>,
    },
    {
      title: '税率组', dataIndex: 'tax_rate_group', width: 130,
      render: (v, _, i) => editable ? (
        <Select size="small" allowClear style={{ width: '100%' }} value={v} options={TAX_GROUPS}
          onChange={(val) => onLineChange(i, 'tax_rate_group', val)} />
      ) : (TAX_GROUPS.find((t) => t.value === v)?.label || v || '—'),
    },
    { title: '税率%', dataIndex: 'tax_rate', width: 70, align: 'right', render: (v) => <span style={{ fontFamily: MONO }}>{num(v)}</span> },
    { title: '不含税', dataIndex: 'untaxed_amount', width: 120, align: 'right', render: (v) => <span style={{ fontFamily: MONO }}>{fmtMoney(v)}</span> },
    { title: '税额', dataIndex: 'tax_amount', width: 110, align: 'right', render: (v) => <span style={{ fontFamily: MONO }}>{fmtMoney(v)}</span> },
    { title: '价税合计', dataIndex: 'amount', width: 130, align: 'right', render: (v) => <span style={{ fontFamily: MONO, fontWeight: 600 }}>{fmtMoney(v)}</span> },
    {
      title: '', width: 44, fixed: 'right',
      render: (_, __, i) => editable ? (
        <Button type="text" size="small" danger icon={<DeleteOutlined />}
          onClick={() => setLineRows((prev) => prev.filter((_, idx) => idx !== i))} />
      ) : null,
    },
  ];

  const planColumns = [
    { title: '行', width: 44, render: (_, __, i) => <span style={{ color: '#999' }}>{i + 1}</span> },
    {
      title: '到期日', dataIndex: 'due_date', width: 150,
      render: (v, _, i) => editable ? (
        <DatePicker size="small" style={{ width: '100%' }} value={v ? dayjs(v) : null}
          onChange={(d) => setPlanRows((prev) => { const n = prev.slice(); n[i] = { ...n[i], due_date: d ? d.format('YYYY-MM-DD') : null }; return n; })} />
      ) : (v || '—'),
    },
    {
      title: '比例%', dataIndex: 'ratio', width: 110, align: 'right',
      render: (v, _, i) => editable ? (
        <InputNumber size="small" style={{ width: '100%' }} value={v} min={0} max={100}
          onChange={(val) => setPlanRows((prev) => { const n = prev.slice(); n[i] = { ...n[i], ratio: val }; return n; })} />
      ) : <span style={{ fontFamily: MONO }}>{num(v)}</span>,
    },
    {
      title: '计划金额', dataIndex: 'plan_amount', width: 130, align: 'right',
      render: (v, _, i) => editable ? (
        <InputNumber size="small" style={{ width: '100%' }} value={v} min={0}
          onChange={(val) => setPlanRows((prev) => { const n = prev.slice(); n[i] = { ...n[i], plan_amount: val }; return n; })} />
      ) : <span style={{ fontFamily: MONO }}>{fmtMoney(v)}</span>,
    },
    { title: '已收', dataIndex: 'received_amount', width: 110, align: 'right', render: (v) => <span style={{ fontFamily: MONO }}>{fmtMoney(v)}</span> },
    {
      title: '', width: 44, fixed: 'right',
      render: (_, __, i) => editable ? (
        <Button type="text" size="small" danger icon={<DeleteOutlined />}
          onClick={() => setPlanRows((prev) => prev.filter((_, idx) => idx !== i))} />
      ) : null,
    },
  ];

  return (
    <div>
      <div style={{ marginBottom: 16, display: 'flex', alignItems: 'baseline', gap: 12, flexWrap: 'wrap' }}>
        <h2 style={{ fontSize: 26, fontWeight: 300, letterSpacing: '-0.01em', color: '#000', margin: 0, lineHeight: 1.2 }}>应收单</h2>
        <span style={{ color: '#777169', fontSize: 13 }}>
          财务 / 应收款管理 · 客户债权立账（完全替代金蝶应收单）· 账簿 = {user?.company_name || `公司 #${user?.company_id ?? ''}`}
        </span>
      </div>

      <Card size="small" style={{ borderRadius: 14 }} styles={{ body: { padding: 0 } }}>
        <div style={{ display: 'flex', gap: 8, padding: 12, alignItems: 'center' }}>
          <Button type="primary" icon={<PlusOutlined />} onClick={openNew}>新建应收单</Button>
          <span style={{ flex: 1 }} />
          <Input.Search allowClear placeholder="应收单号 / 客户" value={kw} onChange={(e) => setKw(e.target.value)} style={{ width: 240 }} />
          <Button icon={<ReloadOutlined />} loading={loading} onClick={load}>刷新</Button>
        </div>
        {!loading && !rows.length ? (
          <Empty style={{ padding: 40 }} description="暂无应收单，点「新建应收单」录入" />
        ) : (
          <Table size="small" rowKey="id" loading={loading} dataSource={filtered} columns={columns}
            pagination={{ pageSize: 30, showSizeChanger: true }}
            scroll={{ x: 'max-content', y: 'calc(100vh - 320px)' }} sticky
            onRow={(r) => ({ onClick: () => openDetail(r, false), style: { cursor: 'pointer' } })} />
        )}
      </Card>

      <Drawer
        open={open} onClose={() => setOpen(false)} width={1080} destroyOnClose
        title={`应收单 · ${editMode ? (detail?.id ? '编辑' : '新建') : '详情'}${detail?.bill_number ? ` · ${detail.bill_number}` : ''}`}
        extra={
          <Space>
            {detail?.id && <Tag color={(BILL_STATUS[status] || {}).color}>{(BILL_STATUS[status] || {}).label || statusLabel(status)}</Tag>}
            {docActions.map((a) => (
              <Button key={`${a.action_label}-${a.to_state}`} size="small" loading={busy}
                type={a.to_state === 'AUDITED' || a.to_state === 'SUBMITTED' ? 'primary' : 'default'}
                danger={a.to_state === 'DRAFT'} onClick={() => runAction(a)}>{a.action_label}</Button>
            ))}
            {editable && <Button type="primary" loading={busy} onClick={onSave}>{detail?.id ? '保存' : '建单'}</Button>}
          </Space>
        }
      >
        <Form form={form} layout="vertical" disabled={!editable}>
          <Row gutter={16}>
            <Col span={8}><Form.Item name="customer_id" label="客户" rules={[{ required: true, message: '请选客户' }]}>
              <Select showSearch optionFilterProp="label" placeholder="客户 F7" options={customers} /></Form.Item></Col>
            <Col span={4}><Form.Item name="currency" label="币别" rules={[{ required: true }]}>
              <Select options={CURRENCIES.map((c) => ({ label: c, value: c }))} /></Form.Item></Col>
            <Col span={4}><Form.Item name="exchange_rate" label="汇率">
              <InputNumber style={{ width: '100%' }} min={0} precision={6} onChange={(v) => setExchangeRate(num(v) || 1)} /></Form.Item></Col>
            <Col span={4}><Form.Item name="bill_type" label="立账类型">
              <Select options={BILL_TYPE_OPTS} /></Form.Item></Col>
            <Col span={4}><Form.Item name="bill_date" label="业务日期"><DatePicker style={{ width: '100%' }} /></Form.Item></Col>
          </Row>
          <Row gutter={16}>
            <Col span={4}><Form.Item name="due_date" label="到期日"><DatePicker style={{ width: '100%' }} /></Form.Item></Col>
            <Col span={6}><Form.Item name="payment_terms_text" label="收款条件"><Input placeholder="如 Net 30 / T/T 预付" /></Form.Item></Col>
            <Col span={5}><Form.Item name="sales_engineer_id" label="销售员">
              <Select showSearch optionFilterProp="label" allowClear placeholder="销售员 F7" options={engineers} /></Form.Item></Col>
            <Col span={5}><Form.Item name="sales_org_id" label="销售组织">
              <Select showSearch optionFilterProp="label" allowClear placeholder="销售组织" options={companies} /></Form.Item></Col>
            <Col span={4}><Form.Item name="sales_dept" label="销售部门"><Input /></Form.Item></Col>
          </Row>
          <Row gutter={16} align="middle">
            <Col span={5}><Form.Item name="is_tax_included" label="价外税" valuePropName="checked"><Switch checkedChildren="价外税" unCheckedChildren="价内税" /></Form.Item></Col>
            <Col span={6}><Form.Item name="is_price_tax_inclusive" label="按含税单价录入" valuePropName="checked">
              <Switch checkedChildren="含税单价" unCheckedChildren="不含税单价" onChange={onTogglePriceTaxInclusive} /></Form.Item></Col>
            <Col span={13}><Form.Item name="remark" label="备注"><Input /></Form.Item></Col>
          </Row>
        </Form>

        <Tabs
          items={[
            {
              key: 'lines', label: `明细（${lineRows.filter((r) => !r._delete).length}）`,
              children: (
                <>
                  {editable && (
                    <Button size="small" type="dashed" icon={<PlusOutlined />} style={{ marginBottom: 8 }}
                      onClick={() => setLineRows((prev) => [...prev, newLine()])}>添加明细行</Button>
                  )}
                  <Table size="small" rowKey="id" pagination={false} columns={lineColumns}
                    dataSource={lineRows.filter((r) => !r._delete)} scroll={{ x: 'max-content' }}
                    summary={() => (
                      <Table.Summary fixed>
                        <Table.Summary.Row style={{ background: 'rgba(245,242,239,0.6)', fontWeight: 600 }}>
                          <Table.Summary.Cell index={0} colSpan={6}>合计</Table.Summary.Cell>
                          <Table.Summary.Cell index={6} align="right">{fmtMoney(totals.untaxed)}</Table.Summary.Cell>
                          <Table.Summary.Cell index={7} align="right">{fmtMoney(totals.tax)}</Table.Summary.Cell>
                          <Table.Summary.Cell index={8} align="right">{fmtMoney(totals.amount)}</Table.Summary.Cell>
                          <Table.Summary.Cell index={9} />
                        </Table.Summary.Row>
                      </Table.Summary>
                    )} />
                </>
              ),
            },
            {
              key: 'plan', label: `收款计划（${planRows.filter((r) => !r._delete).length}）`,
              children: (
                <>
                  {editable && (
                    <Button size="small" type="dashed" icon={<PlusOutlined />} style={{ marginBottom: 8 }}
                      onClick={() => setPlanRows((prev) => [...prev, newPlan()])}>添加收款计划行</Button>
                  )}
                  <Table size="small" rowKey="id" pagination={false} columns={planColumns}
                    dataSource={planRows.filter((r) => !r._delete)} scroll={{ x: 'max-content' }}
                    locale={{ emptyText: '无收款计划（不分期则空）' }} />
                </>
              ),
            },
          ]}
        />

        <Divider style={{ margin: '12px 0' }} />
        <Row gutter={24}>
          <Col><Statistic title="不含税合计" value={fmtMoney(totals.untaxed)} valueStyle={{ fontFamily: MONO, fontSize: 18 }} /></Col>
          <Col><Statistic title="税额合计" value={fmtMoney(totals.tax)} valueStyle={{ fontFamily: MONO, fontSize: 18 }} /></Col>
          <Col><Statistic title="价税合计（原币）" value={fmtMoney(totals.amount)} valueStyle={{ fontFamily: MONO, fontSize: 18, color: '#cf1322' }} /></Col>
          <Col><Statistic title={`本位币（×${exchangeRate}）`} value={fmtMoney(totals.base_amount)} valueStyle={{ fontFamily: MONO, fontSize: 18 }} /></Col>
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
