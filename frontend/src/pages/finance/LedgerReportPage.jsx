/**
 * LedgerReportPage —— 账表查询页（总账·wave-1b，owns by C·前端 PM）
 *
 * 落「账表查询」：过滤（账簿 / 期间 / 科目编码区间 / 口径开关）→ 科目余额表网格 → 点行下钻明细账（该科目分录流水）。
 *
 * 口径开关（录音/蓝图：账表默认只算已过账 + 含未过账开关）：
 *   · 已过账口径（默认）：直接读后端 /api/reports/account_balance（数据源 AccountBalance，过账派生，含期初/本期/期末借贷 + 余额方向净额）。
 *   · 含未过账口径：后端账表端点当前只算已过账（AccountBalance 仅由过账 effect 累加）。本页诚实标注「含未过账口径待后端 ➕」，
 *     不在前端伪造合并未过账分录（避免与过账账簿口径打架）。
 *
 * 下钻明细账（B 的科目明细 API 就绪前的诚实降级）：后端暂无「按科目取分录流水」专端点 →
 *   本页用通用 /api/query(voucher_entry, filters={account_id}) + 关联 voucher 取日期/凭证号/状态，客户端组装明细账。
 *   默认只列已过账凭证的分录（与口径一致）；明细账端点（含期初余额逐行滚算）就绪后切换，不写死假列。
 *
 * 科目编码区间过滤：后端 /api/query 仅支持等值过滤，区间在前端按字符串闭区间筛（filterByCodeRange）。
 * 公司隔离由后端 _company_filter 兜底（账簿=当前会话公司）。
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  App, Card, Select, Input, Button, Space, Table, Tag, Segmented, Drawer, Alert, Empty, Descriptions,
} from 'antd';
import { SearchOutlined } from '@ant-design/icons';
import { useAuth } from '../../auth';
import {
  getAccountingPeriods, getAccountBalanceReport, query,
} from '../../api';
import {
  MONO, fmtMoney, filterByCodeRange, ACCOUNT_TYPE_LABEL,
} from './financeHelpers';

export default function LedgerReportPage() {
  const { user } = useAuth();
  const { message } = App.useApp();

  const [periods, setPeriods] = useState([]);
  const [periodId, setPeriodId] = useState(null);
  const [codeFrom, setCodeFrom] = useState('');
  const [codeTo, setCodeTo] = useState('');
  const [scope, setScope] = useState('posted'); // posted | with_unposted
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(false);
  const [loaded, setLoaded] = useState(false);

  // 下钻明细账
  const [drillAccount, setDrillAccount] = useState(null);
  const [drillRows, setDrillRows] = useState([]);
  const [drillLoading, setDrillLoading] = useState(false);
  const [drillOpen, setDrillOpen] = useState(false);

  useEffect(() => {
    getAccountingPeriods()
      .then(({ data }) => {
        const ps = data?.periods || [];
        setPeriods(ps);
        // 默认选当前月（最近 OPEN）
        const open = ps.find((p) => p.status === 'OPEN') || ps[0];
        if (open) setPeriodId(open.id);
      })
      .catch((e) => message.error('期间加载失败：' + (e.response?.data?.detail || e.message)));
  }, [message]);

  const runQuery = useCallback(async () => {
    if (!periodId) { message.warning('请选择会计期间'); return; }
    setLoading(true);
    try {
      const { data } = await getAccountBalanceReport({ period_id: periodId });
      let list = data?.data || [];
      list = filterByCodeRange(list, codeFrom.trim(), codeTo.trim());
      setRows(list);
      setLoaded(true);
    } catch (e) {
      message.error('科目余额表查询失败：' + (e.response?.data?.detail || e.message));
      setRows([]);
    } finally { setLoading(false); }
  }, [periodId, codeFrom, codeTo, message]);

  // 下钻：取该科目的分录流水（明细账）。需 account_id —— 余额表行只有 account_code，先在 account 表换 id。
  const drillDown = useCallback(async (balanceRow) => {
    setDrillAccount(balanceRow);
    setDrillOpen(true);
    setDrillLoading(true);
    try {
      // 1) 科目编码 → account_id
      const { data: acctData } = await query('account', { filters: { code: balanceRow.account_code }, limit: 1 });
      const acct = acctData?.data?.[0];
      if (!acct) { setDrillRows([]); return; }
      // 2) 该科目分录
      const { data: entryData } = await query('voucher_entry', { filters: { account_id: acct.id }, order_by: 'id', limit: 500 });
      const entries = entryData?.data || [];
      if (!entries.length) { setDrillRows([]); return; }
      // 3) 关联凭证头取 日期/号/状态（批量取 voucher，客户端 join）
      const { data: vData } = await query('voucher', { order_by: '-id', limit: 1000 });
      const vById = new Map((vData?.data || []).map((v) => [v.id, v]));
      const joined = entries
        .map((e) => {
          const v = vById.get(e.voucher_id) || {};
          return {
            ...e,
            voucher_number: v.voucher_number,
            voucher_date: v.voucher_date,
            voucher_status: v.status,
          };
        })
        // 口径：已过账只看 POSTED；含未过账则全列
        .filter((e) => (scope === 'posted' ? e.voucher_status === 'POSTED' : true))
        .sort((a, b) => String(a.voucher_date || '').localeCompare(String(b.voucher_date || '')));
      // 逐行滚算余额（按科目余额方向）
      let running = 0;
      const dir = acct.balance_direction; // DEBIT/CREDIT
      const withRunning = joined.map((e) => {
        const d = Number(e.base_debit) || 0;
        const c = Number(e.base_credit) || 0;
        running += dir === 'DEBIT' ? (d - c) : (c - d);
        return { ...e, _running: Math.round(running * 100) / 100, _dir: dir };
      });
      setDrillRows(withRunning);
    } catch (e) {
      message.error('明细账下钻失败：' + (e.response?.data?.detail || e.message));
      setDrillRows([]);
    } finally { setDrillLoading(false); }
  }, [scope, message]);

  const totals = useMemo(() => {
    const t = { opening: 0, debit: 0, credit: 0, net: 0 };
    for (const r of rows) {
      t.debit += Number(r.period_debit) || 0;
      t.credit += Number(r.period_credit) || 0;
      t.net += Number(r.net_balance) || 0;
    }
    return t;
  }, [rows]);

  const columns = [
    { title: '科目编码', dataIndex: 'account_code', width: 110, fixed: 'left', render: (v) => <span style={{ fontFamily: MONO }}>{v}</span> },
    { title: '科目名称', dataIndex: 'account_name', width: 160, fixed: 'left' },
    { title: '类别', dataIndex: 'account_type', width: 70, render: (v) => ACCOUNT_TYPE_LABEL[v] || v },
    { title: '方向', dataIndex: 'direction_label', width: 56, render: (v) => <Tag color={v === '借' ? 'blue' : 'gold'}>{v}</Tag> },
    { title: '期初借', dataIndex: 'opening_debit', width: 120, align: 'right', render: money },
    { title: '期初贷', dataIndex: 'opening_credit', width: 120, align: 'right', render: money },
    { title: '本期借', dataIndex: 'period_debit', width: 120, align: 'right', render: money },
    { title: '本期贷', dataIndex: 'period_credit', width: 120, align: 'right', render: money },
    { title: '期末借', dataIndex: 'closing_debit', width: 120, align: 'right', render: money },
    { title: '期末贷', dataIndex: 'closing_credit', width: 120, align: 'right', render: money },
    {
      title: '余额（方向净额）', dataIndex: 'net_balance', width: 140, align: 'right',
      render: (v) => <span style={{ fontFamily: MONO, fontWeight: 600 }}>{fmtMoney(v)}</span>,
    },
    {
      title: '操作', dataIndex: '_a', width: 80, fixed: 'right',
      render: (_, row) => <Button type="link" size="small" onClick={() => drillDown(row)}>明细账</Button>,
    },
  ];

  return (
    <div>
      <div style={{ marginBottom: 16, display: 'flex', alignItems: 'baseline', gap: 12, flexWrap: 'wrap' }}>
        <h2 style={{ fontSize: 26, fontWeight: 300, letterSpacing: '-0.01em', color: '#000', margin: 0, lineHeight: 1.2 }}>
          账表查询
        </h2>
        <span style={{ color: '#777169', fontSize: 13 }}>
          财务 / 总账 · 科目余额表 + 明细账下钻 · 账簿 = 当前公司（后端按会话隔离）
        </span>
      </div>

      {/* 过滤条 */}
      <Card size="small" style={{ borderRadius: 14, marginBottom: 14 }}>
        <Space wrap size={16} align="end">
          <Col label="账簿 / 核算组织">
            <Tag color="geekblue">{user?.company_name || `公司 #${user?.company_id ?? ''}`}</Tag>
          </Col>
          <Col label="会计期间">
            <Select size="small" value={periodId} style={{ width: 180 }} onChange={setPeriodId}
              options={periods.map((p) => ({ value: p.id, label: `${p.label}${p.status !== 'OPEN' ? `（${p.status}）` : ''}` }))}
              placeholder="选择期间" />
          </Col>
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
          <Button type="primary" size="small" icon={<SearchOutlined />} loading={loading} onClick={runQuery}>查询</Button>
        </Space>
        {scope === 'with_unposted' && (
          <Alert
            style={{ marginTop: 10, borderRadius: 10 }} type="warning" showIcon
            message="「含未过账」口径待后端 ➕"
            description="后端账表端点（/api/reports/account_balance）数据源 AccountBalance 仅由过账 effect 累加，当前只反映已过账。含未过账口径需后端合并草稿/已审核分录，未就绪前科目余额表仍按已过账返回（本页不在前端伪造合并，避免与过账账簿口径打架）；明细账下钻已支持按口径切换列示分录。"
          />
        )}
      </Card>

      {/* 科目余额表 */}
      <Card size="small" style={{ borderRadius: 14 }} styles={{ body: { padding: 0 } }}>
        {!loaded ? (
          <Empty style={{ padding: 40 }} description="选择期间与科目区间后点「查询」" />
        ) : (
          <Table
            size="small"
            rowKey="account_code"
            loading={loading}
            dataSource={rows}
            columns={columns}
            pagination={{ pageSize: 30, showSizeChanger: true }}
            scroll={{ x: 'max-content', y: 'calc(100vh - 360px)' }}
            sticky
            summary={() => (
              <Table.Summary fixed>
                <Table.Summary.Row style={{ background: 'rgba(245,242,239,0.6)', fontWeight: 600 }}>
                  <Table.Summary.Cell index={0} colSpan={6}>合计（{rows.length} 个科目）</Table.Summary.Cell>
                  <Table.Summary.Cell index={6} align="right">{fmtMoney(totals.debit)}</Table.Summary.Cell>
                  <Table.Summary.Cell index={7} align="right">{fmtMoney(totals.credit)}</Table.Summary.Cell>
                  <Table.Summary.Cell index={8} colSpan={2} />
                  <Table.Summary.Cell index={10} align="right">{fmtMoney(totals.net)}</Table.Summary.Cell>
                  <Table.Summary.Cell index={11} />
                </Table.Summary.Row>
              </Table.Summary>
            )}
          />
        )}
      </Card>

      {/* 明细账下钻抽屉 */}
      <Drawer
        open={drillOpen}
        onClose={() => setDrillOpen(false)}
        width={920}
        title={drillAccount ? `明细账 · ${drillAccount.account_code} ${drillAccount.account_name}` : '明细账'}
      >
        {drillAccount && (
          <Descriptions size="small" column={3} style={{ marginBottom: 12 }}
            styles={{ label: { color: '#777169' } }}>
            <Descriptions.Item label="科目方向">{drillAccount.direction_label}</Descriptions.Item>
            <Descriptions.Item label="本期借">{fmtMoney(drillAccount.period_debit)}</Descriptions.Item>
            <Descriptions.Item label="本期贷">{fmtMoney(drillAccount.period_credit)}</Descriptions.Item>
            <Descriptions.Item label="期末余额">{fmtMoney(drillAccount.net_balance)}</Descriptions.Item>
            <Descriptions.Item label="口径">{scope === 'posted' ? '仅已过账' : '含未过账'}</Descriptions.Item>
          </Descriptions>
        )}
        <Alert
          type="info" showIcon style={{ marginBottom: 12, borderRadius: 10 }}
          message="明细账 = 该科目分录流水（客户端组装：voucher_entry × voucher 头），逐行滚算余额（本位币、按科目方向）。"
          description="后端「按科目取分录流水 + 期初余额逐行滚算」专端点就绪后切换（含跨期期初结转）；当前按本会话可见凭证组装，已过账口径过滤 POSTED。"
        />
        <Table
          size="small"
          rowKey="id"
          loading={drillLoading}
          dataSource={drillRows}
          pagination={{ pageSize: 50 }}
          scroll={{ x: 'max-content' }}
          columns={[
            { title: '凭证日期', dataIndex: 'voucher_date', width: 110 },
            { title: '凭证号', dataIndex: 'voucher_number', width: 130, render: (v) => <span style={{ fontFamily: MONO }}>{v}</span> },
            { title: '摘要', dataIndex: 'description', width: 200, render: (v) => v || <span style={{ color: '#bfbbb5' }}>—</span> },
            { title: '借方（本位币）', dataIndex: 'base_debit', width: 130, align: 'right', render: money },
            { title: '贷方（本位币）', dataIndex: 'base_credit', width: 130, align: 'right', render: money },
            {
              title: '方向', dataIndex: '_dir', width: 56,
              render: (v) => <Tag color={v === 'DEBIT' ? 'blue' : 'gold'}>{v === 'DEBIT' ? '借' : '贷'}</Tag>,
            },
            { title: '余额', dataIndex: '_running', width: 130, align: 'right', render: (v) => <span style={{ fontFamily: MONO, fontWeight: 600 }}>{fmtMoney(v)}</span> },
            {
              title: '凭证状态', dataIndex: 'voucher_status', width: 90,
              render: (v) => <Tag color={v === 'POSTED' ? 'green' : 'default'}>{v}</Tag>,
            },
          ]}
        />
      </Drawer>
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
