/**
 * RecurringSchemePage —— 定期凭证方案（总账·finance-gl wave-6，自动转账 / 摊销 / 预提 三合一）
 *
 * 对齐金蝶「定期转账 / 自动转账 / 待摊预提」惯例：建一份模板方案（头 + 分录模板子表），
 *   每期一键按方案生成 DRAFT 凭证（走标准 VOUCHER 审核→过账闸，本页不绕过账）。
 *
 *   头：账簿（当前公司，会话隔离只读）+ 按 scheme_type 三 tab 切（全部 / 自动转账 / 摊销 / 预提）。
 *   台账：query('recurring_voucher_scheme')，摊销方案显示 total_amount / periods / 已摊期数进度条。
 *   新建/编辑：走引擎唯一写入 /api/transition（doc_type=RECURRING_SCHEME，含分录模板子表 sub_updates），
 *     参 MasterDataPage 子表提交范式（recurring_voucher_line：line_number/account_id/account_code/dr_cr/
 *     description/amount/formula）。
 *   生成本期凭证：选期间 → finance.generate_recurring_voucher（scheme_id + period_id）→ 回执提示跳
 *     /finance/voucher?id={voucher_id} 看草稿；幂等已存在 / 摊销已摊完 → created:false 友好提示。
 *
 * 取数底座：方案/分录均 company_scoped（后端 _company_filter 隔离当前账簿）；HK/CAS 科目码不同 → 各家落各家方案。
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  App, Button, Card, Form, Input, InputNumber, Modal, Progress, Segmented, Select, Space, Spin,
  Table, Tag, Descriptions,
} from 'antd';
import {
  PlusOutlined, ThunderboltOutlined, EditOutlined, HistoryOutlined, ReloadOutlined,
  FileAddOutlined,
} from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../../auth';
import {
  query, transition, getAccountingPeriods, executeCommand,
} from '../../api';
import { BizEditableTable } from '../../components/biz';
import { MONO, fmtMoney, num, loadAccounts, getCachedAccounts, statusLabel } from './financeHelpers';

// scheme_type 元数据：标签 + 配色 + 段控选项。
const SCHEME_TYPE = {
  TRANSFER: { label: '自动转账', color: 'geekblue' },
  AMORTIZATION: { label: '摊销', color: 'purple' },
  ACCRUAL: { label: '预提', color: 'volcano' },
};
const TYPE_FILTERS = ['ALL', 'TRANSFER', 'AMORTIZATION', 'ACCRUAL'];

function SchemeTypeTag({ value }) {
  const m = SCHEME_TYPE[value];
  if (!m) return <Tag>{value}</Tag>;
  return <Tag color={m.color}>{m.label}</Tag>;
}

export default function RecurringSchemePage() {
  const { user } = useAuth();
  const { message } = App.useApp();
  const navigate = useNavigate();

  const [schemes, setSchemes] = useState([]);
  const [loading, setLoading] = useState(true);
  const [typeFilter, setTypeFilter] = useState('ALL');

  const [periods, setPeriods] = useState([]);
  const [vwords, setVwords] = useState([]);
  const [accounts, setAccounts] = useState(getCachedAccounts() || []);

  // 编辑抽屉/弹层
  const [editorOpen, setEditorOpen] = useState(false);
  const [editing, setEditing] = useState(null);   // null=新建，否则为方案对象
  const [form] = Form.useForm();
  const [lines, setLines] = useState([]);
  const [saving, setSaving] = useState(false);
  const watchType = Form.useWatch('scheme_type', form);

  // 生成本期凭证弹层
  const [genOpen, setGenOpen] = useState(false);
  const [genScheme, setGenScheme] = useState(null);
  const [genPeriodId, setGenPeriodId] = useState(null);
  const [genBusy, setGenBusy] = useState(false);
  const [genReceipt, setGenReceipt] = useState(null);

  const reloadSchemes = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await query('recurring_voucher_scheme', { order_by: 'code', limit: 500 });
      setSchemes(data?.data || []);
    } catch (e) {
      message.error('方案加载失败：' + (e.response?.data?.detail || e.message));
    } finally {
      setLoading(false);
    }
  }, [message]);

  useEffect(() => {
    reloadSchemes();
    getAccountingPeriods()
      .then(({ data }) => setPeriods(data?.periods || []))
      .catch(() => {});
    query('voucher_word', { filters: { is_active: true }, order_by: 'id', limit: 50 })
      .then(({ data }) => setVwords(data?.data || []))
      .catch(() => {});
    loadAccounts().then(setAccounts).catch(() => {});
  }, [reloadSchemes]);

  // 叶子科目可挂分录；id→code 映射供保存时补 account_code 弱引用。
  const accountById = useMemo(() => {
    const m = new Map();
    accounts.forEach((a) => m.set(a.id, a));
    return m;
  }, [accounts]);
  const accountValueEnum = useMemo(() => {
    const e = {};
    accounts.forEach((a) => { e[a.id] = { text: `${a.code} ${a.name}`, disabled: a.is_leaf === false }; });
    return e;
  }, [accounts]);

  const filtered = useMemo(() => {
    if (typeFilter === 'ALL') return schemes;
    return schemes.filter((s) => s.scheme_type === typeFilter);
  }, [schemes, typeFilter]);

  // ---- 打开编辑器（新建 / 编辑） ----
  const openEditor = useCallback(async (scheme) => {
    setEditing(scheme || null);
    form.resetFields();
    if (scheme) {
      form.setFieldsValue({
        code: scheme.code, name: scheme.name, scheme_type: scheme.scheme_type,
        voucher_word_id: scheme.voucher_word_id ?? undefined,
        description: scheme.description || '',
        total_amount: scheme.total_amount != null ? Number(scheme.total_amount) : undefined,
        periods: scheme.periods ?? undefined,
        start_period_id: scheme.start_period_id ?? undefined,
        is_active: scheme.is_active !== false,
      });
      // 拉已有分录模板子表
      try {
        const { data } = await query('recurring_voucher_line', {
          filters: { scheme_id: scheme.id }, order_by: 'line_number', limit: 100,
        });
        setLines((data?.data || []).map((r) => ({ ...r })));
      } catch {
        setLines([]);
      }
    } else {
      form.setFieldsValue({ scheme_type: 'TRANSFER', is_active: true, description: '' });
      setLines([]);
    }
    setEditorOpen(true);
  }, [form]);

  // ---- 保存（引擎唯一写入 /api/transition） ----
  const onSave = async () => {
    let values;
    try {
      values = await form.validateFields();
    } catch {
      return;
    }
    if (!lines.length) {
      message.warning('请至少录入一行分录模板');
      return;
    }
    setSaving(true);
    try {
      const field_updates = {};
      for (const [k, v] of Object.entries(values)) {
        if (v === undefined || v === '') continue;
        field_updates[k] = v;
      }
      // 分录模板 → sub_updates（参 MasterDataPage 子表范式：新行 id=new_*，去 parent_fk）
      const sub_updates = lines.map((r, i) => {
        const { id, scheme_id: _sid, _delete, ...rest } = r;
        const isNew = id == null || String(id).startsWith('new_');
        const acctCode = rest.account_id != null
          ? (accountById.get(rest.account_id)?.code || rest.account_code || '')
          : (rest.account_code || '');
        const fields = {
          line_number: rest.line_number || i + 1,
          account_id: rest.account_id ?? null,
          account_code: acctCode,
          dr_cr: rest.dr_cr || 'DR',
          description: rest.description || '',
          amount: rest.amount != null && rest.amount !== '' ? Number(rest.amount) : null,
          formula: rest.formula || '',
        };
        return isNew
          ? { table: 'recurring_voucher_line', parent_fk: 'scheme_id', fields }
          : { table: 'recurring_voucher_line', id, _delete: _delete || undefined, fields };
      });
      const { data } = await transition({
        doc_type: 'RECURRING_SCHEME',
        doc_id: editing?.id ?? null,
        field_updates,
        sub_updates,
        comment: editing?.id ? '定期凭证方案更新' : '定期凭证方案建档',
      });
      if (data?.success === false) {
        message.error(data.error || data.detail || '保存失败（引擎拒绝）');
        return;
      }
      message.success(editing?.id ? '方案已更新' : '方案已建档');
      setEditorOpen(false);
      reloadSchemes();
    } catch (e) {
      message.error('保存失败：' + (e.response?.data?.detail || e.message || '引擎写路径未就绪'));
    } finally {
      setSaving(false);
    }
  };

  // ---- 生成本期凭证 ----
  const openGen = useCallback((scheme) => {
    setGenScheme(scheme);
    setGenReceipt(null);
    // 默认选最早的 OPEN 期间
    const open = periods.find((p) => p.status === 'OPEN') || periods[0];
    setGenPeriodId(open?.id ?? null);
    setGenOpen(true);
  }, [periods]);

  const runGenerate = async () => {
    if (!genScheme || !genPeriodId) {
      message.warning('请选择凭证落账期间');
      return;
    }
    setGenBusy(true);
    try {
      const { data } = await executeCommand('finance.generate_recurring_voucher', {
        scheme_id: genScheme.id, period_id: genPeriodId,
      });
      if (data?.success === false) {
        message.error(data.error || '生成失败');
        return;
      }
      setGenReceipt(data);
      if (data.created) {
        message.success(data.message || '已生成定期凭证（草稿）');
        reloadSchemes(); // 摊销进度可能推进
      } else {
        message.info(data.message || '本期已生成 / 摊销已摊完（幂等）');
      }
    } catch (e) {
      message.error('生成失败：' + (e.response?.data?.detail || e.message));
    } finally {
      setGenBusy(false);
    }
  };

  // ---- 台账列 ----
  const columns = useMemo(() => [
    { title: '方案码', dataIndex: 'code', width: 150, fixed: 'left',
      render: (v) => <span style={{ fontFamily: MONO }}>{v}</span> },
    { title: '方案名称', dataIndex: 'name', width: 200, ellipsis: true },
    { title: '类型', dataIndex: 'scheme_type', width: 96, render: (v) => <SchemeTypeTag value={v} /> },
    { title: '默认摘要', dataIndex: 'description', ellipsis: true,
      render: (v) => v || <span style={{ color: '#bfbbb5' }}>—</span> },
    {
      title: '摊销进度', key: '_amort', width: 220,
      render: (_, r) => {
        if (r.scheme_type !== 'AMORTIZATION') return <span style={{ color: '#d9d4cd' }}>—</span>;
        const total = Number(r.periods) || 0;
        const done = Number(r.amortized_periods) || 0;
        const pct = total ? Math.round((done / total) * 100) : 0;
        return (
          <div>
            <div style={{ fontSize: 12, color: '#777169' }}>
              待摊 <span style={{ fontFamily: MONO }}>{fmtMoney(r.total_amount)}</span>
              {total ? <> · 每期 <span style={{ fontFamily: MONO }}>{fmtMoney(num(r.total_amount) / total)}</span></> : null}
            </div>
            <Progress percent={pct} size="small" status={done >= total && total > 0 ? 'success' : 'active'}
              format={() => `${done}/${total} 期`} />
          </div>
        );
      },
    },
    {
      title: '状态', dataIndex: 'is_active', width: 72,
      render: (v) => v === false
        ? <Tag>停用</Tag>
        : <Tag color="green">启用</Tag>,
    },
    {
      title: '操作', key: '_action', width: 230, fixed: 'right',
      render: (_, r) => (
        <Space size={2}>
          <Button type="link" size="small" icon={<ThunderboltOutlined />} onClick={() => openGen(r)}>
            生成本期凭证
          </Button>
          <Button type="link" size="small" icon={<EditOutlined />} onClick={() => openEditor(r)}>
            编辑
          </Button>
          <Button type="link" size="small" icon={<HistoryOutlined />}
            onClick={() => navigate(`/history/RECURRING_SCHEME/${r.id}`)}>
            历史
          </Button>
        </Space>
      ),
    },
  ], [openGen, openEditor, navigate]);

  // ---- 分录模板网格列 ----
  const lineColumns = useMemo(() => [
    { title: '行号', dataIndex: 'line_number', valueType: 'digit', width: 64,
      fieldProps: { min: 1, precision: 0 } },
    {
      title: '会计科目', dataIndex: 'account_id', width: 240, valueType: 'select',
      valueEnum: accountValueEnum,
      fieldProps: { showSearch: true, optionFilterProp: 'label', placeholder: '编码/名称' },
      render: (_, r) => {
        const a = accountById.get(r.account_id);
        if (a) return <span style={{ fontFamily: MONO }}>{a.code} {a.name}</span>;
        if (r.account_code) return <span style={{ fontFamily: MONO }}>{r.account_code}</span>;
        return <span style={{ color: '#bfbbb5' }}>—</span>;
      },
    },
    {
      title: '借/贷', dataIndex: 'dr_cr', width: 90, valueType: 'select',
      fieldProps: { options: [{ value: 'DR', label: '借 DR' }, { value: 'CR', label: '贷 CR' }] },
      render: (_, r) => <Tag color={r.dr_cr === 'CR' ? 'gold' : 'blue'}>{r.dr_cr === 'CR' ? '贷' : '借'}</Tag>,
    },
    { title: '摘要', dataIndex: 'description', ellipsis: true },
    { title: '金额（固定额）', dataIndex: 'amount', valueType: 'digit', width: 140,
      fieldProps: { min: 0, precision: 2 },
      render: (v) => (v == null || v === '') ? <span style={{ color: '#bfbbb5' }}>—</span> : <span style={{ fontFamily: MONO }}>{fmtMoney(v)}</span> },
    { title: '公式', dataIndex: 'formula', width: 150,
      tooltip: '取数表达式，如 total/periods（摊销每期额）；留空则用固定金额',
      render: (v) => v ? <code style={{ fontSize: 12 }}>{v}</code> : <span style={{ color: '#bfbbb5' }}>—</span> },
  ], [accountValueEnum, accountById]);

  const isAmort = watchType === 'AMORTIZATION';

  return (
    <div>
      <div style={{ marginBottom: 16, display: 'flex', alignItems: 'baseline', gap: 12, flexWrap: 'wrap' }}>
        <h2 style={{ fontSize: 26, fontWeight: 300, letterSpacing: '-0.01em', color: '#000', margin: 0, lineHeight: 1.2 }}>
          定期凭证方案
        </h2>
        <span style={{ color: '#777169', fontSize: 13 }}>
          财务 / 总账 · 自动转账 / 摊销 / 预提 · 账簿 = 当前公司 · 每期一键生成草稿凭证（走标准审核过账闸）
        </span>
      </div>

      {/* 筛选条 + 新建 */}
      <Card size="small" style={{ borderRadius: 14, marginBottom: 12 }}>
        <div style={{ display: 'flex', gap: 24, alignItems: 'center', flexWrap: 'wrap' }}>
          <Field label="账簿 / 核算组织（当前公司）">
            <Tag color="geekblue">{user?.company_name || `公司 #${user?.company_id ?? ''}`}</Tag>
          </Field>
          <Field label="方案类型">
            <Segmented
              size="small"
              value={typeFilter}
              onChange={setTypeFilter}
              options={TYPE_FILTERS.map((t) => ({
                value: t,
                label: t === 'ALL' ? '全部' : SCHEME_TYPE[t].label,
              }))}
            />
          </Field>
          <div style={{ flex: 1 }} />
          <Space>
            <Button icon={<ReloadOutlined />} onClick={reloadSchemes}>刷新</Button>
            <Button type="primary" icon={<PlusOutlined />} onClick={() => openEditor(null)}>新建方案</Button>
          </Space>
        </div>
      </Card>

      <Card size="small" style={{ borderRadius: 14 }} styles={{ body: { padding: 0 } }}>
        <Spin spinning={loading}>
          <Table
            rowKey="id"
            size="small"
            dataSource={filtered}
            columns={columns}
            pagination={{ pageSize: 20, size: 'small', showSizeChanger: true }}
            scroll={{ x: 'max-content' }}
            locale={{ emptyText: '暂无定期凭证方案，点「新建方案」创建' }}
          />
        </Spin>
      </Card>

      {/* ===== 新建/编辑方案（抽屉式 Modal，含分录模板子表） ===== */}
      <Modal
        open={editorOpen}
        onCancel={() => setEditorOpen(false)}
        title={editing?.id ? `编辑方案 · ${editing.code}` : '新建定期凭证方案'}
        width={900}
        okText="保存"
        confirmLoading={saving}
        onOk={onSave}
        maskClosable={false}
        destroyOnHidden
      >
        <Form form={form} layout="vertical" style={{ marginTop: 8 }}>
          <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
            <Form.Item name="code" label="方案码" rules={[{ required: true, message: '请填方案码' }]} style={{ width: 220 }}>
              <Input placeholder="如 RS-AMORT-INS" disabled={!!editing?.id} />
            </Form.Item>
            <Form.Item name="name" label="方案名称" rules={[{ required: true, message: '请填方案名称' }]} style={{ width: 280 }}>
              <Input placeholder="如 保险费摊销" />
            </Form.Item>
            <Form.Item name="scheme_type" label="类型" rules={[{ required: true }]} style={{ width: 160 }}>
              <Select options={Object.entries(SCHEME_TYPE).map(([v, m]) => ({ value: v, label: m.label }))} />
            </Form.Item>
            <Form.Item name="voucher_word_id" label="默认凭证字" style={{ width: 160 }}>
              <Select allowClear placeholder="多为「转」"
                options={vwords.map((w) => ({ value: w.id, label: `${w.code || ''} ${w.name || ''}`.trim() }))} />
            </Form.Item>
          </div>
          <Form.Item name="description" label="默认凭证摘要">
            <Input placeholder="生成凭证时的默认摘要" />
          </Form.Item>

          {/* 摊销专属字段 */}
          {isAmort && (
            <Card size="small" style={{ borderRadius: 10, marginBottom: 12, background: 'rgba(245,242,239,0.5)' }}
              title={<span style={{ fontSize: 13 }}>摊销参数（每期额 = 待摊总额 / 摊销期数，末期吃尾差）</span>}>
              <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
                <Form.Item name="total_amount" label="待摊总额"
                  rules={[{ required: true, message: '请填待摊总额' }]} style={{ width: 200 }}>
                  <InputNumber min={0} precision={2} style={{ width: '100%' }} placeholder="如 12000.00" />
                </Form.Item>
                <Form.Item name="periods" label="摊销期数"
                  rules={[{ required: true, message: '请填摊销期数' }]} style={{ width: 140 }}>
                  <InputNumber min={1} precision={0} style={{ width: '100%' }} placeholder="如 12" />
                </Form.Item>
                <Form.Item name="start_period_id" label="起始摊销期间" style={{ width: 220 }}>
                  <Select allowClear placeholder="选起始期间"
                    options={periods.map((p) => ({ value: p.id, label: `${p.label}${p.status !== 'OPEN' ? `（${p.status}）` : ''}` }))} />
                </Form.Item>
                {editing?.id && (
                  <Field label="已摊期数（进度）">
                    <Tag color="purple">{editing.amortized_periods ?? 0} / {editing.periods ?? '—'} 期</Tag>
                  </Field>
                )}
              </div>
            </Card>
          )}

          <div style={{ fontWeight: 500, color: '#4e4e4e', margin: '4px 0 8px' }}>
            分录模板
            <span style={{ color: '#bfbbb5', fontSize: 12, marginLeft: 8 }}>
              固定额方案直填金额；摊销方案在公式填 <code>total/periods</code>（每期额）
            </span>
          </div>
          <BizEditableTable
            value={lines}
            onChange={setLines}
            rowKey="id"
            columns={lineColumns}
            recordCreatorProps={{
              record: () => ({ id: `new_${Date.now()}`, dr_cr: 'DR', line_number: lines.length + 1 }),
              creatorButtonText: '添加分录行',
            }}
          />
        </Form>
      </Modal>

      {/* ===== 生成本期凭证 ===== */}
      <Modal
        open={genOpen}
        onCancel={() => setGenOpen(false)}
        title={<span><FileAddOutlined /> 生成本期凭证 · {genScheme?.code}</span>}
        width={560}
        footer={[
          <Button key="close" onClick={() => setGenOpen(false)}>关闭</Button>,
          <Button key="gen" type="primary" icon={<ThunderboltOutlined />} loading={genBusy} onClick={runGenerate}>
            生成草稿凭证
          </Button>,
        ]}
        destroyOnHidden
      >
        {genScheme && (
          <Descriptions size="small" column={1} style={{ marginBottom: 12 }}>
            <Descriptions.Item label="方案">{genScheme.name} <SchemeTypeTag value={genScheme.scheme_type} /></Descriptions.Item>
            {genScheme.scheme_type === 'AMORTIZATION' && (
              <Descriptions.Item label="摊销进度">
                <Tag color="purple">{genScheme.amortized_periods ?? 0} / {genScheme.periods ?? '—'} 期</Tag>
                {Number(genScheme.amortized_periods) >= Number(genScheme.periods) && Number(genScheme.periods) > 0 && (
                  <Tag color="default">已摊完</Tag>
                )}
              </Descriptions.Item>
            )}
          </Descriptions>
        )}
        <div style={{ marginBottom: 8 }}>
          <span style={{ fontSize: 12, color: '#777169' }}>凭证落账期间</span>
        </div>
        <Select
          style={{ width: '100%' }}
          value={genPeriodId}
          onChange={setGenPeriodId}
          placeholder="选择期间（默认期末日为凭证日期）"
          options={periods.map((p) => ({
            value: p.id,
            label: `${p.label}${p.status !== 'OPEN' ? `（${p.status}）` : ''}`,
            disabled: p.status === 'CLOSED',
          }))}
        />
        <div style={{ fontSize: 12, color: '#a8a39c', marginTop: 8 }}>
          幂等：同（方案 + 期间）已生成则返回既有；摊销已摊完则不再生成。生成的凭证为 <Tag>DRAFT</Tag> 草稿，
          请到「凭证录入」审核并过账。
        </div>

        {/* 回执 */}
        {genReceipt && (
          <Card size="small" style={{ marginTop: 14, borderRadius: 10, background: 'rgba(245,242,239,0.5)' }}
            title="生成回执">
            <Descriptions size="small" column={1}>
              <Descriptions.Item label="是否生成">
                {genReceipt.created
                  ? <Tag color="green">已生成（草稿）</Tag>
                  : <Tag>未生成（幂等已存在 / 已摊完）</Tag>}
              </Descriptions.Item>
              {genReceipt.voucher_number && (
                <Descriptions.Item label="凭证号"><span style={{ fontFamily: MONO }}>{genReceipt.voucher_number}</span></Descriptions.Item>
              )}
              {genReceipt.voucher_status && (
                <Descriptions.Item label="凭证状态"><Tag>{statusLabel(genReceipt.voucher_status)}</Tag></Descriptions.Item>
              )}
              {genReceipt.lines != null && (
                <Descriptions.Item label="分录行数">{genReceipt.lines}</Descriptions.Item>
              )}
              {(genReceipt.total_debit != null || genReceipt.total_credit != null) && (
                <Descriptions.Item label="借 / 贷合计">
                  <span style={{ fontFamily: MONO }}>{fmtMoney(genReceipt.total_debit)} / {fmtMoney(genReceipt.total_credit)}</span>
                </Descriptions.Item>
              )}
              {genReceipt.per_period_amount != null && (
                <Descriptions.Item label="本期摊销额"><span style={{ fontFamily: MONO }}>{fmtMoney(genReceipt.per_period_amount)}</span></Descriptions.Item>
              )}
              {genReceipt.amort_periods != null && (
                <Descriptions.Item label="摊销进度">
                  <Tag color="purple">{genReceipt.amortized_periods ?? 0} / {genReceipt.amort_periods} 期</Tag>
                </Descriptions.Item>
              )}
              <Descriptions.Item label="说明">{genReceipt.message}</Descriptions.Item>
            </Descriptions>
            {genReceipt.created && genReceipt.voucher_id && (
              <Button type="primary" style={{ marginTop: 8 }} block
                onClick={() => {
                  setGenOpen(false);
                  navigate(`/finance/voucher?id=${genReceipt.voucher_id}`);
                }}>
                跳转查看草稿凭证 →
              </Button>
            )}
          </Card>
        )}
      </Modal>
    </div>
  );
}

function Field({ label, children }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
      <span style={{ fontSize: 11, color: '#777169' }}>{label}</span>
      {children}
    </div>
  );
}
