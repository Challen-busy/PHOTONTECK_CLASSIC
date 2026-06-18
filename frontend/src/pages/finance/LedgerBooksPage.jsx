/**
 * LedgerBooksPage —— 账簿查询页（finance-gl wave-5，owns by 前端B·账簿补全 PM）
 *
 * 补齐金蝶账簿账表（与 wave-1 LedgerReportPage「科目余额表 + 明细下钻」并列，互不替代）：
 *   ┌ tab 明细分类账：/api/reports/detail_ledger —— 逐科目列分录流水（日期/凭证字号/摘要/借/贷/方向/滚动余额），可下钻凭证。
 *   ├ tab 总分类账：  /api/reports/general_ledger —— 各科目 年初/本期发生/本年累计/期末。
 *   ├ tab 试算平衡表：/api/reports/trial_balance —— 全科目 期初/本期/期末 借贷 + 三栏平衡校验。
 *   └ tab 核算维度余额表：/api/reports/aux-balance —— 选维度 → 该维度各值的科目余额（本期/本年累计借贷净额）。
 *
 * 口径：四表均「已过账」口径（数据源 AccountBalance / 已过账 VoucherEntry）；明细账提供「含未过账」开关（后端 include_unposted）。
 * 公司隔离：detail/general/trial 由后端 _company_filter 按会话公司兜底；aux-balance 必传 company_id（取 user.company_id）+ dimension_id。
 * 下钻凭证：明细账行带 voucher_id → navigate('/finance/voucher?id={id}')（与 VoucherQueryPage 一致契约）。
 *
 * ★禁碰 App.jsx / components/Layout.jsx / api.js（共享文件，竞态）—— 路由 / 导航 label / api 方法签名全部走 routesToWire 交主 agent 统一接。
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  App, Card, Select, Input, Button, Space, Table, Tag, Tabs, Segmented, Alert, Empty, Result,
} from 'antd';
import { SearchOutlined } from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../../auth';
import {
  getAccountingPeriods, getDetailLedger, getGeneralLedger, getTrialBalance, getAuxBalance, query,
} from '../../api';
import { MONO, fmtMoney, ACCOUNT_TYPE_LABEL } from './financeHelpers';

const SOURCE_TYPE_LABEL = {
  CUSTOMER: '客户', SUPPLIER: '供应商', EMPLOYEE: '职员', DEPT: '部门', PROJECT: '项目',
};

// 金额格（0/空给破折号占位，否则 MONO 右对齐千分位）。
function money(v) {
  const n = Number(v);
  if (!n) return <span style={{ color: '#d9d4cd' }}>—</span>;
  return <span style={{ fontFamily: MONO }}>{fmtMoney(v)}</span>;
}
function netCell(v) {
  return <span style={{ fontFamily: MONO, fontWeight: 600 }}>{fmtMoney(v)}</span>;
}
function Col({ label, children }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
      <span style={{ fontSize: 11, color: '#777169' }}>{label}</span>
      {children}
    </div>
  );
}

export default function LedgerBooksPage() {
  const { user } = useAuth();
  const { message } = App.useApp();
  const navigate = useNavigate();

  const [periods, setPeriods] = useState([]);
  const [periodId, setPeriodId] = useState(null);
  const [activeTab, setActiveTab] = useState('detail');

  useEffect(() => {
    getAccountingPeriods()
      .then(({ data }) => {
        const ps = data?.periods || [];
        setPeriods(ps);
        const open = ps.find((p) => p.status === 'OPEN') || ps[0];
        if (open) setPeriodId(open.id);
      })
      .catch((e) => message.error('期间加载失败：' + (e.response?.data?.detail || e.message)));
  }, [message]);

  const periodOptions = periods.map((p) => ({
    value: p.id,
    label: `${p.label}${p.status !== 'OPEN' ? `（${p.status}）` : ''}`,
  }));

  const drillVoucher = useCallback((voucherId) => {
    if (voucherId) navigate(`/finance/voucher?id=${voucherId}`);
  }, [navigate]);

  return (
    <div>
      <div style={{ marginBottom: 16, display: 'flex', alignItems: 'baseline', gap: 12, flexWrap: 'wrap' }}>
        <h2 style={{ fontSize: 26, fontWeight: 300, letterSpacing: '-0.01em', color: '#000', margin: 0, lineHeight: 1.2 }}>
          账簿查询
        </h2>
        <span style={{ color: '#777169', fontSize: 13 }}>
          财务 / 总账 · 明细分类账 / 总分类账 / 试算平衡表 / 核算维度余额表 · 已过账口径 · 账簿 = 当前公司（后端按会话隔离）
        </span>
      </div>

      {/* 统一筛选条：公司 + 期间 */}
      <Card size="small" style={{ borderRadius: 14, marginBottom: 14 }}>
        <Space wrap size={16} align="end">
          <Col label="账簿 / 核算组织">
            <Tag color="geekblue">{user?.company_name || `公司 #${user?.company_id ?? ''}`}</Tag>
          </Col>
          <Col label="会计期间">
            <Select size="small" value={periodId} style={{ width: 200 }} onChange={setPeriodId}
              options={periodOptions} placeholder="选择期间" />
          </Col>
        </Space>
      </Card>

      <Card size="small" style={{ borderRadius: 14 }} styles={{ body: { paddingTop: 8 } }}>
        <Tabs
          activeKey={activeTab}
          onChange={setActiveTab}
          items={[
            { key: 'detail', label: '明细分类账', children: <DetailLedgerTab periodId={periodId} onDrill={drillVoucher} /> },
            { key: 'general', label: '总分类账', children: <GeneralLedgerTab periodId={periodId} /> },
            { key: 'trial', label: '试算平衡表', children: <TrialBalanceTab periodId={periodId} /> },
            { key: 'aux', label: '核算维度余额表', children: <AuxBalanceTab periodId={periodId} companyId={user?.company_id} /> },
          ]}
        />
      </Card>
    </div>
  );
}

