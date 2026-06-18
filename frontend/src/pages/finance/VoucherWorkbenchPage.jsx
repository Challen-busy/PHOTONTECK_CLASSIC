/**
 * VoucherWorkbenchPage —— 凭证批量工作台（金蝶式批量审核/复核/过账 + 凭证整理，finance-gl wave-4，owns by 前端A·凭证工作台 PM）
 *
 * 金蝶「凭证管理」批量工作台：把散在凭证录入屏（VoucherEntryPage）里的逐张审核/复核/过账，提到批量层。
 *   顶部 tabs 分篮（待审核 DRAFT / 待复核 AUDITED且资金类 / 待过账 AUDITED|REVIEWED / 全部）→ 行多选 →
 *   批量审核 / 批量复核 / 批量过账（一张失败不阻断其余，回执弹窗逐条原因）。单行：查看下钻 / 红冲。
 *   「凭证整理」：先 check_voucher_gaps 看断号 → renumber(dry_run 预览映射 → 确认实写) 重排未过账凭证号。
 *
 * 写入路径（守唯一写入：execute_command 调度，前端只触发，不伪造库）：
 *   · 批量过状态机：command finance.batch_voucher_transition（payload {voucher_ids,to_state}）
 *   · 模式凭证生成：command finance.create_voucher_from_model
 *   · 断号检测：command finance.check_voucher_gaps（只读，不写库）
 *   · 重排凭证号：command finance.renumber_vouchers（dry_run 预览 / false 实写，仅未过账）
 *   · 红冲：command finance.red_reversal（单张，POSTED 才可，红字反向）
 *   命令统一经 execCommand() → POST /api/commands/execute（见文件尾，后端命令均 @register_command 已注册，
 *   若该通用命令端点未开通则 404，本页 catch 后如实提示「待后端 ➕ 命令触发端点」，不伪造成功）。
 *
 * 数据源：通用 /api/query(voucher) 带 status/period/word/created_by 筛选；凭证字 /api/query(voucher_word)；
 *   制单人下拉 /api/query(user_account)；会计期间 GET /api/reports/periods（均后端 _company_filter 隔离）。
 *
 * 资金类（待复核）判定：无独立 is_cash 标记 —— 以凭证字 收/付（code 含 收|付 或 restrict_multi_dc=true）近似，
 *   AUDITED 且资金字 → 待出纳复核。非资金字 AUDITED 直接进待过账。判定仅前端分篮，最终放行以后端状态机为准。
 *
 * ★ 共享文件铁律：本页不改 App.jsx/Layout.jsx/api.js。路由/导航label/api方法签名经 routesToWire 交主 agent 接。
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  App, Card, Button, Space, Table, Tag, Tabs, Select, Input, Modal, Alert, Empty, Descriptions, Tooltip, Badge,
} from 'antd';
import {
  ReloadOutlined, CheckOutlined, SafetyCertificateOutlined, AuditOutlined, EyeOutlined,
  RollbackOutlined, NumberOutlined, WarningOutlined,
} from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../../auth';
import api, { query, getAccountingPeriods } from '../../api';
import { MONO, fmtMoney } from './financeHelpers';

// 凭证状态中文标签 + 配色（对齐 VoucherEntryPage.STATUS_META 口径）。
const STATUS_META = {
  DRAFT: { label: '草稿', color: 'default' },
  AUDITED: { label: '已审核', color: 'blue' },
  REVIEWED: { label: '出纳已复核', color: 'cyan' },
  POSTED: { label: '已过账', color: 'green' },
};
const statusTag = (s) => {
  const m = STATUS_META[s] || { label: s || '—', color: 'default' };
  return <Tag color={m.color}>{m.label}</Tag>;
};

// 资金类凭证字判定（收/付 字 → 需出纳复核）。无独立标记，以凭证字近似。
const isCashWord = (w) => !!w && (/[收付]/.test(w.code || '') || w.restrict_multi_dc === true);

// tab 定义：key + 标题 + 命中状态集 + 批量动作目标态 + 动作按钮文案。
const TABS = [
  { key: 'audit', label: '待审核', statuses: ['DRAFT'], action: 'AUDITED', actionLabel: '批量审核', cashOnly: false },
  { key: 'review', label: '待复核', statuses: ['AUDITED'], action: 'REVIEWED', actionLabel: '批量复核', cashOnly: true },
  { key: 'post', label: '待过账', statuses: ['AUDITED', 'REVIEWED'], action: 'POSTED', actionLabel: '批量过账', cashOnly: false },
  { key: 'all', label: '全部', statuses: null, action: null, actionLabel: null, cashOnly: false },
];

const money = (v) => {
  const n = Number(v);
  if (!n) return <span style={{ color: '#d9d4cd' }}>—</span>;
  return <span style={{ fontFamily: MONO }}>{fmtMoney(v)}</span>;
};

export default function VoucherWorkbenchPage() {
  const { user } = useAuth();
  const { message, modal } = App.useApp();
  const navigate = useNavigate();

  const [tab, setTab] = useState('audit');
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);

  // 筛选条
  const [periods, setPeriods] = useState([]);
  const [vwords, setVwords] = useState([]);
  const [users, setUsers] = useState([]);
  const [filterPeriod, setFilterPeriod] = useState(null);
  const [filterWord, setFilterWord] = useState(null);
  const [filterCreator, setFilterCreator] = useState(null);
  const [kw, setKw] = useState('');

  // 多选
  const [selectedKeys, setSelectedKeys] = useState([]);

  // 回执弹窗
  const [resultModal, setResultModal] = useState({ open: false, title: '', summary: null, rows: [] });

  // 凭证整理弹窗
  const [tidyOpen, setTidyOpen] = useState(false);

  const vwordById = useMemo(() => new Map(vwords.map((w) => [w.id, w])), [vwords]);
  const userById = useMemo(() => new Map(users.map((u) => [u.id, u])), [users]);

  // 主数据（期间 / 凭证字 / 用户）一次性载入。
  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const [{ data: pd }, { data: vw }, { data: ud }] = await Promise.all([
          getAccountingPeriods(),
          query('voucher_word', { order_by: 'id', limit: 100 }),
          query('user_account', { order_by: 'id', limit: 500 }),
        ]);
        if (!alive) return;
        setPeriods(pd?.periods || []);
        setVwords(vw?.data || []);
        setUsers(ud?.data || []);
      } catch (e) {
        if (alive) message.warning('筛选主数据加载失败（期间/凭证字/制单人）：' + (e.response?.data?.detail || e.message));
      }
    })();
    return () => { alive = false; };
  }, [message]);

  const activeTab = useMemo(() => TABS.find((t) => t.key === tab) || TABS[0], [tab]);

  // 载入当前 tab 的凭证（status 筛选交后端，资金类/关键字客户端再筛）。
  const load = useCallback(async () => {
    setLoading(true);
    setSelectedKeys([]);
    try {
      const filters = {};
      if (filterPeriod) filters.period_id = filterPeriod;
      if (filterWord) filters.voucher_word_id = filterWord;
      if (filterCreator) filters.created_by_id = filterCreator;
      // 单状态走 filters.status（通用 query 等值过滤）；多状态/全部取回后客户端筛。
      const t = TABS.find((x) => x.key === tab) || TABS[0];
      const singleStatus = t.statuses && t.statuses.length === 1 ? t.statuses[0] : null;
      if (singleStatus) filters.status = singleStatus;
      const { data } = await query('voucher', { filters, order_by: '-id', limit: 500 });
      let list = data?.data || [];
      // 多状态 tab：客户端按状态集过滤。
      if (t.statuses && t.statuses.length > 1) {
        const set = new Set(t.statuses);
        list = list.filter((v) => set.has(v.status));
      }
      // 待复核：仅资金类凭证字（收/付）。
      if (t.cashOnly) {
        list = list.filter((v) => isCashWord(vwordById.get(v.voucher_word_id)));
      }
      setRows(list);
    } catch (e) {
      message.error('凭证列表加载失败：' + (e.response?.data?.detail || e.message));
      setRows([]);
    } finally { setLoading(false); }
  }, [tab, filterPeriod, filterWord, filterCreator, message, vwordById]);

  useEffect(() => { load(); }, [load]);

  const filtered = useMemo(() => {
    const q = kw.trim().toLowerCase();
    if (!q) return rows;
    return rows.filter((r) =>
      String(r.voucher_number || '').toLowerCase().includes(q)
      || String(r.description || '').toLowerCase().includes(q));
  }, [rows, kw]);

  const selectedRows = useMemo(
    () => filtered.filter((r) => selectedKeys.includes(r.id)),
    [filtered, selectedKeys],
  );

  // === 批量过状态机 ===
  const runBatch = useCallback(async () => {
    if (!activeTab.action) return;
    if (!selectedKeys.length) { message.warning('请先勾选凭证'); return; }
    // 职责分离前置提示（SoD 在 POSTED 闸生效；批量操作人需≠制单人）。后端最终判定，前端仅提示。
    const selfCreated = selectedRows.filter((r) => r.created_by_id === user?.id);
    let sodNote = '';
    if (activeTab.action === 'POSTED' && selfCreated.length) {
      sodNote = `其中 ${selfCreated.length} 张为本人制单 —— 职责分离：审核/过账人不能为制单人，这些行可能被后端拒绝。`;
    }
    modal.confirm({
      title: `${activeTab.actionLabel}（${selectedKeys.length} 张）`,
      width: 460,
      content: (
        <div>
          <div>将对所选 {selectedKeys.length} 张凭证执行「{activeTab.actionLabel}」（目标状态 {STATUS_META[activeTab.action]?.label}）。</div>
          <div style={{ marginTop: 6, color: '#777169', fontSize: 12 }}>一张失败不阻断其余，回执将逐条列出结果。</div>
          {sodNote && <Alert style={{ marginTop: 10 }} type="warning" showIcon message={sodNote} />}
        </div>
      ),
      okText: activeTab.actionLabel,
      onOk: async () => {
        setBusy(true);
        try {
          const res = await execCommand('finance.batch_voucher_transition', {
            voucher_ids: [...selectedKeys],
            to_state: activeTab.action,
          });
          // 整批命令本身 success=false（payload 校验失败）→ 直接报错。
          if (res?.success === false) {
            message.error('批量操作未执行：' + (res.error || res.detail || '未知错误'));
            return;
          }
          openResult(`${activeTab.actionLabel}回执`, res);
          await load();
        } catch (e) {
          cmdErr(e, activeTab.actionLabel, message);
        } finally { setBusy(false); }
      },
    });
  }, [activeTab, selectedKeys, selectedRows, user, modal, message, load]);

  // 回执弹窗（成功 N / 失败 M + 逐条原因）。
  const openResult = (title, res) => {
    const results = res?.results || [];
    setResultModal({
      open: true,
      title,
      summary: { total: res?.total ?? results.length, succeeded: res?.succeeded ?? 0, failed: res?.failed ?? 0 },
      rows: results,
    });
  };

  // === 单行红冲 ===
  const redReversal = useCallback((row) => {
    if (row.status !== 'POSTED') { message.warning('仅已过账(POSTED)凭证可红冲'); return; }
    if (row.is_reversed) { message.warning('该凭证已被红冲，不可重复'); return; }
    modal.confirm({
      title: `红冲（红字反向）· ${row.voucher_number || `#${row.id}`}`,
      content: '将生成一张红字反向凭证冲销本凭证（金额取负），原单标记已红冲。确认红冲？',
      okText: '红冲', okButtonProps: { danger: true },
      onOk: async () => {
        setBusy(true);
        try {
          const res = await execCommand('finance.red_reversal', { voucher_id: row.id });
          if (res?.success === false) { message.error('红冲失败：' + (res.error || res.detail)); return; }
          message.success(`已红冲，红字凭证 #${res?.reversal_voucher_id ?? res?.voucher_id ?? '已生成'}`);
          await load();
        } catch (e) {
          cmdErr(e, '红冲', message);
        } finally { setBusy(false); }
      },
    });
  }, [modal, message, load]);

  const goVoucher = (id) => navigate(`/finance/voucher?id=${id}`);

  // 行可选规则：批量动作 tab 才允许勾选命中目标状态集的行（全部 tab 不批量）。
  const rowSelection = activeTab.action ? {
    selectedRowKeys: selectedKeys,
    onChange: setSelectedKeys,
    getCheckboxProps: (r) => ({ disabled: !(activeTab.statuses || []).includes(r.status) }),
  } : undefined;

  const columns = [
    { title: '凭证号', dataIndex: 'voucher_number', width: 130, fixed: 'left', render: (v) => v ? <span style={{ fontFamily: MONO }}>{v}</span> : <span style={{ color: '#bfbbb5' }}>—</span> },
    { title: '日期', dataIndex: 'voucher_date', width: 110 },
    {
      title: '凭证字', dataIndex: 'voucher_word_id', width: 86,
      render: (v) => { const w = vwordById.get(v); return w ? <Tag>{w.code}</Tag> : <span style={{ color: '#bfbbb5' }}>—</span>; },
    },
    { title: '摘要', dataIndex: 'description', width: 220, render: (v) => v || <span style={{ color: '#bfbbb5' }}>—</span> },
    { title: '借方合计', dataIndex: 'total_debit', width: 130, align: 'right', render: money },
    { title: '贷方合计', dataIndex: 'total_credit', width: 130, align: 'right', render: money },
    {
      title: '制单人', dataIndex: 'created_by_id', width: 110,
      render: (v) => { const u = userById.get(v); return u ? (u.full_name || u.username) : (v ? `#${v}` : '—'); },
    },
    { title: '状态', dataIndex: 'status', width: 100, render: statusTag },
    {
      title: '操作', dataIndex: '_a', width: 140, fixed: 'right',
      render: (_, r) => (
        <Space size={2}>
          <Button type="link" size="small" icon={<EyeOutlined />} onClick={() => goVoucher(r.id)}>查看</Button>
          <Tooltip title={r.status === 'POSTED' ? (r.is_reversed ? '已红冲' : '红字反向') : '仅已过账可红冲'}>
            <Button type="link" size="small" danger icon={<RollbackOutlined />}
              disabled={r.status !== 'POSTED' || r.is_reversed}
              onClick={() => redReversal(r)}>红冲</Button>
          </Tooltip>
        </Space>
      ),
    },
  ];

  // tab 角标统计（命中目标状态集行数，全部 tab 不显）。
  const tabItems = TABS.map((t) => ({
    key: t.key,
    label: t.key === tab && t.statuses
      ? <Badge color="#1f5aa8" count={filtered.length} offset={[10, -2]} size="small">{t.label}</Badge>
      : t.label,
  }));

  return (
    <div>
      <div style={{ marginBottom: 16, display: 'flex', alignItems: 'baseline', gap: 12, flexWrap: 'wrap' }}>
        <h2 style={{ fontSize: 26, fontWeight: 300, letterSpacing: '-0.01em', color: '#000', margin: 0, lineHeight: 1.2 }}>
          凭证工作台
        </h2>
        <span style={{ color: '#777169', fontSize: 13 }}>
          财务 / 总账 · 批量审核 / 复核 / 过账 + 凭证整理（断号 / 重排）· 账簿 = {user?.company_name || `公司 #${user?.company_id ?? ''}`}
        </span>
      </div>

      <Card size="small" style={{ borderRadius: 14, marginBottom: 14 }}>
        <Tabs activeKey={tab} onChange={setTab} items={tabItems} style={{ marginBottom: 4 }} />

        {/* 筛选条 + 批量按钮 */}
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'center' }}>
          <Select allowClear placeholder="会计期间" value={filterPeriod} onChange={setFilterPeriod} style={{ width: 170 }}
            options={periods.map((p) => ({ value: p.id, label: `${p.label}${p.status !== 'OPEN' ? `（${p.status}）` : ''}` }))} />
          <Select allowClear placeholder="凭证字" value={filterWord} onChange={setFilterWord} style={{ width: 120 }}
            options={vwords.map((w) => ({ value: w.id, label: `${w.code} ${w.name}` }))} />
          <Select allowClear showSearch optionFilterProp="label" placeholder="制单人" value={filterCreator} onChange={setFilterCreator} style={{ width: 160 }}
            options={users.map((u) => ({ value: u.id, label: u.full_name || u.username }))} />
          <Input.Search allowClear placeholder="凭证号 / 摘要" value={kw} onChange={(e) => setKw(e.target.value)} style={{ width: 200 }} />
          <Button icon={<ReloadOutlined />} loading={loading} onClick={load}>刷新</Button>

          <div style={{ flex: 1 }} />

          {activeTab.action && (
            <Button type="primary" loading={busy} disabled={!selectedKeys.length}
              icon={activeTab.key === 'audit' ? <CheckOutlined /> : activeTab.key === 'review' ? <SafetyCertificateOutlined /> : <AuditOutlined />}
              onClick={runBatch}>
              {activeTab.actionLabel}{selectedKeys.length ? `（${selectedKeys.length}）` : ''}
            </Button>
          )}
          <Button icon={<NumberOutlined />} onClick={() => setTidyOpen(true)}>凭证整理</Button>
        </div>
      </Card>

      <Card size="small" style={{ borderRadius: 14 }} styles={{ body: { padding: 0 } }}>
        {!loading && !filtered.length ? (
          <Empty style={{ padding: 40 }} description={`暂无${activeTab.label}凭证`} />
        ) : (
          <Table
            size="small"
            rowKey="id"
            loading={loading}
            dataSource={filtered}
            columns={columns}
            rowSelection={rowSelection}
            pagination={{ pageSize: 30, showSizeChanger: true, showTotal: (t) => `共 ${t} 张` }}
            scroll={{ x: 'max-content', y: 'calc(100vh - 380px)' }}
            sticky
          />
        )}
      </Card>

      {/* 批量回执弹窗 */}
      <Modal
        open={resultModal.open}
        title={resultModal.title}
        width={680}
        footer={<Button type="primary" onClick={() => setResultModal((s) => ({ ...s, open: false }))}>关闭</Button>}
        onCancel={() => setResultModal((s) => ({ ...s, open: false }))}
      >
        {resultModal.summary && (
          <Space size={16} style={{ marginBottom: 12 }}>
            <Tag>共 {resultModal.summary.total}</Tag>
            <Tag color="green">成功 {resultModal.summary.succeeded}</Tag>
            <Tag color={resultModal.summary.failed ? 'red' : 'default'}>失败 {resultModal.summary.failed}</Tag>
          </Space>
        )}
        <Table
          size="small"
          rowKey="id"
          dataSource={resultModal.rows}
          pagination={false}
          scroll={{ y: 320 }}
          columns={[
            { title: '凭证 id', dataIndex: 'id', width: 80, render: (v) => <span style={{ fontFamily: MONO }}>#{v}</span> },
            {
              title: '结果', dataIndex: 'success', width: 90,
              render: (v) => v ? <Tag color="green">成功</Tag> : <Tag color="red">失败</Tag>,
            },
            {
              title: '状态变化', dataIndex: '_s', width: 150,
              render: (_, r) => r.success ? <span>{STATUS_META[r.from_state]?.label || r.from_state || '—'} → {STATUS_META[r.to_state]?.label || r.to_state || '—'}</span> : <span style={{ color: '#bfbbb5' }}>—</span>,
            },
            { title: '失败原因', dataIndex: 'error', render: (v) => v ? <span style={{ color: '#cf1322' }}>{v}</span> : <span style={{ color: '#bfbbb5' }}>—</span> },
          ]}
        />
      </Modal>

      <TidyModal
        open={tidyOpen}
        onClose={() => setTidyOpen(false)}
        periods={periods}
        companyId={user?.company_id}
        onDone={load}
      />
    </div>
  );
}

