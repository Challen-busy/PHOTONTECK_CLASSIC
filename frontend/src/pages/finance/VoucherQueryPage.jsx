/**
 * VoucherQueryPage —— 凭证查询台账（总账·wave-4，owns by B·前端 PM）
 *
 * 全量凭证台账（query('voucher')）+ 丰富筛选 + 行抽屉看分录 + 下钻凭证录入页 + 从模板新建。
 *
 * 筛选（后端 /api/query 仅等值过滤 → 等值条件下推 filters，范围/关键字在前端二次筛）：
 *   会计期间(等值下推) / 凭证字(等值下推) / 状态(等值下推) / 金额区间(前端) / 制单人(等值下推) / 摘要关键字(前端) / 凭证号关键字(前端) / 日期区间(前端)。
 * 列：凭证号 / 日期 / 字 / 摘要 / 借方合计 / 贷方合计 / 状态 / 制单 / 审核 / 过账人。
 * 点行 → 抽屉拉该凭证分录（query('voucher_entry', {voucher_id}) join account 取科目码/名），底部借贷合计核对。
 * 下钻 → navigate('/finance/voucher?id={id}') 进录入页（契约：录入页读 ?id 载入对应凭证）。
 * 从模板新建 → ModelVoucherPickerModal → finance.create_voucher_from_model → 建成跳录入页。
 *
 * 引擎对齐（已 Read models.py 确认 Voucher / VoucherEntry / VoucherWord 列）。公司隔离由后端 _company_filter 兜底（账簿=当前会话公司）。
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  App, Card, Select, Input, InputNumber, Button, Space, Table, Tag, DatePicker,
  Drawer, Empty, Descriptions,
} from 'antd';
import { SearchOutlined, ReloadOutlined, PlusOutlined } from '@ant-design/icons';
import dayjs from 'dayjs';
import { useAuth } from '../../auth';
import { query, getAccountingPeriods } from '../../api';
import { MONO, fmtMoney, num } from './financeHelpers';
import ModelVoucherPickerModal from './ModelVoucherPickerModal';

const { RangePicker } = DatePicker;

// 凭证状态语义（与录入屏 / 全模块一致）。
const STATUS_META = {
  DRAFT: { label: '草稿', color: 'default' },
  AUDITED: { label: '已审核', color: 'blue' },
  REVIEWED: { label: '出纳已复核', color: 'cyan' },
  POSTED: { label: '已过账', color: 'green' },
};
const STATUS_OPTIONS = Object.entries(STATUS_META).map(([value, m]) => ({ value, label: m.label }));

export default function VoucherQueryPage() {
  const { user } = useAuth();
  const { message } = App.useApp();
  const navigate = useNavigate();

  // 主数据
  const [periods, setPeriods] = useState([]);
  const [vwords, setVwords] = useState([]);
  const [users, setUsers] = useState([]); // 制单人候选（user_account 可见范围）

  // 筛选态
  const [periodId, setPeriodId] = useState(null);
  const [vwordId, setVwordId] = useState(null);
  const [status, setStatus] = useState(null);
  const [createdById, setCreatedById] = useState(null);
  const [amountMin, setAmountMin] = useState(null);
  const [amountMax, setAmountMax] = useState(null);
  const [kw, setKw] = useState('');         // 摘要 / 凭证号关键字
  const [dateRange, setDateRange] = useState(null);

  // 数据
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(false);
  const [loaded, setLoaded] = useState(false);

  // 抽屉：分录明细
  const [drawerVoucher, setDrawerVoucher] = useState(null);
  const [drawerRows, setDrawerRows] = useState([]);
  const [drawerLoading, setDrawerLoading] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);

  // 从模板新建
  const [pickerOpen, setPickerOpen] = useState(false);

  // 初始化主数据（期间 / 凭证字 / 制单人候选）。
  useEffect(() => {
    (async () => {
      try {
        const [{ data: pd }, { data: vw }, { data: ud }] = await Promise.all([
          getAccountingPeriods(),
          query('voucher_word', { order_by: 'id', limit: 50 }),
          query('user_account', { order_by: 'id', limit: 500 }).catch(() => ({ data: { data: [] } })),
        ]);
        setPeriods(pd?.periods || []);
        setVwords(vw?.data || []);
        setUsers(ud?.data || []);
      } catch (e) {
        message.error('主数据加载失败：' + (e.response?.data?.detail || e.message));
      }
    })();
  }, [message]);

  const wordById = useMemo(() => new Map(vwords.map((w) => [w.id, w])), [vwords]);
  const userById = useMemo(() => new Map(users.map((u) => [u.id, u])), [users]);
  const userLabel = useCallback((id) => {
    if (!id) return null;
    const u = userById.get(id);
    return u ? (u.full_name || u.username || `#${id}`) : `#${id}`;
  }, [userById]);

  const runQuery = useCallback(async () => {
    setLoading(true);
    try {
      // 等值条件下推后端 filters；范围/关键字前端二次筛。
      const filters = {};
      if (periodId) filters.period_id = periodId;
      if (vwordId) filters.voucher_word_id = vwordId;
      if (status) filters.status = status;
      if (createdById) filters.created_by_id = createdById;
      const { data } = await query('voucher', { filters, order_by: '-id', limit: 1000 });
      let list = data?.data || [];

      // 前端二次筛：金额区间（借方合计口径）/ 摘要+凭证号关键字 / 日期区间。
      const lo = num(amountMin), hi = num(amountMax);
      const s = kw.trim().toLowerCase();
      const [df, dt] = dateRange || [];
      const dfStr = df ? df.format('YYYY-MM-DD') : null;
      const dtStr = dt ? dt.format('YYYY-MM-DD') : null;
      list = list.filter((v) => {
        const amt = num(v.total_debit);
        if (amountMin != null && amt < lo) return false;
        if (amountMax != null && amt > hi) return false;
        if (s) {
          const hay = `${v.voucher_number || ''} ${v.description || ''}`.toLowerCase();
          if (!hay.includes(s)) return false;
        }
        if (dfStr && String(v.voucher_date || '') < dfStr) return false;
        if (dtStr && String(v.voucher_date || '') > dtStr) return false;
        return true;
      });
      setRows(list);
      setLoaded(true);
    } catch (e) {
      message.error('凭证查询失败：' + (e.response?.data?.detail || e.message));
      setRows([]);
    } finally { setLoading(false); }
  }, [periodId, vwordId, status, createdById, amountMin, amountMax, kw, dateRange, message]);

  const resetFilters = () => {
    setPeriodId(null); setVwordId(null); setStatus(null); setCreatedById(null);
    setAmountMin(null); setAmountMax(null); setKw(''); setDateRange(null);
  };

  // 行抽屉：拉该凭证分录 join account。
  const openDrawer = useCallback(async (v) => {
    setDrawerVoucher(v);
    setDrawerOpen(true);
    setDrawerLoading(true);
    try {
      const { data: ed } = await query('voucher_entry', {
        filters: { voucher_id: v.id }, order_by: 'line_number', limit: 200,
      });
      const entries = ed?.data || [];
      const ids = [...new Set(entries.map((e) => e.account_id).filter(Boolean))];
      let acctById = new Map();
      if (ids.length) {
        const { data: ad } = await query('account', { order_by: 'code', limit: 1000 });
        acctById = new Map((ad?.data || []).map((a) => [a.id, a]));
      }
      setDrawerRows(entries.map((e) => {
        const a = acctById.get(e.account_id);
        return { ...e, _account_code: a?.code || '', _account_name: a?.name || `科目 #${e.account_id}` };
      }));
    } catch (e) {
      message.error('分录加载失败：' + (e.response?.data?.detail || e.message));
      setDrawerRows([]);
    } finally { setDrawerLoading(false); }
  }, [message]);

  const drill = (v) => navigate(`/finance/voucher?id=${v.id}`);

  const onTemplateCreated = (vid) => {
    setPickerOpen(false);
    if (vid) navigate(`/finance/voucher?id=${vid}`);
  };

  const totals = useMemo(() => {
    let d = 0, c = 0;
    for (const v of rows) { d += num(v.total_debit); c += num(v.total_credit); }
    return { d: Math.round(d * 100) / 100, c: Math.round(c * 100) / 100 };
  }, [rows]);

  const drawerTotals = useMemo(() => {
    let d = 0, c = 0;
    for (const e of drawerRows) { d += num(e.base_debit); c += num(e.base_credit); }
    return { d: Math.round(d * 100) / 100, c: Math.round(c * 100) / 100 };
  }, [drawerRows]);

  const columns = [
    {
      title: '凭证号', dataIndex: 'voucher_number', width: 130, fixed: 'left',
      render: (v) => <span style={{ fontFamily: MONO }}>{v}</span>,
    },
    { title: '日期', dataIndex: 'voucher_date', width: 110 },
    {
      title: '字', dataIndex: 'voucher_word_id', width: 70,
      render: (id) => { const w = wordById.get(id); return w ? <Tag>{w.code}</Tag> : <span style={{ color: '#bfbbb5' }}>—</span>; },
    },
    {
      title: '摘要', dataIndex: 'description', width: 200, ellipsis: true,
      render: (v) => v || <span style={{ color: '#bfbbb5' }}>—</span>,
    },
    { title: '借方合计', dataIndex: 'total_debit', width: 130, align: 'right', render: money },
    { title: '贷方合计', dataIndex: 'total_credit', width: 130, align: 'right', render: money },
    {
      title: '状态', dataIndex: 'status', width: 100,
      render: (v) => { const m = STATUS_META[v] || { label: v, color: 'default' }; return <Tag color={m.color}>{m.label}</Tag>; },
    },
    { title: '制单', dataIndex: 'created_by_id', width: 100, render: (id) => userLabel(id) || <span style={{ color: '#bfbbb5' }}>—</span> },
    { title: '审核', dataIndex: 'audited_by_id', width: 100, render: (id) => userLabel(id) || <span style={{ color: '#bfbbb5' }}>—</span> },
    { title: '过账人', dataIndex: 'posted_by_id', width: 100, render: (id) => userLabel(id) || <span style={{ color: '#bfbbb5' }}>—</span> },
    {
      title: '操作', dataIndex: '_a', width: 130, fixed: 'right',
      render: (_, v) => (
        <Space size={0}>
          <Button type="link" size="small" onClick={() => openDrawer(v)}>分录</Button>
          <Button type="link" size="small" onClick={() => drill(v)}>打开</Button>
        </Space>
      ),
    },
  ];

  return (
    <div>
      <div style={{ marginBottom: 16, display: 'flex', alignItems: 'baseline', gap: 12, flexWrap: 'wrap' }}>
        <h2 style={{ fontSize: 26, fontWeight: 300, letterSpacing: '-0.01em', color: '#000', margin: 0, lineHeight: 1.2 }}>
          凭证查询
        </h2>
        <span style={{ color: '#777169', fontSize: 13 }}>
          财务 / 总账 · 全量凭证台账 · 多维筛选 + 分录抽屉 + 下钻录入页 · 账簿 = 当前公司（后端按会话隔离）
        </span>
      </div>

      {/* 筛选条 */}
      <Card size="small" style={{ borderRadius: 14, marginBottom: 14 }}>
        <Space wrap size={16} align="end">
          <Col label="账簿 / 核算组织">
            <Tag color="geekblue">{user?.company_name || `公司 #${user?.company_id ?? ''}`}</Tag>
          </Col>
          <Col label="会计期间">
            <Select size="small" value={periodId} allowClear style={{ width: 170 }} onChange={setPeriodId}
              options={periods.map((p) => ({ value: p.id, label: `${p.label}${p.status !== 'OPEN' ? `（${p.status}）` : ''}` }))}
              placeholder="全部期间" />
          </Col>
          <Col label="凭证字">
            <Select size="small" value={vwordId} allowClear style={{ width: 120 }} onChange={setVwordId}
              options={vwords.map((w) => ({ value: w.id, label: `${w.code} ${w.name}` }))}
              placeholder="全部" />
          </Col>
          <Col label="状态">
            <Select size="small" value={status} allowClear style={{ width: 130 }} onChange={setStatus}
              options={STATUS_OPTIONS} placeholder="全部状态" />
          </Col>
          <Col label="制单人">
            <Select size="small" value={createdById} allowClear showSearch optionFilterProp="label"
              style={{ width: 150 }} onChange={setCreatedById}
              options={users.map((u) => ({ value: u.id, label: u.full_name || u.username || `#${u.id}` }))}
              placeholder="全部" />
          </Col>
          <Col label="金额区间（借方合计）">
            <Space.Compact>
              <InputNumber size="small" value={amountMin} onChange={setAmountMin} placeholder="最小" style={{ width: 110 }} controls={false} />
              <InputNumber size="small" value={amountMax} onChange={setAmountMax} placeholder="最大" style={{ width: 110 }} controls={false} />
            </Space.Compact>
          </Col>
          <Col label="日期区间">
            <RangePicker size="small" value={dateRange} onChange={setDateRange} style={{ width: 230 }} />
          </Col>
          <Col label="摘要 / 凭证号关键字">
            <Input size="small" value={kw} onChange={(e) => setKw(e.target.value)} allowClear
              prefix={<SearchOutlined />} placeholder="模糊匹配" style={{ width: 180 }} />
          </Col>
          <Button type="primary" size="small" icon={<SearchOutlined />} loading={loading} onClick={runQuery}>查询</Button>
          <Button size="small" icon={<ReloadOutlined />} onClick={resetFilters}>重置</Button>
          <Button size="small" type="dashed" icon={<PlusOutlined />} onClick={() => setPickerOpen(true)}>从模板新建</Button>
        </Space>
      </Card>

      {/* 凭证台账 */}
      <Card size="small" style={{ borderRadius: 14 }} styles={{ body: { padding: 0 } }}>
        {!loaded ? (
          <Empty style={{ padding: 40 }} description="设置筛选条件后点「查询」" />
        ) : (
          <Table
            size="small"
            rowKey="id"
            loading={loading}
            dataSource={rows}
            columns={columns}
            onRow={(v) => ({ onClick: () => openDrawer(v), style: { cursor: 'pointer' } })}
            pagination={{ pageSize: 30, showSizeChanger: true, showTotal: (t) => `共 ${t} 张凭证` }}
            scroll={{ x: 'max-content', y: 'calc(100vh - 380px)' }}
            sticky
            summary={() => (
              <Table.Summary fixed>
                <Table.Summary.Row style={{ background: 'rgba(245,242,239,0.6)', fontWeight: 600 }}>
                  <Table.Summary.Cell index={0} colSpan={4}>合计（{rows.length} 张）</Table.Summary.Cell>
                  <Table.Summary.Cell index={4} align="right">{fmtMoney(totals.d)}</Table.Summary.Cell>
                  <Table.Summary.Cell index={5} align="right">{fmtMoney(totals.c)}</Table.Summary.Cell>
                  <Table.Summary.Cell index={6} colSpan={5} />
                </Table.Summary.Row>
              </Table.Summary>
            )}
          />
        )}
      </Card>

      {/* 分录抽屉 */}
      <Drawer
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        width={880}
        title={drawerVoucher ? `凭证分录 · ${drawerVoucher.voucher_number}` : '凭证分录'}
        extra={drawerVoucher && (
          <Button type="primary" size="small" onClick={() => drill(drawerVoucher)}>打开录入页编辑</Button>
        )}
      >
        {drawerVoucher && (
          <Descriptions size="small" column={3} style={{ marginBottom: 12 }} styles={{ label: { color: '#777169' } }}>
            <Descriptions.Item label="日期">{drawerVoucher.voucher_date}</Descriptions.Item>
            <Descriptions.Item label="凭证字">{wordById.get(drawerVoucher.voucher_word_id)?.code || '—'}</Descriptions.Item>
            <Descriptions.Item label="状态">
              {(() => { const m = STATUS_META[drawerVoucher.status] || { label: drawerVoucher.status, color: 'default' }; return <Tag color={m.color}>{m.label}</Tag>; })()}
            </Descriptions.Item>
            <Descriptions.Item label="摘要" span={3}>{drawerVoucher.description || '—'}</Descriptions.Item>
            <Descriptions.Item label="制单">{userLabel(drawerVoucher.created_by_id) || '—'}</Descriptions.Item>
            <Descriptions.Item label="审核">{userLabel(drawerVoucher.audited_by_id) || '—'}</Descriptions.Item>
            <Descriptions.Item label="过账人">{userLabel(drawerVoucher.posted_by_id) || '—'}</Descriptions.Item>
          </Descriptions>
        )}
        <Table
          size="small"
          rowKey="id"
          loading={drawerLoading}
          dataSource={drawerRows}
          pagination={false}
          scroll={{ x: 'max-content' }}
          columns={[
            { title: '行', dataIndex: 'line_number', width: 44 },
            { title: '摘要', dataIndex: 'description', width: 180, render: (v) => v || <span style={{ color: '#bfbbb5' }}>—</span> },
            { title: '科目码', dataIndex: '_account_code', width: 100, render: (v) => <span style={{ fontFamily: MONO }}>{v || '—'}</span> },
            { title: '科目名称', dataIndex: '_account_name', width: 160 },
            { title: '借方（本位币）', dataIndex: 'base_debit', width: 130, align: 'right', render: money },
            { title: '贷方（本位币）', dataIndex: 'base_credit', width: 130, align: 'right', render: money },
          ]}
          summary={() => (
            <Table.Summary fixed>
              <Table.Summary.Row style={{ background: 'rgba(245,242,239,0.5)', fontWeight: 600 }}>
                <Table.Summary.Cell index={0} colSpan={4}>合计</Table.Summary.Cell>
                <Table.Summary.Cell index={4} align="right">{fmtMoney(drawerTotals.d)}</Table.Summary.Cell>
                <Table.Summary.Cell index={5} align="right">{fmtMoney(drawerTotals.c)}</Table.Summary.Cell>
              </Table.Summary.Row>
            </Table.Summary>
          )}
        />
        <div style={{ marginTop: 10, fontSize: 12, color: '#777169' }}>
          借贷{Math.abs(drawerTotals.d - drawerTotals.c) < 0.005
            ? <Tag color="green" style={{ marginLeft: 6 }}>平衡 ✓</Tag>
            : <Tag color="red" style={{ marginLeft: 6 }}>差额 {fmtMoney(drawerTotals.d - drawerTotals.c)}</Tag>}
        </div>
      </Drawer>

      <ModelVoucherPickerModal
        open={pickerOpen}
        onCancel={() => setPickerOpen(false)}
        onCreated={onTemplateCreated}
      />
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
