/**
 * VoucherSummaryPage —— 凭证汇总表（总账·wave-4，owns by B·前端 PM）
 *
 * 科目级借贷发生额汇总：调 GET /api/reports/voucher-summary（后端 routers/reports.py 已实现）。
 *   期间区间选择（起 period_from 必填 + 止 period_to 可选，缺省=单期）+ 含未过账开关（include_unposted）。
 *   每行：科目码/名/类别/方向 + 本期借 + 本期贷 + 净额（按余额方向）+ 凭证数。合计行给 Σ借/Σ贷 + 平衡断言。
 *
 * 口径（与后端一致，本页不二次加工）：
 *   · 默认只汇总已过账（POSTED）凭证分录；开「含未过账」纳入全状态凭证分录（后端聚合，非前端伪造）。
 *   · 本位币口径，data 按 account_code 升序。
 * 期间列表用 GET /api/reports/periods（getAccountingPeriods）。公司隔离由后端 _company_filter 兜底。
 *
 * 命令/端点经主 agent 接入 api.js 的 getVoucherSummary(params) → GET /api/reports/voucher-summary。
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  App, Card, Select, Button, Space, Table, Tag, Segmented, Empty, Alert, Statistic,
} from 'antd';
import { SearchOutlined } from '@ant-design/icons';
import { useAuth } from '../../auth';
import { getAccountingPeriods, getVoucherSummary } from '../../api';
import { MONO, fmtMoney, ACCOUNT_TYPE_LABEL } from './financeHelpers';

export default function VoucherSummaryPage() {
  const { user } = useAuth();
  const { message } = App.useApp();

  const [periods, setPeriods] = useState([]);
  const [periodFrom, setPeriodFrom] = useState(null);
  const [periodTo, setPeriodTo] = useState(null);
  const [scope, setScope] = useState('posted'); // posted | with_unposted → include_unposted

  const [rows, setRows] = useState([]);
  const [totals, setTotals] = useState({ period_debit: 0, period_credit: 0 });
  const [balanced, setBalanced] = useState(true);
  const [loading, setLoading] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [meta, setMeta] = useState({ from: null, to: null, unposted: false });

  useEffect(() => {
    getAccountingPeriods()
      .then(({ data }) => {
        const ps = data?.periods || [];
        setPeriods(ps);
        const open = ps.find((p) => p.status === 'OPEN') || ps[0];
        if (open) { setPeriodFrom(open.id); setPeriodTo(open.id); }
      })
      .catch((e) => message.error('期间加载失败：' + (e.response?.data?.detail || e.message)));
  }, [message]);

  const periodLabel = useCallback((id) => {
    const p = periods.find((x) => x.id === id);
    return p ? p.label : (id ? `期间 #${id}` : '—');
  }, [periods]);

  const runQuery = useCallback(async () => {
    if (!periodFrom) { message.warning('请选择起始会计期间'); return; }
    setLoading(true);
    try {
      const params = {
        period_from: periodFrom,
        include_unposted: scope === 'with_unposted',
      };
      if (periodTo) params.period_to = periodTo;
      const { data } = await getVoucherSummary(params);
      setRows(data?.data || []);
      setTotals(data?.totals || { period_debit: 0, period_credit: 0 });
      setBalanced(data?.balanced ?? true);
      setMeta({ from: data?.period_from, to: data?.period_to, unposted: data?.include_unposted });
      setLoaded(true);
    } catch (e) {
      message.error('凭证汇总查询失败：' + (e.response?.data?.detail || e.message));
      setRows([]);
    } finally { setLoading(false); }
  }, [periodFrom, periodTo, scope, message]);

  const columns = useMemo(() => [
    { title: '科目编码', dataIndex: 'account_code', width: 120, fixed: 'left', render: (v) => <span style={{ fontFamily: MONO }}>{v}</span> },
    { title: '科目名称', dataIndex: 'account_name', width: 200, fixed: 'left' },
    { title: '类别', dataIndex: 'account_type', width: 70, render: (v) => ACCOUNT_TYPE_LABEL[v] || v },
    { title: '方向', dataIndex: 'direction_label', width: 56, render: (v) => <Tag color={v === '借' ? 'blue' : 'gold'}>{v}</Tag> },
    { title: '本期借（本位币）', dataIndex: 'period_debit', width: 150, align: 'right', render: money },
    { title: '本期贷（本位币）', dataIndex: 'period_credit', width: 150, align: 'right', render: money },
    {
      title: '净额（方向）', dataIndex: 'net_balance', width: 150, align: 'right',
      render: (v) => <span style={{ fontFamily: MONO, fontWeight: 600 }}>{fmtMoney(v)}</span>,
    },
    { title: '凭证数', dataIndex: 'voucher_count', width: 80, align: 'right' },
  ], []);

  return (
    <div>
      <div style={{ marginBottom: 16, display: 'flex', alignItems: 'baseline', gap: 12, flexWrap: 'wrap' }}>
        <h2 style={{ fontSize: 26, fontWeight: 300, letterSpacing: '-0.01em', color: '#000', margin: 0, lineHeight: 1.2 }}>
          凭证汇总表
        </h2>
        <span style={{ color: '#777169', fontSize: 13 }}>
          财务 / 总账 · 科目级借贷发生额汇总（本位币）· 期间区间 + 含未过账开关 · 账簿 = 当前公司
        </span>
      </div>

      {/* 筛选条 */}
      <Card size="small" style={{ borderRadius: 14, marginBottom: 14 }}>
        <Space wrap size={16} align="end">
          <Col label="账簿 / 核算组织">
            <Tag color="geekblue">{user?.company_name || `公司 #${user?.company_id ?? ''}`}</Tag>
          </Col>
          <Col label="起始期间">
            <Select size="small" value={periodFrom} style={{ width: 180 }} onChange={setPeriodFrom}
              options={periods.map((p) => ({ value: p.id, label: `${p.label}${p.status !== 'OPEN' ? `（${p.status}）` : ''}` }))}
              placeholder="必选" />
          </Col>
          <Col label="结束期间（含，可空=单期）">
            <Select size="small" value={periodTo} allowClear style={{ width: 180 }} onChange={setPeriodTo}
              options={periods.map((p) => ({ value: p.id, label: `${p.label}${p.status !== 'OPEN' ? `（${p.status}）` : ''}` }))}
              placeholder="缺省=起始期间" />
          </Col>
          <Col label="口径">
            <Segmented size="small" value={scope} onChange={setScope}
              options={[{ label: '仅已过账', value: 'posted' }, { label: '含未过账', value: 'with_unposted' }]} />
          </Col>
          <Button type="primary" size="small" icon={<SearchOutlined />} loading={loading} onClick={runQuery}>查询</Button>
        </Space>
        {scope === 'with_unposted' && (
          <Alert style={{ marginTop: 10, borderRadius: 10 }} type="info" showIcon
            message="「含未过账」口径：后端在汇总时纳入全状态（含草稿/已审核）凭证分录的本位币发生额，与过账账簿口径分开，仅供批量工作台核对用。" />
        )}
      </Card>

      {/* 汇总头部统计 */}
      {loaded && (
        <Card size="small" style={{ borderRadius: 14, marginBottom: 14 }}>
          <Space size={48} wrap>
            <Statistic title="区间" value={`${periodLabel(meta.from)} → ${periodLabel(meta.to)}`} valueStyle={{ fontSize: 16 }} />
            <Statistic title="Σ 本期借" value={fmtMoney(totals.period_debit)} valueStyle={{ fontSize: 18, fontFamily: MONO }} />
            <Statistic title="Σ 本期贷" value={fmtMoney(totals.period_credit)} valueStyle={{ fontSize: 18, fontFamily: MONO }} />
            <div>
              <div style={{ fontSize: 14, color: '#777169', marginBottom: 4 }}>试算平衡</div>
              {balanced
                ? <Tag color="green" style={{ fontSize: 14, padding: '2px 12px' }}>借贷平衡 ✓</Tag>
                : <Tag color="red" style={{ fontSize: 14, padding: '2px 12px' }}>不平衡（差额 {fmtMoney((totals.period_debit || 0) - (totals.period_credit || 0))}）</Tag>}
            </div>
            <Statistic title="口径" value={meta.unposted ? '含未过账' : '仅已过账'} valueStyle={{ fontSize: 16 }} />
          </Space>
        </Card>
      )}

      {/* 汇总表 */}
      <Card size="small" style={{ borderRadius: 14 }} styles={{ body: { padding: 0 } }}>
        {!loaded ? (
          <Empty style={{ padding: 40 }} description="选择期间区间与口径后点「查询」" />
        ) : (
          <Table
            size="small"
            rowKey="account_id"
            loading={loading}
            dataSource={rows}
            columns={columns}
            pagination={{ pageSize: 50, showSizeChanger: true, showTotal: (t) => `共 ${t} 个科目` }}
            scroll={{ x: 'max-content', y: 'calc(100vh - 460px)' }}
            sticky
            summary={() => (
              <Table.Summary fixed>
                <Table.Summary.Row style={{ background: 'rgba(245,242,239,0.6)', fontWeight: 600 }}>
                  <Table.Summary.Cell index={0} colSpan={4}>合计（{rows.length} 个科目）</Table.Summary.Cell>
                  <Table.Summary.Cell index={4} align="right">{fmtMoney(totals.period_debit)}</Table.Summary.Cell>
                  <Table.Summary.Cell index={5} align="right">{fmtMoney(totals.period_credit)}</Table.Summary.Cell>
                  <Table.Summary.Cell index={6} colSpan={2} />
                </Table.Summary.Row>
              </Table.Summary>
            )}
          />
        )}
      </Card>
    </div>
  );
}

function money(v) {
  const n = Number(v);
  if (!n) return <span style={{ color: '#d9d4cd' }}>—</span>;
  return <span style={{ fontFamily: MONO }}>{fmtMoney(v)}</span>;
}
function Col({ label, children }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
      <span style={{ fontSize: 11, color: '#777169' }}>{label}</span>
      {children}
    </div>
  );
}
