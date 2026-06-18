/**
 * ARPage —— 应收管理（应收视图，owns by C·业财映射 PM，finance-gl wave-2）
 *
 * 落「应收视图」：应收台账（应收单 / 账龄 / 关联凭证）只读 + 核销入口占位。打通业财一体化的「读」侧：
 *   销售开票 → 业财映射规则（AccountMappingRule）自动生成凭证（借应收/贷收入+贷销项税）→ 过账写
 *   AccountBalance → 同时业务侧落 accounts_receivable 台账 → 本页把「应收单 ↔ 关联凭证」两侧拉通展示。
 *
 * 数据源（均后端 _company_filter 隔离，账簿=当前会话公司）：
 *   · 应收台账 + 关联凭证：通用 /api/query(accounts_receivable)（含 voucher_id 回链、paid_amount、status）。
 *   · 账龄分桶：/api/reports/aging_analysis（按 invoice_number 客户端 join 出 bucket / overdue_days / outstanding）。
 *   · 关联凭证下钻：/api/query(voucher, {id}) 取凭证号/状态/借贷合计（点行打开抽屉）。
 *
 * 只读 + 核销入口占位：核销（收款冲应收）走资金类凭证 + 应收 paid_amount 递减，后端核销命令未就绪前本页
 *   诚实标注「核销入口待后端命令 ➕」，不在前端伪造核销写库（守唯一写入路径）。
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  App, Card, Button, Space, Table, Tag, Drawer, Alert, Empty, Descriptions, Statistic, Row, Col as ACol, Input,
} from 'antd';
import { ReloadOutlined, LinkOutlined } from '@ant-design/icons';
import { useAuth } from '../../auth';
import { query, getAgingAnalysis } from '../../api';
import { MONO, fmtMoney } from './financeHelpers';

// 账龄桶中文标签 + 配色（对齐 reports.aging_analysis 的 bucket 取值）。
const BUCKET = {
  current: { label: '未到期', color: 'green' },
  d1_30: { label: '逾期 1–30', color: 'gold' },
  d31_60: { label: '逾期 31–60', color: 'orange' },
  d61_90: { label: '逾期 61–90', color: 'volcano' },
  d90_plus: { label: '逾期 90+', color: 'red' },
};
// 应收单状态中文标签。
const AR_STATUS = {
  PENDING: { label: '待收', color: 'gold' },
  PARTIAL: { label: '部分收款', color: 'blue' },
  PAID: { label: '已收清', color: 'green' },
  SETTLED: { label: '已结算', color: 'green' },
  CLOSED: { label: '已关闭', color: 'default' },
};

export default function ARPage() {
  const { user } = useAuth();
  const { message } = App.useApp();

  const [rows, setRows] = useState([]);
  const [bucketTotals, setBucketTotals] = useState(null);
  const [loading, setLoading] = useState(false);
  const [kw, setKw] = useState('');

  // 关联凭证下钻
  const [drillAr, setDrillAr] = useState(null);
  const [drillVoucher, setDrillVoucher] = useState(null);
  const [drillEntries, setDrillEntries] = useState([]);
  const [drillLoading, setDrillLoading] = useState(false);
  const [drillOpen, setDrillOpen] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      // 1) 应收台账（含 voucher_id 回链 / paid_amount / status）。
      const { data: arData } = await query('accounts_receivable', { order_by: '-id', limit: 500 });
      const ars = arData?.data || [];
      // 2) 客户名（批量取 customer 客户端 join）。
      const { data: custData } = await query('customer', { limit: 1000 });
      const custById = new Map((custData?.data || []).map((c) => [c.id, c]));
      // 3) 账龄分桶（按 invoice_number join 出 bucket / overdue_days / outstanding）。
      let agingByInvoice = new Map();
      let buckets = null;
      try {
        const { data: aging } = await getAgingAnalysis();
        agingByInvoice = new Map((aging?.data || []).map((a) => [a.invoice_number, a]));
        buckets = aging?.bucket_totals || null;
      } catch (e) {
        // 账龄端点失败不阻塞主台账，仅降级（不显示桶）。
        message.warning('账龄分析加载失败，仅显示应收台账：' + (e.response?.data?.detail || e.message));
      }
      const joined = ars.map((ar) => {
        const cust = custById.get(ar.customer_id) || {};
        const ag = agingByInvoice.get(ar.invoice_number) || {};
        const outstanding = Math.round(((Number(ar.amount) || 0) - (Number(ar.paid_amount) || 0)) * 100) / 100;
        return {
          ...ar,
          customer_name: cust.short_name || cust.name || (ar.customer_id ? `客户#${ar.customer_id}` : '—'),
          customer_code: cust.code || '',
          outstanding,
          bucket: ag.bucket || null,
          overdue_days: ag.overdue_days ?? null,
        };
      });
      setRows(joined);
      setBucketTotals(buckets);
    } catch (e) {
      message.error('应收台账加载失败：' + (e.response?.data?.detail || e.message));
      setRows([]);
    } finally { setLoading(false); }
  }, [message]);

  useEffect(() => { load(); }, [load]);

  // 关联凭证下钻：取该应收单 voucher_id 的凭证头 + 分录。
  const drillDown = useCallback(async (ar) => {
    setDrillAr(ar);
    setDrillOpen(true);
    setDrillVoucher(null);
    setDrillEntries([]);
    if (!ar.voucher_id) return;
    setDrillLoading(true);
    try {
      const { data: vData } = await query('voucher', { filters: { id: ar.voucher_id }, limit: 1 });
      const v = vData?.data?.[0] || null;
      setDrillVoucher(v);
      if (v) {
        const { data: eData } = await query('voucher_entry', { filters: { voucher_id: v.id }, order_by: 'line_number', limit: 100 });
        setDrillEntries(eData?.data || []);
      }
    } catch (e) {
      message.error('关联凭证加载失败：' + (e.response?.data?.detail || e.message));
    } finally { setDrillLoading(false); }
  }, [message]);

  const filtered = useMemo(() => {
    const q = kw.trim().toLowerCase();
    if (!q) return rows;
    return rows.filter((r) =>
      String(r.invoice_number || '').toLowerCase().includes(q)
      || String(r.customer_name || '').toLowerCase().includes(q)
      || String(r.customer_code || '').toLowerCase().includes(q));
  }, [rows, kw]);

  const totals = useMemo(() => {
    let amount = 0, paid = 0, outstanding = 0;
    for (const r of filtered) {
      amount += Number(r.amount) || 0;
      paid += Number(r.paid_amount) || 0;
      outstanding += Number(r.outstanding) || 0;
    }
    const round2 = (x) => Math.round(x * 100) / 100;
    return { amount: round2(amount), paid: round2(paid), outstanding: round2(outstanding) };
  }, [filtered]);

  const columns = [
    { title: '应收单', dataIndex: 'id', width: 70, fixed: 'left', render: (v) => <span style={{ fontFamily: MONO }}>#{v}</span> },
    { title: '发票号', dataIndex: 'invoice_number', width: 150, fixed: 'left', render: (v) => v ? <span style={{ fontFamily: MONO }}>{v}</span> : <span style={{ color: '#bfbbb5' }}>—</span> },
    { title: '客户', dataIndex: 'customer_name', width: 160, render: (v, r) => <span>{v}{r.customer_code ? <span style={{ color: '#999', marginLeft: 6, fontSize: 12 }}>{r.customer_code}</span> : null}</span> },
    { title: '应收金额', dataIndex: 'amount', width: 130, align: 'right', render: money },
    { title: '已收', dataIndex: 'paid_amount', width: 120, align: 'right', render: money },
    { title: '未收余额', dataIndex: 'outstanding', width: 130, align: 'right', render: (v) => <span style={{ fontFamily: MONO, fontWeight: 600 }}>{fmtMoney(v)}</span> },
    { title: '币种', dataIndex: 'currency', width: 64 },
    { title: '到期日', dataIndex: 'due_date', width: 110, render: (v) => v || <span style={{ color: '#bfbbb5' }}>—</span> },
    {
      title: '账龄', dataIndex: 'bucket', width: 110,
      render: (v, r) => {
        if (!v) return <span style={{ color: '#bfbbb5' }}>—</span>;
        const b = BUCKET[v] || { label: v, color: 'default' };
        return <Tag color={b.color}>{b.label}{r.overdue_days ? `（${r.overdue_days}天）` : ''}</Tag>;
      },
    },
    {
      title: '状态', dataIndex: 'status', width: 92,
      render: (v) => { const s = AR_STATUS[v] || { label: v, color: 'default' }; return <Tag color={s.color}>{s.label}</Tag>; },
    },
    {
      title: '关联凭证', dataIndex: 'voucher_id', width: 100,
      render: (v) => v
        ? <Tag color="geekblue" icon={<LinkOutlined />}>凭证#{v}</Tag>
        : <Tag color="default">未生成</Tag>,
    },
    {
      title: '操作', dataIndex: '_a', width: 130, fixed: 'right',
      render: (_, r) => (
        <Space size={4}>
          <Button type="link" size="small" disabled={!r.voucher_id} onClick={() => drillDown(r)}>关联凭证</Button>
          <Button type="link" size="small" disabled onClick={() => message.info('核销入口待后端命令 ➕')}>核销</Button>
        </Space>
      ),
    },
  ];

  return (
    <div>
      <div style={{ marginBottom: 16, display: 'flex', alignItems: 'baseline', gap: 12, flexWrap: 'wrap' }}>
        <h2 style={{ fontSize: 26, fontWeight: 300, letterSpacing: '-0.01em', color: '#000', margin: 0, lineHeight: 1.2 }}>
          应收管理
        </h2>
        <span style={{ color: '#777169', fontSize: 13 }}>
          财务 / 总账 · 应收台账 + 账龄 + 关联凭证（业财一体化只读视图）· 账簿 = {user?.company_name || `公司 #${user?.company_id ?? ''}`}
        </span>
      </div>

      {/* 汇总卡 */}
      <Card size="small" style={{ borderRadius: 14, marginBottom: 14 }}>
        <Row gutter={24}>
          <ACol><Statistic title="应收合计" value={fmtMoney(totals.amount)} valueStyle={{ fontFamily: MONO, fontSize: 20 }} /></ACol>
          <ACol><Statistic title="已收合计" value={fmtMoney(totals.paid)} valueStyle={{ fontFamily: MONO, fontSize: 20, color: '#389e0d' }} /></ACol>
          <ACol><Statistic title="未收余额" value={fmtMoney(totals.outstanding)} valueStyle={{ fontFamily: MONO, fontSize: 20, color: '#cf1322' }} /></ACol>
          <ACol flex="auto" style={{ textAlign: 'right' }}>
            <Space>
              <Input.Search allowClear placeholder="发票号 / 客户" value={kw} onChange={(e) => setKw(e.target.value)} style={{ width: 220 }} />
              <Button icon={<ReloadOutlined />} loading={loading} onClick={load}>刷新</Button>
            </Space>
          </ACol>
        </Row>
        {bucketTotals && (
          <Space wrap size={8} style={{ marginTop: 12 }}>
            <span style={{ fontSize: 12, color: '#777169' }}>账龄分桶（未清应收）：</span>
            {Object.entries(BUCKET).map(([k, b]) => (
              <Tag key={k} color={b.color}>{b.label}：{fmtMoney(bucketTotals[k] || 0)}</Tag>
            ))}
          </Space>
        )}
      </Card>

      {/* 应收台账 */}
      <Card size="small" style={{ borderRadius: 14 }} styles={{ body: { padding: 0 } }}>
        {!loading && !rows.length ? (
          <Empty style={{ padding: 40 }} description="暂无应收单（销售开票过账后自动落应收 + 关联凭证）" />
        ) : (
          <Table
            size="small"
            rowKey="id"
            loading={loading}
            dataSource={filtered}
            columns={columns}
            pagination={{ pageSize: 30, showSizeChanger: true }}
            scroll={{ x: 'max-content', y: 'calc(100vh - 360px)' }}
            sticky
            summary={() => (
              <Table.Summary fixed>
                <Table.Summary.Row style={{ background: 'rgba(245,242,239,0.6)', fontWeight: 600 }}>
                  <Table.Summary.Cell index={0} colSpan={3}>合计（{filtered.length} 张应收单）</Table.Summary.Cell>
                  <Table.Summary.Cell index={3} align="right">{fmtMoney(totals.amount)}</Table.Summary.Cell>
                  <Table.Summary.Cell index={4} align="right">{fmtMoney(totals.paid)}</Table.Summary.Cell>
                  <Table.Summary.Cell index={5} align="right">{fmtMoney(totals.outstanding)}</Table.Summary.Cell>
                  <Table.Summary.Cell index={6} colSpan={6} />
                </Table.Summary.Row>
              </Table.Summary>
            )}
          />
        )}
      </Card>

      {/* 关联凭证下钻抽屉 */}
      <Drawer
        open={drillOpen}
        onClose={() => setDrillOpen(false)}
        width={820}
        title={drillAr ? `关联凭证 · 应收单 #${drillAr.id}${drillAr.invoice_number ? `（${drillAr.invoice_number}）` : ''}` : '关联凭证'}
      >
        {drillAr && !drillAr.voucher_id && (
          <Alert type="warning" showIcon style={{ borderRadius: 10 }}
            message="该应收单尚未关联凭证"
            description="销售开票经业财映射规则生成凭证并过账后，应收单 voucher_id 才回链；当前为业务侧先建应收、凭证未生成（或老数据）。" />
        )}
        {drillAr?.voucher_id && (
          <>
            <Descriptions size="small" column={3} style={{ marginBottom: 12 }} styles={{ label: { color: '#777169' } }}>
              <Descriptions.Item label="凭证号">{drillVoucher?.voucher_number ? <span style={{ fontFamily: MONO }}>{drillVoucher.voucher_number}</span> : '—'}</Descriptions.Item>
              <Descriptions.Item label="凭证日期">{drillVoucher?.voucher_date || '—'}</Descriptions.Item>
              <Descriptions.Item label="状态">
                {drillVoucher ? <Tag color={drillVoucher.status === 'POSTED' ? 'green' : 'default'}>{drillVoucher.status}</Tag> : '—'}
              </Descriptions.Item>
              <Descriptions.Item label="借方合计">{fmtMoney(drillVoucher?.total_debit)}</Descriptions.Item>
              <Descriptions.Item label="贷方合计">{fmtMoney(drillVoucher?.total_credit)}</Descriptions.Item>
              <Descriptions.Item label="来源单">{drillVoucher?.source_doc_type || '—'} {drillVoucher?.source_doc_id ? `#${drillVoucher.source_doc_id}` : ''}</Descriptions.Item>
            </Descriptions>
            <Table
              size="small"
              rowKey="id"
              loading={drillLoading}
              dataSource={drillEntries}
              pagination={false}
              scroll={{ x: 'max-content' }}
              columns={[
                { title: '行', dataIndex: 'line_number', width: 50 },
                { title: '摘要', dataIndex: 'description', width: 220, render: (v) => v || <span style={{ color: '#bfbbb5' }}>—</span> },
                { title: '借方（本位币）', dataIndex: 'base_debit', width: 130, align: 'right', render: money },
                { title: '贷方（本位币）', dataIndex: 'base_credit', width: 130, align: 'right', render: money },
                { title: '原币借', dataIndex: 'debit', width: 110, align: 'right', render: money },
                { title: '原币贷', dataIndex: 'credit', width: 110, align: 'right', render: money },
                { title: '币种', dataIndex: 'currency', width: 64 },
              ]}
            />
          </>
        )}
      </Drawer>
    </div>
  );
}

function money(v) {
  const n = Number(v);
  if (!n) return <span style={{ color: '#d9d4cd' }}>—</span>;
  return <span style={{ fontFamily: MONO }}>{fmtMoney(v)}</span>;
}
