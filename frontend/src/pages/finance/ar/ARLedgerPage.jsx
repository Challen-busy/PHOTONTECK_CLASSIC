/**
 * ARLedgerPage —— 应收报表台账（finance-gl·应收款管理，owns by C·应收报表 PM）
 *
 * 落「应收四表」多 Tab，全只读，全后端 _company_filter 隔离（账簿=当前会话公司）：
 *   · 汇总表 /api/reports/ar-summary —— 按客户×币别期末未清（应收−已收−已核销）。
 *   · 明细表 /api/reports/ar-detail —— 逐应收单（含税/不含税/税额/已收/已核销/未清）；含已结开关。
 *   · 账龄表 /api/reports/aging_analysis —— 复用已有账龄端点（bucket / overdue_days / outstanding）。
 *   · 客户对账单 /api/reports/customer-statement —— 单客户应收/收款时序 + 期初/期末余额逐行滚算。
 *
 * as_of / 期间过滤前端传参；客户筛选用 F7（query customer）。不在前端伪造汇总（全走后端聚合端点）。
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  App, Card, Tabs, Select, Button, Space, Table, Tag, DatePicker, Switch, Statistic, Row, Col as ACol, Empty, Alert, Descriptions,
} from 'antd';
import { ReloadOutlined, SearchOutlined } from '@ant-design/icons';
import { useAuth } from '../../../auth';
import {
  query, getAgingAnalysis, getArSummary, getArDetail, getCustomerStatement,
} from '../../../api';
import { MONO, fmtMoney, statusLabel } from '../financeHelpers';

const BUCKET = {
  current: { label: '未到期', color: 'green' },
  d1_30: { label: '逾期 1–30', color: 'gold' },
  d31_60: { label: '逾期 31–60', color: 'orange' },
  d61_90: { label: '逾期 61–90', color: 'volcano' },
  d90_plus: { label: '逾期 90+', color: 'red' },
};
const fmtDate = (d) => (d ? d.format('YYYY-MM-DD') : undefined);

export default function ARLedgerPage() {
  const { user } = useAuth();
  const { message } = App.useApp();

  const [tab, setTab] = useState('summary');
  const [customers, setCustomers] = useState([]);
  const custById = useMemo(() => new Map(customers.map((c) => [c.id, c])), [customers]);

  useEffect(() => {
    query('customer', { limit: 1000, order_by: 'code' })
      .then(({ data }) => setCustomers(data?.data || []))
      .catch((e) => message.error('客户加载失败：' + (e.response?.data?.detail || e.message)));
  }, [message]);

  const customerOptions = customers.map((c) => ({ value: c.id, label: `${c.short_name || c.name}${c.code ? `（${c.code}）` : ''}` }));

  return (
    <div>
      <div style={{ marginBottom: 16, display: 'flex', alignItems: 'baseline', gap: 12, flexWrap: 'wrap' }}>
        <h2 style={{ fontSize: 26, fontWeight: 300, letterSpacing: '-0.01em', color: '#000', margin: 0, lineHeight: 1.2 }}>
          应收报表
        </h2>
        <span style={{ color: '#777169', fontSize: 13 }}>
          财务 / 应收款管理 · 汇总 / 明细 / 账龄 / 客户对账单（只读）· 账簿 = {user?.company_name || `公司 #${user?.company_id ?? ''}`}
        </span>
      </div>

      <Card size="small" style={{ borderRadius: 14 }} styles={{ body: { paddingTop: 8 } }}>
        <Tabs activeKey={tab} onChange={setTab} items={[
          { key: 'summary', label: '应收款汇总表', children: <SummaryTab message={message} /> },
          { key: 'detail', label: '应收款明细表', children: <DetailTab customerOptions={customerOptions} message={message} /> },
          { key: 'aging', label: '账龄分析表', children: <AgingTab custById={custById} message={message} /> },
          { key: 'statement', label: '客户对账单', children: <StatementTab customerOptions={customerOptions} message={message} /> },
        ]} />
      </Card>
    </div>
  );
}

/* ── 应收款汇总表（按客户×币别期末未清）── */
function SummaryTab({ message }) {
  const [asOf, setAsOf] = useState(null);
  const [rows, setRows] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [loaded, setLoaded] = useState(false);

  const run = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await getArSummary({ as_of: fmtDate(asOf) });
      setRows(data?.data || []);
      setTotal(data?.total_outstanding || 0);
      setLoaded(true);
    } catch (e) {
      message.error('应收汇总加载失败：' + (e.response?.data?.detail || e.message));
      setRows([]);
    } finally { setLoading(false); }
  }, [asOf, message]);
  useEffect(() => { run(); }, [run]);

  const columns = [
    { title: '客户', dataIndex: 'customer_name', width: 200, fixed: 'left', render: (v, r) => <span>{v}{r.customer_code ? <span style={{ color: '#999', marginLeft: 6, fontSize: 12 }}>{r.customer_code}</span> : null}</span> },
    { title: '币别', dataIndex: 'currency', width: 70 },
    { title: '应收合计', dataIndex: 'total_amount', width: 130, align: 'right', render: money },
    { title: '已收', dataIndex: 'paid_amount', width: 120, align: 'right', render: money },
    { title: '已核销', dataIndex: 'written_off_amount', width: 120, align: 'right', render: money },
    { title: '期末未清', dataIndex: 'outstanding', width: 140, align: 'right', render: (v) => <strong style={{ fontFamily: MONO }}>{fmtMoney(v)}</strong> },
    { title: '单据数', dataIndex: 'bill_count', width: 80, align: 'right' },
  ];

  return (
    <>
      <FilterBar>
        <Fld label="截止日（as_of）"><DatePicker size="small" value={asOf} onChange={setAsOf} placeholder="不限（全部未清）" /></Fld>
        <Button size="small" type="primary" icon={<SearchOutlined />} loading={loading} onClick={run}>查询</Button>
      </FilterBar>
      <ReportTable loaded={loaded} loading={loading} rows={rows} rowKey={(r) => `${r.customer_id}-${r.currency}`} columns={columns}
        emptyText="无应收数据"
        summary={() => (
          <Table.Summary fixed>
            <Table.Summary.Row style={{ background: 'rgba(245,242,239,0.6)', fontWeight: 600 }}>
              <Table.Summary.Cell index={0} colSpan={5}>期末未清合计（{rows.length} 行）</Table.Summary.Cell>
              <Table.Summary.Cell index={5} align="right">{fmtMoney(total)}</Table.Summary.Cell>
              <Table.Summary.Cell index={6} />
            </Table.Summary.Row>
          </Table.Summary>
        )} />
    </>
  );
}

