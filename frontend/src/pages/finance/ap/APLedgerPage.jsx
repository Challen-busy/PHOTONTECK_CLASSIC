/**
 * APLedgerPage —— 应付报表台账（finance-gl·应付款管理，owns by C·应付报表 PM）
 *
 * 落「应付四表」多 Tab，全只读，全后端 _company_filter 隔离（账簿=当前会话公司）：
 *   · 汇总表 /api/reports/ap-summary —— 按供应商×币别期末未清（应付−已付−已核销）。
 *   · 明细表 /api/reports/ap-detail —— 逐应付单（含税/不含税/税额/已付/已核销/未清）；含已结开关。
 *   · 账龄表 —— 后端 aging_analysis 为应收专用不可用；改为前端从 ap-detail 拿明细，按 due_date
 *     客户端分桶（未到期 / 逾期 0–30 / 31–60 / 61–90 / 90+）并按供应商汇总。
 *   · 供应商对账单 /api/reports/supplier-statement —— 单供应商应付/付款时序 + 期初/期末余额逐行滚算。
 *
 * as_of / 期间过滤前端传参；供应商筛选用 F7（query supplier）。不在前端伪造汇总（汇总/明细/对账单全走后端聚合端点；
 * 仅账龄因后端无应付端点而在客户端分桶）。
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  App, Card, Tabs, Select, Button, Space, Table, Tag, DatePicker, Switch, Statistic, Row, Col as ACol, Empty, Alert, Descriptions,
} from 'antd';
import { ReloadOutlined, SearchOutlined } from '@ant-design/icons';
import { useAuth } from '../../../auth';
import {
  query, getApSummary, getApDetail, getSupplierStatement,
} from '../../../api';
import { MONO, fmtMoney, statusLabel } from '../financeHelpers';

const BUCKET = {
  current: { label: '未到期', color: 'green' },
  d0_30: { label: '逾期 0–30', color: 'gold' },
  d31_60: { label: '逾期 31–60', color: 'orange' },
  d61_90: { label: '逾期 61–90', color: 'volcano' },
  d90_plus: { label: '逾期 90+', color: 'red' },
};
const fmtDate = (d) => (d ? d.format('YYYY-MM-DD') : undefined);

export default function APLedgerPage() {
  const { user } = useAuth();
  const { message } = App.useApp();

  const [tab, setTab] = useState('summary');
  const [suppliers, setSuppliers] = useState([]);
  const suppById = useMemo(() => new Map(suppliers.map((c) => [c.id, c])), [suppliers]);

  useEffect(() => {
    query('supplier', { limit: 1000, order_by: 'code' })
      .then(({ data }) => setSuppliers(data?.data || []))
      .catch((e) => message.error('供应商加载失败：' + (e.response?.data?.detail || e.message)));
  }, [message]);

  const supplierOptions = suppliers.map((c) => ({ value: c.id, label: `${c.short_name || c.name}${c.code ? `（${c.code}）` : ''}` }));

  return (
    <div>
      <div style={{ marginBottom: 16, display: 'flex', alignItems: 'baseline', gap: 12, flexWrap: 'wrap' }}>
        <h2 style={{ fontSize: 26, fontWeight: 300, letterSpacing: '-0.01em', color: '#000', margin: 0, lineHeight: 1.2 }}>
          应付报表
        </h2>
        <span style={{ color: '#777169', fontSize: 13 }}>
          财务 / 应付款管理 · 汇总 / 明细 / 账龄 / 供应商对账单（只读）· 账簿 = {user?.company_name || `公司 #${user?.company_id ?? ''}`}
        </span>
      </div>

      <Card size="small" style={{ borderRadius: 14 }} styles={{ body: { paddingTop: 8 } }}>
        <Tabs activeKey={tab} onChange={setTab} items={[
          { key: 'summary', label: '应付款汇总表', children: <SummaryTab message={message} /> },
          { key: 'detail', label: '应付款明细表', children: <DetailTab supplierOptions={supplierOptions} message={message} /> },
          { key: 'aging', label: '账龄分析表', children: <AgingTab suppById={suppById} message={message} /> },
          { key: 'statement', label: '供应商对账单', children: <StatementTab supplierOptions={supplierOptions} message={message} /> },
        ]} />
      </Card>
    </div>
  );
}

/* ── 应付款汇总表（按供应商×币别期末未清）── */
function SummaryTab({ message }) {
  const [asOf, setAsOf] = useState(null);
  const [rows, setRows] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [loaded, setLoaded] = useState(false);

  const run = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await getApSummary({ as_of: fmtDate(asOf) });
      setRows(data?.data || []);
      setTotal(data?.total_outstanding || 0);
      setLoaded(true);
    } catch (e) {
      message.error('应付汇总加载失败：' + (e.response?.data?.detail || e.message));
      setRows([]);
    } finally { setLoading(false); }
  }, [asOf, message]);
  useEffect(() => { run(); }, [run]);

  const columns = [
    { title: '供应商', dataIndex: 'supplier_name', width: 200, fixed: 'left', render: (v, r) => <span>{v}{r.supplier_code ? <span style={{ color: '#999', marginLeft: 6, fontSize: 12 }}>{r.supplier_code}</span> : null}</span> },
    { title: '币别', dataIndex: 'currency', width: 70 },
    { title: '应付合计', dataIndex: 'total_amount', width: 130, align: 'right', render: money },
    { title: '已付', dataIndex: 'paid_amount', width: 120, align: 'right', render: money },
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
      <ReportTable loaded={loaded} loading={loading} rows={rows} rowKey={(r) => `${r.supplier_id}-${r.currency}`} columns={columns}
        emptyText="无应付数据"
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

/* ── 应付款明细表（逐应付单）── */
function DetailTab({ supplierOptions, message }) {
  const [supplierId, setSupplierId] = useState(null);
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
      if (supplierId) params.supplier_id = supplierId;
      if (asOf) params.as_of = fmtDate(asOf);
      const { data } = await getApDetail(params);
      setRows(data?.data || []);
      setTotal(data?.total_outstanding || 0);
      setLoaded(true);
    } catch (e) {
      message.error('应付明细加载失败：' + (e.response?.data?.detail || e.message));
      setRows([]);
    } finally { setLoading(false); }
  }, [supplierId, asOf, includeSettled, message]);
  useEffect(() => { run(); }, [run]);

  const columns = [
    { title: '应付单号', dataIndex: 'bill_number', width: 150, fixed: 'left', render: (v, r) => <span style={{ fontFamily: MONO }}>{v || `#${r.id}`}</span> },
    { title: '发票号', dataIndex: 'invoice_number', width: 140, render: (v) => v ? <span style={{ fontFamily: MONO }}>{v}</span> : dash },
    { title: '供应商', dataIndex: 'supplier_name', width: 160, render: (v, r) => <span>{v}{r.supplier_code ? <span style={{ color: '#999', marginLeft: 6, fontSize: 12 }}>{r.supplier_code}</span> : null}</span> },
    { title: '业务日期', dataIndex: 'bill_date', width: 100, render: (v) => v || dash },
    { title: '到期日', dataIndex: 'due_date', width: 100, render: (v) => v || dash },
    { title: '币别', dataIndex: 'currency', width: 60 },
    { title: '不含税', dataIndex: 'untaxed_amount', width: 110, align: 'right', render: money },
    { title: '税额', dataIndex: 'tax_amount', width: 100, align: 'right', render: money },
    { title: '价税合计', dataIndex: 'amount', width: 120, align: 'right', render: money },
    { title: '已付', dataIndex: 'paid_amount', width: 110, align: 'right', render: money },
    { title: '已核销', dataIndex: 'written_off_amount', width: 110, align: 'right', render: money },
    { title: '未清', dataIndex: 'outstanding', width: 120, align: 'right', render: (v) => <strong style={{ fontFamily: MONO }}>{fmtMoney(v)}</strong> },
    { title: '单据状态', dataIndex: 'status', width: 100, render: (v) => <Tag>{statusLabel(v)}</Tag> },
    { title: '核销状态', dataIndex: 'writeoff_status', width: 100, render: (v) => v ? <Tag color="blue">{statusLabel(v)}</Tag> : dash },
  ];

  return (
    <>
      <FilterBar>
        <Fld label="供应商">
          <Select size="small" style={{ width: 200 }} allowClear showSearch optionFilterProp="label"
            placeholder="全部供应商" value={supplierId ?? undefined} onChange={setSupplierId} options={supplierOptions} />
        </Fld>
        <Fld label="截止日（as_of）"><DatePicker size="small" value={asOf} onChange={setAsOf} placeholder="不限" /></Fld>
        <Fld label="含已结清"><Switch size="small" checked={includeSettled} onChange={setIncludeSettled} /></Fld>
        <Button size="small" type="primary" icon={<SearchOutlined />} loading={loading} onClick={run}>查询</Button>
      </FilterBar>
      <ReportTable loaded={loaded} loading={loading} rows={rows} rowKey="id" columns={columns}
        emptyText={includeSettled ? '无应付单' : '无未清应付单'}
        summary={() => (
          <Table.Summary fixed>
            <Table.Summary.Row style={{ background: 'rgba(245,242,239,0.6)', fontWeight: 600 }}>
              <Table.Summary.Cell index={0} colSpan={11}>未清合计（{rows.length} 张应付单）</Table.Summary.Cell>
              <Table.Summary.Cell index={11} align="right">{fmtMoney(total)}</Table.Summary.Cell>
              <Table.Summary.Cell index={12} colSpan={2} />
            </Table.Summary.Row>
          </Table.Summary>
        )} />
    </>
  );
}