/**
 * 凭证整理弹窗：断号检测（check_voucher_gaps，只读）+ 重排（renumber dry_run 预览 → 确认实写）。
 * 选公司期间 → 检测 → 展示断号/分组 → 预览重排映射 → 确认实写。
 */
function TidyModal({ open, onClose, periods, companyId, onDone }) {
  const { message, modal } = App.useApp();
  const [periodId, setPeriodId] = useState(null);
  const [checking, setChecking] = useState(false);
  const [gapResult, setGapResult] = useState(null);
  const [previewing, setPreviewing] = useState(false);
  const [mapping, setMapping] = useState(null); // {changed, mapping[], skipped_posted, dry_run}

  // 打开时重置。
  useEffect(() => {
    if (open) { setGapResult(null); setMapping(null); }
  }, [open]);

  const runCheck = async () => {
    if (!companyId) { message.warning('当前会话无公司上下文'); return; }
    if (!periodId) { message.warning('请选择会计期间'); return; }
    setChecking(true); setMapping(null);
    try {
      const res = await execCommand('finance.check_voucher_gaps', { company_id: companyId, period_id: periodId });
      if (res?.success === false) { message.error('断号检测失败：' + (res.error || res.detail)); return; }
      setGapResult(res);
    } catch (e) {
      cmdErr(e, '断号检测', message);
    } finally { setChecking(false); }
  };

  const runPreview = async () => {
    if (!periodId) { message.warning('请选择会计期间'); return; }
    setPreviewing(true);
    try {
      const res = await execCommand('finance.renumber_vouchers', { company_id: companyId, period_id: periodId, dry_run: true });
      if (res?.success === false) { message.error('重排预览失败：' + (res.error || res.detail)); return; }
      setMapping(res);
      if (!res?.changed) message.info('无需重排（凭证号已连续 / 无可重排的未过账凭证）');
    } catch (e) {
      cmdErr(e, '重排预览', message);
    } finally { setPreviewing(false); }
  };

  const runApply = () => {
    if (!mapping || !mapping.changed) return;
    modal.confirm({
      title: `确认重排 ${mapping.changed} 张凭证号？`,
      content: `仅未过账凭证重排，已过账保号占位（跳过 ${mapping.skipped_posted ?? 0} 张）。此操作将实写凭证号，不可一键撤销。`,
      okText: '确认重排', okButtonProps: { danger: true },
      onOk: async () => {
        try {
          const res = await execCommand('finance.renumber_vouchers', { company_id: companyId, period_id: periodId, dry_run: false });
          if (res?.success === false) { message.error('重排失败：' + (res.error || res.detail)); return; }
          message.success(`已重排 ${res?.changed ?? mapping.changed} 张凭证号`);
          setMapping(null);
          await runCheck();
          onDone?.();
        } catch (e) {
          cmdErr(e, '重排实写', message);
        }
      },
    });
  };

  const gaps = gapResult?.gaps || [];
  const groups = gapResult?.groups || [];
  const unparsable = gapResult?.unparsable || [];

  return (
    <Modal
      open={open}
      onCancel={onClose}
      title="凭证整理 · 断号检测 / 重排"
      width={720}
      footer={<Button onClick={onClose}>关闭</Button>}
    >
      <Space style={{ marginBottom: 12 }}>
        <Select placeholder="会计期间" value={periodId} onChange={(v) => { setPeriodId(v); setGapResult(null); setMapping(null); }} style={{ width: 200 }}
          options={periods.map((p) => ({ value: p.id, label: `${p.label}${p.status !== 'OPEN' ? `（${p.status}）` : ''}` }))} />
        <Button type="primary" icon={<WarningOutlined />} loading={checking} onClick={runCheck}>检测断号</Button>
        <Button icon={<NumberOutlined />} loading={previewing} disabled={!gapResult} onClick={runPreview}>预览重排</Button>
      </Space>

      {gapResult && (
        <>
          <Descriptions size="small" column={2} style={{ marginBottom: 10 }} styles={{ label: { color: '#777169' } }}>
            <Descriptions.Item label="该期间凭证总数">{gapResult.total}</Descriptions.Item>
            <Descriptions.Item label="断号数">{gaps.length}</Descriptions.Item>
          </Descriptions>

          {gaps.length === 0 ? (
            <Alert type="success" showIcon style={{ borderRadius: 10 }} message="无断号，凭证号连续。" />
          ) : (
            <Alert type="warning" showIcon style={{ borderRadius: 10, marginBottom: 10 }}
              message={`检测到 ${gaps.length} 个断号`}
              description={
                <Space wrap size={6} style={{ marginTop: 4 }}>
                  {gaps.slice(0, 60).map((g, i) => <Tag key={i} color="orange" style={{ fontFamily: MONO }}>{g.missing_number}</Tag>)}
                  {gaps.length > 60 && <span style={{ color: '#777169' }}>…等 {gaps.length} 个</span>}
                </Space>
              } />
          )}

          {groups.length > 0 && (
            <Table
              size="small" rowKey={(r) => r.prefix} pagination={false} style={{ marginBottom: 10 }}
              dataSource={groups}
              columns={[
                { title: '前缀', dataIndex: 'prefix', render: (v) => <span style={{ fontFamily: MONO }}>{v}</span> },
                { title: '起', dataIndex: 'min_seq', width: 70 },
                { title: '止', dataIndex: 'max_seq', width: 70 },
                { title: '张数', dataIndex: 'count', width: 70 },
                { title: '断号数', dataIndex: 'missing_count', width: 80, render: (v) => v ? <Tag color="orange">{v}</Tag> : v },
              ]}
            />
          )}

          {unparsable.length > 0 && (
            <Alert type="info" showIcon style={{ borderRadius: 10, marginBottom: 10 }}
              message={`${unparsable.length} 个号无数字尾段，未参与连号比对`}
              description={<Space wrap size={6}>{unparsable.slice(0, 30).map((n, i) => <Tag key={i}>{n}</Tag>)}</Space>} />
          )}
        </>
      )}

      {mapping && mapping.changed > 0 && (
        <>
          <Alert type="warning" showIcon style={{ borderRadius: 10, margin: '10px 0' }}
            message={`重排预览：将变更 ${mapping.changed} 张凭证号（跳过已过账 ${mapping.skipped_posted ?? 0} 张）`}
            description="确认后实写（dry_run=false）。仅未过账凭证重排。" />
          <Table
            size="small" rowKey="id" pagination={{ pageSize: 8 }}
            dataSource={mapping.mapping || []}
            columns={[
              { title: '凭证 id', dataIndex: 'id', width: 90, render: (v) => <span style={{ fontFamily: MONO }}>#{v}</span> },
              { title: '原号', dataIndex: 'old_number', render: (v) => <span style={{ fontFamily: MONO, color: '#cf1322' }}>{v}</span> },
              { title: '新号', dataIndex: 'new_number', render: (v) => <span style={{ fontFamily: MONO, color: '#389e0d' }}>{v}</span> },
            ]}
          />
          <div style={{ textAlign: 'right', marginTop: 12 }}>
            <Button type="primary" danger onClick={runApply}>确认重排（实写）</Button>
          </div>
        </>
      )}
    </Modal>
  );
}

// === 命令统一触发：POST /api/commands/execute（后端命令均 @register_command 已注册）===
// 守唯一写入路径：前端只触发命令、不直接写库。命令端点若未开通（404）由调用方 catch 后如实降级提示。
async function execCommand(command, payload, idempotencyKey) {
  const body = { command, payload };
  if (idempotencyKey) body.idempotency_key = idempotencyKey;
  const { data } = await api.post('/commands/execute', body);
  return data;
}

function cmdErr(e, label, message) {
  const status = e?.response?.status;
  const detail = e?.response?.data?.detail || e?.response?.data?.error || e?.message;
  if (status === 404) {
    message.warning(`${label}：通用命令触发端点 /api/commands/execute 待后端 ➕（后端命令已 @register_command 注册，仅缺 HTTP 路由）。未伪造成功。`);
  } else {
    message.error(`${label}失败：${detail}`);
  }
}