/* ── 应收款明细表（逐应收单）── */
function DetailTab({ customerOptions, message }) {
  const [customerId, setCustomerId] = useState(null);
  const [asOf, setAsOf] = useState(null);
  const [includeSettled, setIncludeSettled] = useState(false);
  const [rows, setRows] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [loaded, setLoaded] = useState(false);

  const run = useCallback(async () => {
    setLoading(true);
    try {
      const params = { include_settled: includeSettled };
      if (customerId) params.customer_id = customerId;
      if (asOf) params.as_of = fmtDate(asOf);
      const { data } = await getArDetail(params);
      setRows(data?.data || []);
      setTotal(data?.total_outstanding || 0);
      setLoaded(true);
    } catch (e) {
      message.error('应收明细加载失败：' + (e.response?.data?.detail || e.message));
      setRows([]);
    } finally { setLoading(false); }
  }, [customerId, asOf, includeSettled, message]);
  useEffect(() => { run(); }, [run]);

  const columns = [
    { title: '应收单号', dataIndex: 'bill_number', width: 150, fixed: 'left', render: (v, r) => <span style={{ fontFamily: MONO }}>{v || `#${r.id}`}</span> },
    { title: '发票号', dataIndex: 'invoice_number', width: 140, render: (v) => v ? <span style={{ fontFamily: MONO }}>{v}</span> : dash },
    { title: '客户', dataIndex: 'customer_name', width: 160, render: (v, r) => <span>{v}{r.customer_code ? <span style={{ color: '#999', marginLeft: 6, fontSize: 12 }}>{r.customer_code}</span> : null}</span> },
    { title: '业务日期', dataIndex: 'bill_date', width: 100, render: (v) => v || dash },
    { title: '到期日', dataIndex: 'due_date', width: 100, render: (v) => v || dash },
    { title: '币别', dataIndex: 'currency', width: 60 },
    { title: '不含税', dataIndex: 'untaxed_amount', width: 110, align: 'right', render: money },
    { title: '税额', dataIndex: 'tax_amount', width: 100, align: 'right', render: money },
    { title: '价税合计', dataIndex: 'amount', width: 120, align: 'right', render: money },
    { title: '已收', dataIndex: 'paid_amount', width: 110, align: 'right', render: money },
    { title: '已核销', dataIndex: 'written_off_amount', width: 110, align: 'right', render: money },
    { title: '未清', dataIndex: 'outstanding', width: 120, align: 'right', render: (v) => <strong style={{ fontFamily: MONO }}>{fmtMoney(v)}</strong> },
    { title: '单据状态', dataIndex: 'status', width: 100, render: (v) => <Tag>{statusLabel(v)}</Tag> },
    { title: '核销状态', dataIndex: 'writeoff_status', width: 100, render: (v) => v ? <Tag color="blue">{statusLabel(v)}</Tag> : dash },
  ];

  return (
    <>
      <FilterBar>
        <Fld label="客户">
          <Select size="small" style={{ width: 200 }} allowClear showSearch optionFilterProp="label"
            placeholder="全部客户" value={customerId ?? undefined} onChange={setCustomerId} options={customerOptions} />
        </Fld>
        <Fld label="截止日（as_of）"><DatePicker size="small" value={asOf} onChange={setAsOf} placeholder="不限" /></Fld>
        <Fld label="含已结清"><Switch size="small" checked={includeSettled} onChange={setIncludeSettled} /></Fld>
        <Button size="small" type="primary" icon={<SearchOutlined />} loading={loading} onClick={run}>查询</Button>
      </FilterBar>
      <ReportTable loaded={loaded} loading={loading} rows={rows} rowKey="id" columns={columns}
        emptyText={includeSettled ? '无应收单' : '无未清应收单'}
        summary={() => (
          <Table.Summary fixed>
            <Table.Summary.Row style={{ background: 'rgba(245,242,239,0.6)', fontWeight: 600 }}>
              <Table.Summary.Cell index={0} colSpan={11}>未清合计（{rows.length} 张应收单）</Table.Summary.Cell>
              <Table.Summary.Cell index={11} align="right">{fmtMoney(total)}</Table.Summary.Cell>
              <Table.Summary.Cell index={12} colSpan={2} />
            </Table.Summary.Row>
          </Table.Summary>
        )} />
    </>
  );
}