/* ── 账龄分析表（后端 aging_analysis 为应收专用，应付端无此端点；故前端从 ap-detail 客户端分桶并按供应商汇总）── */
function AgingTab({ suppById, message }) {
  const [rows, setRows] = useState([]);
  const [buckets, setBuckets] = useState(null);
  const [loading, setLoading] = useState(false);
  const [loaded, setLoaded] = useState(false);

  const run = useCallback(async () => {
    setLoading(true);
    try {
      // 拿全部未清应付明细（不含已结清），前端按 due_date vs today 分桶
      const { data } = await getApDetail({ include_settled: false });
      const detail = data?.data || [];
      const today = new Date(); today.setHours(0, 0, 0, 0);
      const dayMs = 86400000;
      const bucketOf = (dueStr) => {
        if (!dueStr) return 'current'; // 无到期日按未到期处理
        const due = new Date(dueStr); due.setHours(0, 0, 0, 0);
        const overdue = Math.floor((today - due) / dayMs);
        if (overdue < 0) return 'current';
        if (overdue <= 30) return 'd0_30';
        if (overdue <= 60) return 'd31_60';
        if (overdue <= 90) return 'd61_90';
        return 'd90_plus';
      };

      // 按供应商×币别聚合：各桶未清金额求和（金额取 outstanding）
      const agg = new Map();
      const totals = { current: 0, d0_30: 0, d31_60: 0, d61_90: 0, d90_plus: 0 };
      for (const it of detail) {
        const out = Number(it.outstanding) || 0;
        if (!out) continue;
        const c = suppById.get(it.supplier_id) || {};
        const key = `${it.supplier_id}-${it.currency || ''}`;
        if (!agg.has(key)) {
          agg.set(key, {
            supplier_id: it.supplier_id,
            supplier_name: it.supplier_name || c.short_name || c.name || (it.supplier_id ? `供应商#${it.supplier_id}` : '—'),
            supplier_code: it.supplier_code || c.code || '',
            currency: it.currency,
            current: 0, d0_30: 0, d31_60: 0, d61_90: 0, d90_plus: 0, total: 0,
          });
        }
        const row = agg.get(key);
        const b = bucketOf(it.due_date);
        row[b] += out;
        row.total += out;
        totals[b] += out;
      }
      setRows([...agg.values()].sort((a, b) => b.total - a.total));
      setBuckets(totals);
      setLoaded(true);
    } catch (e) {
      message.error('账龄分析加载失败：' + (e.response?.data?.detail || e.message));
      setRows([]);
      setBuckets(null);
    } finally { setLoading(false); }
  }, [suppById, message]);
  useEffect(() => { run(); }, [run]);

  const columns = [
    { title: '供应商', dataIndex: 'supplier_name', width: 200, fixed: 'left', render: (v, r) => <span>{v}{r.supplier_code ? <span style={{ color: '#999', marginLeft: 6, fontSize: 12 }}>{r.supplier_code}</span> : null}</span> },
    { title: '币别', dataIndex: 'currency', width: 64 },
    { title: BUCKET.current.label, dataIndex: 'current', width: 120, align: 'right', render: money },
    { title: BUCKET.d0_30.label, dataIndex: 'd0_30', width: 120, align: 'right', render: money },
    { title: BUCKET.d31_60.label, dataIndex: 'd31_60', width: 120, align: 'right', render: money },
    { title: BUCKET.d61_90.label, dataIndex: 'd61_90', width: 120, align: 'right', render: money },
    { title: BUCKET.d90_plus.label, dataIndex: 'd90_plus', width: 120, align: 'right', render: money },
    { title: '未清合计', dataIndex: 'total', width: 140, align: 'right', render: (v) => <strong style={{ fontFamily: MONO }}>{fmtMoney(v)}</strong> },
  ];

  const grandTotal = (buckets && Object.values(buckets).reduce((a, b) => a + b, 0)) || 0;

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
      <Alert type="info" showIcon style={{ marginBottom: 12 }}
        message="账龄按未清应付单到期日（due_date）相对今日客户端分桶；金额取未清额（outstanding），按供应商×币别汇总。" />
      <ReportTable loaded={loaded} loading={loading} rows={rows} rowKey={(r) => `${r.supplier_id}-${r.currency}`} columns={columns}
        emptyText="无未清应付（无账龄数据）"
        summary={() => (
          <Table.Summary fixed>
            <Table.Summary.Row style={{ background: 'rgba(245,242,239,0.6)', fontWeight: 600 }}>
              <Table.Summary.Cell index={0} colSpan={2}>账龄合计（{rows.length} 行）</Table.Summary.Cell>
              <Table.Summary.Cell index={2} align="right">{fmtMoney(buckets?.current || 0)}</Table.Summary.Cell>
              <Table.Summary.Cell index={3} align="right">{fmtMoney(buckets?.d0_30 || 0)}</Table.Summary.Cell>
              <Table.Summary.Cell index={4} align="right">{fmtMoney(buckets?.d31_60 || 0)}</Table.Summary.Cell>
              <Table.Summary.Cell index={5} align="right">{fmtMoney(buckets?.d61_90 || 0)}</Table.Summary.Cell>
              <Table.Summary.Cell index={6} align="right">{fmtMoney(buckets?.d90_plus || 0)}</Table.Summary.Cell>
              <Table.Summary.Cell index={7} align="right">{fmtMoney(grandTotal)}</Table.Summary.Cell>
            </Table.Summary.Row>
          </Table.Summary>
        )} />
    </>
  );
}