/* ============================== tab 1：明细分类账 ============================== */
function DetailLedgerTab({ periodId, onDrill }) {
  const { message } = App.useApp();
  const [codeFrom, setCodeFrom] = useState('');
  const [codeTo, setCodeTo] = useState('');
  const [scope, setScope] = useState('posted'); // posted | with_unposted
  const [accounts, setAccounts] = useState([]);
  const [loading, setLoading] = useState(false);
  const [loaded, setLoaded] = useState(false);

  const run = useCallback(async () => {
    if (!periodId) { message.warning('请选择会计期间'); return; }
    setLoading(true);
    try {
      const params = { period_id: periodId, include_unposted: scope === 'with_unposted' };
      if (codeFrom.trim()) params.account_code_from = codeFrom.trim();
      if (codeTo.trim()) params.account_code_to = codeTo.trim();
      const { data } = await getDetailLedger(params);
      setAccounts(data?.accounts || []);
      setLoaded(true);
    } catch (e) {
      message.error('明细分类账查询失败：' + (e.response?.data?.detail || e.message));
      setAccounts([]);
    } finally { setLoading(false); }
  }, [periodId, codeFrom, codeTo, scope, message]);

  const lineColumns = [
    { title: '凭证日期', dataIndex: 'voucher_date', width: 110 },
    { title: '凭证字号', dataIndex: 'voucher_label', width: 120, render: (v) => <span style={{ fontFamily: MONO }}>{v}</span> },
    { title: '摘要', dataIndex: 'description', width: 220, render: (v) => v || <span style={{ color: '#bfbbb5' }}>—</span> },
    { title: '借方', dataIndex: 'debit', width: 130, align: 'right', render: money },
    { title: '贷方', dataIndex: 'credit', width: 130, align: 'right', render: money },
    {
      title: '方向', dataIndex: 'direction_label', width: 56,
      render: (v) => <Tag color={v === '借' ? 'blue' : 'gold'}>{v}</Tag>,
    },
    { title: '余额', dataIndex: 'running_balance', width: 130, align: 'right', render: netCell },
    {
      title: '凭证状态', dataIndex: 'voucher_status', width: 88,
      render: (v) => <Tag color={v === 'POSTED' ? 'green' : 'default'}>{v}</Tag>,
    },
    {
      title: '操作', dataIndex: '_a', width: 80, fixed: 'right',
      render: (_, row) => <Button type="link" size="small" onClick={() => onDrill(row.voucher_id)}>看凭证</Button>,
    },
  ];

  return (
    <div>
      <Space wrap size={16} align="end" style={{ marginBottom: 12 }}>
        <Col label="科目编码（起）">
          <Input size="small" value={codeFrom} onChange={(e) => setCodeFrom(e.target.value)} placeholder="如 1001" style={{ width: 120, fontFamily: MONO }} />
        </Col>
        <Col label="科目编码（止）">
          <Input size="small" value={codeTo} onChange={(e) => setCodeTo(e.target.value)} placeholder="如 1999" style={{ width: 120, fontFamily: MONO }} />
        </Col>
        <Col label="口径">
          <Segmented size="small" value={scope} onChange={setScope}
            options={[{ label: '仅已过账', value: 'posted' }, { label: '含未过账', value: 'with_unposted' }]} />
        </Col>
        <Button type="primary" size="small" icon={<SearchOutlined />} loading={loading} onClick={run}>查询</Button>
      </Space>

      {scope === 'with_unposted' && (
        <Alert
          style={{ marginBottom: 12, borderRadius: 10 }} type="warning" showIcon
          message="「含未过账」口径"
          description="后端 include_unposted=True 一并列出未过账凭证分录（行内凭证状态非 POSTED）；滚动余额仍按本期间 AccountBalance 期初起算，未过账分录纳入流水但不改变已过账账簿余额口径。"
        />
      )}

      {!loaded ? (
        <Empty style={{ padding: 40 }} description="选择期间与科目区间后点「查询」" />
      ) : accounts.length === 0 ? (
        <Empty style={{ padding: 40 }} description="本期间该科目区间无发生且期初为零（已过账口径）" />
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          {accounts.map((acct) => (
            <Card
              key={acct.account_id}
              size="small"
              styles={{ body: { padding: 0 } }}
              style={{ borderRadius: 12 }}
              title={
                <Space size={10} wrap>
                  <span style={{ fontFamily: MONO, fontWeight: 600 }}>{acct.account_code}</span>
                  <span>{acct.account_name}</span>
                  <Tag color={acct.direction_label === '借' ? 'blue' : 'gold'}>{acct.direction_label}</Tag>
                </Space>
              }
              extra={
                <Space size={16} style={{ fontSize: 12, color: '#777169' }}>
                  <span>期初 <b style={{ fontFamily: MONO, color: '#000' }}>{fmtMoney(acct.opening_balance)}</b></span>
                  <span>本期借 <b style={{ fontFamily: MONO, color: '#000' }}>{fmtMoney(acct.period_debit)}</b></span>
                  <span>本期贷 <b style={{ fontFamily: MONO, color: '#000' }}>{fmtMoney(acct.period_credit)}</b></span>
                  <span>期末 <b style={{ fontFamily: MONO, color: '#000' }}>{fmtMoney(acct.closing_balance)}</b></span>
                </Space>
              }
            >
              <Table
                size="small"
                rowKey={(r) => `${r.voucher_id}-${r.line_number}`}
                dataSource={acct.lines}
                columns={lineColumns}
                pagination={false}
                scroll={{ x: 'max-content' }}
                locale={{ emptyText: '本期间无发生（仅期初余额）' }}
              />
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}

/* ============================== tab 2：总分类账 ============================== */
function GeneralLedgerTab({ periodId }) {
  const { message } = App.useApp();
  const [codeFrom, setCodeFrom] = useState('');
  const [codeTo, setCodeTo] = useState('');
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(false);
  const [loaded, setLoaded] = useState(false);

  const run = useCallback(async () => {
    if (!periodId) { message.warning('请选择会计期间'); return; }
    setLoading(true);
    try {
      const params = { period_id: periodId };
      if (codeFrom.trim()) params.account_code_from = codeFrom.trim();
      if (codeTo.trim()) params.account_code_to = codeTo.trim();
      const { data } = await getGeneralLedger(params);
      setRows(data?.data || []);
      setLoaded(true);
    } catch (e) {
      message.error('总分类账查询失败：' + (e.response?.data?.detail || e.message));
      setRows([]);
    } finally { setLoading(false); }
  }, [periodId, codeFrom, codeTo, message]);

  const totals = useMemo(() => {
    const t = { period_debit: 0, period_credit: 0, ytd_debit: 0, ytd_credit: 0 };
    for (const r of rows) {
      t.period_debit += Number(r.period_debit) || 0;
      t.period_credit += Number(r.period_credit) || 0;
      t.ytd_debit += Number(r.ytd_debit) || 0;
      t.ytd_credit += Number(r.ytd_credit) || 0;
    }
    return t;
  }, [rows]);

  const columns = [
    { title: '科目编码', dataIndex: 'account_code', width: 110, fixed: 'left', render: (v) => <span style={{ fontFamily: MONO }}>{v}</span> },
    { title: '科目名称', dataIndex: 'account_name', width: 170, fixed: 'left' },
    { title: '类别', dataIndex: 'account_type', width: 70, render: (v) => ACCOUNT_TYPE_LABEL[v] || v },
    { title: '方向', dataIndex: 'direction_label', width: 56, render: (v) => <Tag color={v === '借' ? 'blue' : 'gold'}>{v}</Tag> },
    { title: '年初余额', dataIndex: 'year_opening_balance', width: 130, align: 'right', render: netCell },
    { title: '本期借', dataIndex: 'period_debit', width: 120, align: 'right', render: money },
    { title: '本期贷', dataIndex: 'period_credit', width: 120, align: 'right', render: money },
    { title: '本年累计借', dataIndex: 'ytd_debit', width: 130, align: 'right', render: money },
    { title: '本年累计贷', dataIndex: 'ytd_credit', width: 130, align: 'right', render: money },
    { title: '期末余额', dataIndex: 'closing_balance', width: 130, align: 'right', render: netCell },
  ];

  return (
    <div>
      <Space wrap size={16} align="end" style={{ marginBottom: 12 }}>
        <Col label="科目编码（起）">
          <Input size="small" value={codeFrom} onChange={(e) => setCodeFrom(e.target.value)} placeholder="如 1001" style={{ width: 120, fontFamily: MONO }} />
        </Col>
        <Col label="科目编码（止）">
          <Input size="small" value={codeTo} onChange={(e) => setCodeTo(e.target.value)} placeholder="如 1999" style={{ width: 120, fontFamily: MONO }} />
        </Col>
        <Button type="primary" size="small" icon={<SearchOutlined />} loading={loading} onClick={run}>查询</Button>
      </Space>

      {!loaded ? (
        <Empty style={{ padding: 40 }} description="选择期间与科目区间后点「查询」" />
      ) : (
        <Table
          size="small"
          rowKey="account_id"
          loading={loading}
          dataSource={rows}
          columns={columns}
          pagination={{ pageSize: 30, showSizeChanger: true }}
          scroll={{ x: 'max-content', y: 'calc(100vh - 420px)' }}
          sticky
          summary={() => (
            <Table.Summary fixed>
              <Table.Summary.Row style={{ background: 'rgba(245,242,239,0.6)', fontWeight: 600 }}>
                <Table.Summary.Cell index={0} colSpan={5}>合计（{rows.length} 个科目）</Table.Summary.Cell>
                <Table.Summary.Cell index={5} align="right">{fmtMoney(totals.period_debit)}</Table.Summary.Cell>
                <Table.Summary.Cell index={6} align="right">{fmtMoney(totals.period_credit)}</Table.Summary.Cell>
                <Table.Summary.Cell index={7} align="right">{fmtMoney(totals.ytd_debit)}</Table.Summary.Cell>
                <Table.Summary.Cell index={8} align="right">{fmtMoney(totals.ytd_credit)}</Table.Summary.Cell>
                <Table.Summary.Cell index={9} />
              </Table.Summary.Row>
            </Table.Summary>
          )}
        />
      )}
    </div>
  );
}

/* ============================== tab 3：试算平衡表 ============================== */
function TrialBalanceTab({ periodId }) {
  const { message } = App.useApp();
  const [rows, setRows] = useState([]);
  const [totals, setTotals] = useState(null);
  const [checks, setChecks] = useState(null);
  const [allBalanced, setAllBalanced] = useState(null);
  const [loading, setLoading] = useState(false);
  const [loaded, setLoaded] = useState(false);

  const run = useCallback(async () => {
    if (!periodId) { message.warning('请选择会计期间'); return; }
    setLoading(true);
    try {
      const { data } = await getTrialBalance({ period_id: periodId });
      setRows(data?.data || []);
      setTotals(data?.totals || null);
      setChecks(data?.balance_checks || null);
      setAllBalanced(data?.all_balanced ?? null);
      setLoaded(true);
    } catch (e) {
      message.error('试算平衡表查询失败：' + (e.response?.data?.detail || e.message));
      setRows([]); setTotals(null); setChecks(null); setAllBalanced(null);
    } finally { setLoading(false); }
  }, [periodId, message]);

  const columns = [
    { title: '科目编码', dataIndex: 'account_code', width: 110, fixed: 'left', render: (v) => <span style={{ fontFamily: MONO }}>{v}</span> },
    { title: '科目名称', dataIndex: 'account_name', width: 170, fixed: 'left' },
    { title: '类别', dataIndex: 'account_type', width: 70, render: (v) => ACCOUNT_TYPE_LABEL[v] || v },
    { title: '期初借', dataIndex: 'opening_debit', width: 120, align: 'right', render: money },
    { title: '期初贷', dataIndex: 'opening_credit', width: 120, align: 'right', render: money },
    { title: '本期借', dataIndex: 'period_debit', width: 120, align: 'right', render: money },
    { title: '本期贷', dataIndex: 'period_credit', width: 120, align: 'right', render: money },
    { title: '期末借', dataIndex: 'closing_debit', width: 120, align: 'right', render: money },
    { title: '期末贷', dataIndex: 'closing_credit', width: 120, align: 'right', render: money },
  ];

  const checkTag = (label, ok) => (
    <Tag color={ok ? 'green' : 'red'}>{label} {ok ? '平 ✓' : '不平 ✗'}</Tag>
  );

  return (
    <div>
      <Space wrap size={16} align="end" style={{ marginBottom: 12 }}>
        <Button type="primary" size="small" icon={<SearchOutlined />} loading={loading} onClick={run}>查询</Button>
        {loaded && checks && (
          <Space size={8}>
            {checkTag('期初', checks.opening)}
            {checkTag('本期', checks.period)}
            {checkTag('期末', checks.closing)}
            {allBalanced != null && (
              <Tag color={allBalanced ? 'success' : 'error'} style={{ fontWeight: 600 }}>
                {allBalanced ? '三栏全平衡' : '存在不平栏'}
              </Tag>
            )}
          </Space>
        )}
      </Space>

      {loaded && allBalanced === false && (
        <Alert
          style={{ marginBottom: 12, borderRadius: 10 }} type="error" showIcon
          message="试算不平衡"
          description="存在期初 / 本期 / 期末某栏 Σ借 ≠ Σ贷（容差 0.01）。请核对凭证过账与期初建账数据；正常已过账账簿三栏均应平衡。"
        />
      )}

      {!loaded ? (
        <Empty style={{ padding: 40 }} description="选择期间后点「查询」" />
      ) : (
        <Table
          size="small"
          rowKey="account_code"
          loading={loading}
          dataSource={rows}
          columns={columns}
          pagination={{ pageSize: 50, showSizeChanger: true }}
          scroll={{ x: 'max-content', y: 'calc(100vh - 420px)' }}
          sticky
          summary={() => totals && (
            <Table.Summary fixed>
              <Table.Summary.Row style={{ background: 'rgba(245,242,239,0.6)', fontWeight: 600 }}>
                <Table.Summary.Cell index={0} colSpan={3}>合计（{rows.length} 个科目）</Table.Summary.Cell>
                <Table.Summary.Cell index={3} align="right">{fmtMoney(totals.opening_debit)}</Table.Summary.Cell>
                <Table.Summary.Cell index={4} align="right">{fmtMoney(totals.opening_credit)}</Table.Summary.Cell>
                <Table.Summary.Cell index={5} align="right">{fmtMoney(totals.period_debit)}</Table.Summary.Cell>
                <Table.Summary.Cell index={6} align="right">{fmtMoney(totals.period_credit)}</Table.Summary.Cell>
                <Table.Summary.Cell index={7} align="right">{fmtMoney(totals.closing_debit)}</Table.Summary.Cell>
                <Table.Summary.Cell index={8} align="right">{fmtMoney(totals.closing_credit)}</Table.Summary.Cell>
              </Table.Summary.Row>
            </Table.Summary>
          )}
        />
      )}
    </div>
  );
}

/* ============================== tab 4：核算维度余额表 ============================== */
function AuxBalanceTab({ periodId, companyId }) {
  const { message } = App.useApp();
  const [dimensions, setDimensions] = useState([]);
  const [dimensionId, setDimensionId] = useState(null);
  const [result, setResult] = useState(null);
  const [errorMsg, setErrorMsg] = useState('');
  const [loading, setLoading] = useState(false);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    query('auxiliary_dimension', { order_by: 'code', limit: 200 })
      .then(({ data }) => setDimensions(data?.data || []))
      .catch((e) => message.error('维度加载失败：' + (e.response?.data?.detail || e.message)));
  }, [message]);

  const run = useCallback(async () => {
    if (!periodId) { message.warning('请选择会计期间'); return; }
    if (!companyId) { message.warning('当前会话缺少公司，无法查询'); return; }
    if (!dimensionId) { message.warning('请选择核算维度'); return; }
    setLoading(true);
    setErrorMsg('');
    try {
      const { data } = await getAuxBalance({ company_id: companyId, period_id: periodId, dimension_id: dimensionId });
      if (data?.error) {
        setErrorMsg(data.error);
        setResult(null);
      } else {
        setResult(data);
      }
      setLoaded(true);
    } catch (e) {
      message.error('核算维度余额表查询失败：' + (e.response?.data?.detail || e.message));
      setResult(null);
    } finally { setLoading(false); }
  }, [periodId, companyId, dimensionId, message]);

  const acctColumns = [
    { title: '科目编码', dataIndex: 'account_code', width: 110, render: (v) => <span style={{ fontFamily: MONO }}>{v}</span> },
    { title: '科目名称', dataIndex: 'account_name', width: 170 },
    { title: '方向', dataIndex: 'direction_label', width: 56, render: (v) => <Tag color={v === '借' ? 'blue' : 'gold'}>{v}</Tag> },
    { title: '本期借', dataIndex: 'period_debit', width: 120, align: 'right', render: money },
    { title: '本期贷', dataIndex: 'period_credit', width: 120, align: 'right', render: money },
    { title: '本期净额', dataIndex: 'period_net', width: 120, align: 'right', render: netCell },
    { title: '本年累计借', dataIndex: 'ytd_debit', width: 130, align: 'right', render: money },
    { title: '本年累计贷', dataIndex: 'ytd_credit', width: 130, align: 'right', render: money },
    { title: '本年累计净额', dataIndex: 'ytd_net', width: 130, align: 'right', render: netCell },
  ];

  const groups = result?.data || [];

  return (
    <div>
      <Space wrap size={16} align="end" style={{ marginBottom: 12 }}>
        <Col label="核算维度">
          <Select size="small" value={dimensionId} style={{ width: 240 }} onChange={setDimensionId}
            placeholder="选择维度"
            options={dimensions.map((d) => ({
              value: d.id,
              label: `${d.code} ${d.name}（${SOURCE_TYPE_LABEL[d.source_type] || d.source_type}）`,
            }))} />
        </Col>
        <Button type="primary" size="small" icon={<SearchOutlined />} loading={loading} onClick={run}>查询</Button>
        {result?.source_type && (
          <Tag color="purple" style={{ alignSelf: 'center' }}>
            分组轴：{SOURCE_TYPE_LABEL[result.source_type] || result.source_type}
          </Tag>
        )}
      </Space>

      {(result?.source_type === 'DEPT' || result?.source_type === 'EMPLOYEE') && (
        <Alert
          style={{ marginBottom: 12, borderRadius: 10 }} type="info" showIcon
          message="部门 / 职员 维度以 #id 标识"
          description="后端口径：DEPT / EMPLOYEE 无独立主数据表（弱引用多态），分组名以「#id」呈现；客户 / 供应商 / 项目轴附带 code/name。"
        />
      )}

      {!loaded ? (
        <Empty style={{ padding: 40 }} description="选择维度后点「查询」" />
      ) : errorMsg ? (
        <Result status="warning" title="无法生成核算维度余额表" subTitle={errorMsg} />
      ) : groups.length === 0 ? (
        <Empty style={{ padding: 40 }} description="本期间该维度无已过账分录" />
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          {groups.map((g) => (
            <Card
              key={g.group_id ?? '_null'}
              size="small"
              styles={{ body: { padding: 0 } }}
              style={{ borderRadius: 12 }}
              title={
                <Space size={10} wrap>
                  {g.group_code && <span style={{ fontFamily: MONO, fontWeight: 600 }}>{g.group_code}</span>}
                  <span>{g.group_name}</span>
                </Space>
              }
              extra={
                <Space size={16} style={{ fontSize: 12, color: '#777169' }}>
                  <span>本期净额 <b style={{ fontFamily: MONO, color: '#000' }}>{fmtMoney(g.total_period_net)}</b></span>
                  <span>本年累计净额 <b style={{ fontFamily: MONO, color: '#000' }}>{fmtMoney(g.total_ytd_net)}</b></span>
                </Space>
              }
            >
              <Table
                size="small"
                rowKey="account_id"
                dataSource={g.accounts}
                columns={acctColumns}
                pagination={false}
                scroll={{ x: 'max-content' }}
              />
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