/* ── 账龄分析表（复用已有 aging_analysis 端点）── */
function AgingTab({ custById, message }) {
  const [rows, setRows] = useState([]);
  const [buckets, setBuckets] = useState(null);
  const [loading, setLoading] = useState(false);
  const [loaded, setLoaded] = useState(false);

  const run = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await getAgingAnalysis();
      const list = (data?.data || []).map((a) => {
        const c = custById.get(a.customer_id) || {};
        return { ...a, customer_name: a.customer_name || c.short_name || c.name || (a.customer_id ? `客户#${a.customer_id}` : '—'), customer_code: a.customer_code || c.code || '' };
      });
      setRows(list);
      setBuckets(data?.bucket_totals || null);
      setLoaded(true);
    } catch (e) {
      message.error('账龄分析加载失败：' + (e.response?.data?.detail || e.message));
      setRows([]);
    } finally { setLoading(false); }
  }, [custById, message]);
  useEffect(() => { run(); }, [run]);

  const columns = [
    { title: '发票号', dataIndex: 'invoice_number', width: 150, fixed: 'left', render: (v) => v ? <span style={{ fontFamily: MONO }}>{v}</span> : dash },
    { title: '客户', dataIndex: 'customer_name', width: 180, render: (v, r) => <span>{v}{r.customer_code ? <span style={{ color: '#999', marginLeft: 6, fontSize: 12 }}>{r.customer_code}</span> : null}</span> },
    { title: '到期日', dataIndex: 'due_date', width: 110, render: (v) => v || dash },
    { title: '逾期天数', dataIndex: 'overdue_days', width: 90, align: 'right', render: (v) => (v ?? 0) },
    { title: '未清金额', dataIndex: 'outstanding', width: 130, align: 'right', render: (v) => <strong style={{ fontFamily: MONO }}>{fmtMoney(v)}</strong> },
    { title: '币别', dataIndex: 'currency', width: 64 },
    {
      title: '账龄桶', dataIndex: 'bucket', width: 130,
      render: (v) => { if (!v) return dash; const b = BUCKET[v] || { label: v, color: 'default' }; return <Tag color={b.color}>{b.label}</Tag>; },
    },
  ];

  return (
    <>
      <FilterBar>
        <Button size="small" icon={<ReloadOutlined />} loading={loading} onClick={run}>刷新</Button>
        {buckets && (
          <Space wrap size={8} style={{ marginLeft: 8 }}>
            {Object.entries(BUCKET).map(([k, b]) => <Tag key={k} color={b.color}>{b.label}：{fmtMoney(buckets[k] || 0)}</Tag>)}
          </Space>
        )}
      </FilterBar>
      <ReportTable loaded={loaded} loading={loading} rows={rows} rowKey={(r, i) => r.invoice_number || `r${i}`} columns={columns} emptyText="无未清应收（无账龄数据）" />
    </>
  );
}