/* ── 供应商对账单（单供应商应付/付款时序 + 期初/期末余额）── */
function StatementTab({ supplierOptions, message }) {
  const [supplierId, setSupplierId] = useState(null);
  const [range, setRange] = useState([null, null]);
  const [stmt, setStmt] = useState(null);
  const [loading, setLoading] = useState(false);

  const run = useCallback(async () => {
    if (!supplierId) { message.warning('请先选择供应商'); return; }
    setLoading(true);
    try {
      const params = { supplier_id: supplierId };
      if (range?.[0]) params.date_from = fmtDate(range[0]);
      if (range?.[1]) params.date_to = fmtDate(range[1]);
      const { data } = await getSupplierStatement(params);
      setStmt(data || null);
    } catch (e) {
      message.error('供应商对账单加载失败：' + (e.response?.data?.detail || e.message));
      setStmt(null);
    } finally { setLoading(false); }
  }, [supplierId, range, message]);

  const txnColumns = [
    { title: '日期', dataIndex: 'date', width: 110, render: (v) => v || dash },
    { title: '类型', dataIndex: 'type', width: 110, render: (v) => <Tag color={v === 'AP_PAYMENT' ? 'green' : 'geekblue'}>{v === 'AP_PAYMENT' ? '付款' : '应付'}</Tag> },
    { title: '单据号', dataIndex: 'doc_no', width: 160, render: (v) => <span style={{ fontFamily: MONO }}>{v || '—'}</span> },
    { title: '币别', dataIndex: 'currency', width: 60 },
    { title: '贷（应付增）', dataIndex: 'credit', width: 130, align: 'right', render: money },
    { title: '借（付款/核销）', dataIndex: 'debit', width: 140, align: 'right', render: money },
    { title: '余额', dataIndex: 'running_balance', width: 130, align: 'right', render: (v) => <strong style={{ fontFamily: MONO }}>{fmtMoney(v)}</strong> },
    { title: '到期日', dataIndex: 'due_date', width: 100, render: (v) => v || dash },
    { title: '预付', dataIndex: 'is_advance', width: 70, render: (v) => v ? <Tag color="purple">预付</Tag> : dash },
  ];

  return (
    <>
      <FilterBar>
        <Fld label="供应商（必选）">
          <Select size="small" style={{ width: 220 }} showSearch optionFilterProp="label"
            placeholder="选择供应商" value={supplierId ?? undefined} onChange={setSupplierId} options={supplierOptions} />
        </Fld>
        <Fld label="对账期间">
          <DatePicker.RangePicker size="small" value={range} onChange={(v) => setRange(v || [null, null])} />
        </Fld>
        <Button size="small" type="primary" icon={<SearchOutlined />} loading={loading} onClick={run}>出对账单</Button>
      </FilterBar>

      {!stmt ? (
        <Empty style={{ padding: 40 }} description="选择供应商后点「出对账单」" />
      ) : (
        <>
          <Row gutter={24} style={{ marginBottom: 12 }}>
            <ACol><Statistic title="期初余额" value={fmtMoney(stmt.opening_balance)} valueStyle={{ fontFamily: MONO, fontSize: 18 }} /></ACol>
            <ACol><Statistic title="本期贷（应付）" value={fmtMoney(stmt.total_credit)} valueStyle={{ fontFamily: MONO, fontSize: 18, color: '#1677ff' }} /></ACol>
            <ACol><Statistic title="本期借（付款）" value={fmtMoney(stmt.total_debit)} valueStyle={{ fontFamily: MONO, fontSize: 18, color: '#389e0d' }} /></ACol>
            <ACol><Statistic title="期末余额" value={fmtMoney(stmt.closing_balance)} valueStyle={{ fontFamily: MONO, fontSize: 18, color: '#cf1322' }} /></ACol>
            <ACol flex="auto" style={{ textAlign: 'right' }}>
              <Descriptions size="small" column={1} styles={{ label: { color: '#777169' } }}>
                <Descriptions.Item label="供应商">{stmt.supplier_name || `#${stmt.supplier_id}`}</Descriptions.Item>
              </Descriptions>
            </ACol>
          </Row>
          <Table size="small" rowKey={(r, i) => `${r.type}-${r.doc_id}-${i}`} loading={loading}
            dataSource={stmt.transactions || []} columns={txnColumns}
            pagination={{ pageSize: 30 }} scroll={{ x: 'max-content', y: 'calc(100vh - 460px)' }} sticky
            locale={{ emptyText: '本期无应付/付款流水' }} />
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