/* ── 客户对账单（单客户应收/收款时序 + 期初/期末余额）── */
function StatementTab({ customerOptions, message }) {
  const [customerId, setCustomerId] = useState(null);
  const [range, setRange] = useState([null, null]);
  const [stmt, setStmt] = useState(null);
  const [loading, setLoading] = useState(false);

  const run = useCallback(async () => {
    if (!customerId) { message.warning('请先选择客户'); return; }
    setLoading(true);
    try {
      const params = { customer_id: customerId };
      if (range?.[0]) params.date_from = fmtDate(range[0]);
      if (range?.[1]) params.date_to = fmtDate(range[1]);
      const { data } = await getCustomerStatement(params);
      setStmt(data || null);
    } catch (e) {
      message.error('客户对账单加载失败：' + (e.response?.data?.detail || e.message));
      setStmt(null);
    } finally { setLoading(false); }
  }, [customerId, range, message]);

  const txnColumns = [
    { title: '日期', dataIndex: 'date', width: 110, render: (v) => v || dash },
    { title: '类型', dataIndex: 'type', width: 110, render: (v) => <Tag color={v === 'AR_RECEIPT' ? 'green' : 'geekblue'}>{v === 'AR_RECEIPT' ? '收款' : '应收'}</Tag> },
    { title: '单据号', dataIndex: 'doc_no', width: 160, render: (v) => <span style={{ fontFamily: MONO }}>{v || '—'}</span> },
    { title: '币别', dataIndex: 'currency', width: 60 },
    { title: '借（应收增）', dataIndex: 'debit', width: 130, align: 'right', render: money },
    { title: '贷（收款/核销）', dataIndex: 'credit', width: 140, align: 'right', render: money },
    { title: '余额', dataIndex: 'running_balance', width: 130, align: 'right', render: (v) => <strong style={{ fontFamily: MONO }}>{fmtMoney(v)}</strong> },
    { title: '到期日', dataIndex: 'due_date', width: 100, render: (v) => v || dash },
    { title: '预收', dataIndex: 'is_advance', width: 70, render: (v) => v ? <Tag color="purple">预收</Tag> : dash },
  ];

  return (
    <>
      <FilterBar>
        <Fld label="客户（必选）">
          <Select size="small" style={{ width: 220 }} showSearch optionFilterProp="label"
            placeholder="选择客户" value={customerId ?? undefined} onChange={setCustomerId} options={customerOptions} />
        </Fld>
        <Fld label="对账期间">
          <DatePicker.RangePicker size="small" value={range} onChange={(v) => setRange(v || [null, null])} />
        </Fld>
        <Button size="small" type="primary" icon={<SearchOutlined />} loading={loading} onClick={run}>出对账单</Button>
      </FilterBar>

      {!stmt ? (
        <Empty style={{ padding: 40 }} description="选择客户后点「出对账单」" />
      ) : (
        <>
          <Row gutter={24} style={{ marginBottom: 12 }}>
            <ACol><Statistic title="期初余额" value={fmtMoney(stmt.opening_balance)} valueStyle={{ fontFamily: MONO, fontSize: 18 }} /></ACol>
            <ACol><Statistic title="本期借（应收）" value={fmtMoney(stmt.total_debit)} valueStyle={{ fontFamily: MONO, fontSize: 18, color: '#1677ff' }} /></ACol>
            <ACol><Statistic title="本期贷（收款）" value={fmtMoney(stmt.total_credit)} valueStyle={{ fontFamily: MONO, fontSize: 18, color: '#389e0d' }} /></ACol>
            <ACol><Statistic title="期末余额" value={fmtMoney(stmt.closing_balance)} valueStyle={{ fontFamily: MONO, fontSize: 18, color: '#cf1322' }} /></ACol>
            <ACol flex="auto" style={{ textAlign: 'right' }}>
              <Descriptions size="small" column={1} styles={{ label: { color: '#777169' } }}>
                <Descriptions.Item label="客户">{stmt.customer_name || `#${stmt.customer_id}`}</Descriptions.Item>
              </Descriptions>
            </ACol>
          </Row>
          <Table size="small" rowKey={(r, i) => `${r.type}-${r.doc_id}-${i}`} loading={loading}
            dataSource={stmt.transactions || []} columns={txnColumns}
            pagination={{ pageSize: 30 }} scroll={{ x: 'max-content', y: 'calc(100vh - 460px)' }} sticky
            locale={{ emptyText: '本期无应收/收款流水' }} />
        </>
      )}
    </>
  );
}

/* ── 小组件 ── */
const dash = <span style={{ color: '#bfbbb5' }}>—</span>;
function money(v) { const n = Number(v); if (!n) return <span style={{ color: '#d9d4cd' }}>—</span>; return <span style={{ fontFamily: MONO }}>{fmtMoney(v)}</span>; }
function Fld({ label, children }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
      <span style={{ fontSize: 11, color: '#777169' }}>{label}</span>
      {children}
    </div>
  );
}
function FilterBar({ children }) {
  return <Space wrap size={16} align="end" style={{ marginBottom: 14 }}>{children}</Space>;
}
function ReportTable({ loaded, loading, rows, rowKey, columns, summary, emptyText }) {
  if (loaded && !loading && !rows.length) return <Empty style={{ padding: 40 }} description={emptyText} />;
  return (
    <Table size="small" rowKey={rowKey} loading={loading} dataSource={rows} columns={columns}
      pagination={{ pageSize: 30, showSizeChanger: true }} scroll={{ x: 'max-content', y: 'calc(100vh - 420px)' }}
      sticky summary={summary} />
  );
}
