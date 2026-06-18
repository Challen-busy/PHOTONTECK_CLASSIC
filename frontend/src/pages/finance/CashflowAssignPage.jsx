/**
 * CashflowAssignPage —— 现金流量项目指定 / 批量预设（总账·finance-gl wave-6，前端A·现金流量 PM）
 *
 * 现金流量靠 VoucherEntry.cashflow_item_id 标记。本页解决「凭证已记账但现金流量项目未标 → 现金流量表 0 流量」：
 *   1) 选会计期间 → 用 /api/reports/cashflow-query（status=ALL）拉本期所有已标 / 未标的现金类凭证分录；
 *      列出含现金类科目（1001/1002…）凭证的对手分录，逐条挂 cashflow_item（写回 voucher_entry.cashflow_item_id）。
 *   2) 批量预设（本页核心写动作）：调 finance.assign_cashflow（按规则补标对手分录），支持单张 voucher_id 或整期 period_id；
 *      回执给出 scanned / cash_vouchers / marked / unclassified + 逐凭证逐行命中规则明细。
 *   3) 单凭证预设：行内「单张预设」按规则补标该凭证；规则未命中 / 需改判 → 下钻凭证录入页手工挂
 *      （cashflow_item_id 的逐行手工写归 VoucherEntryPage 的 AuxAccountingModal，走引擎 VOUCHER 唯一写入路径，本页不重复造写）。
 *
 * 取数底座（与后端一致，本页不二次加工现金流量表口径）：
 *   · 现金类科目 = Account.code 以 1001(库存现金)/1002(银行存款) 等开头，balance_direction=DEBIT；现金流量=对手方分录归集到 cashflow_item。
 *   · cashflow_item 树（经营/投资/筹资），direction IN|OUT；可查表 cashflow_item（后端 _company_filter 隔离）。
 *
 * 写口径说明（命令唯一写 + 不造假）：finance.assign_cashflow 契约是「按规则补标」，不收逐行显式 item_id；
 *   故本页的写 = 规则批量/单张预设；逐行人工指定改判走凭证录入页 AuxAccountingModal（VOUCHER 写路径），本页提供下钻入口。
 *
 * ★禁碰 App.jsx / Layout.jsx / api.js —— 路由/导航/api 方法签名以 routesToWire 返回，主 agent 统一接。
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  App, Card, Select, Tag, Button, Space, Table, Empty, Spin, Descriptions, Switch, Tooltip, Alert,
} from 'antd';
import {
  ThunderboltOutlined, ReloadOutlined, EditOutlined, CheckCircleTwoTone,
} from '@ant-design/icons';
import { useAuth } from '../../auth';
import { getAccountingPeriods, getCashflowQuery, assignCashflow, query as apiQuery } from '../../api';
import { MONO, fmtMoney } from './financeHelpers';

// 凭证状态语义（与凭证查询页一致）。
const STATUS_META = {
  DRAFT: { label: '草稿', color: 'default' },
  AUDITED: { label: '已审核', color: 'blue' },
  REVIEWED: { label: '出纳已复核', color: 'cyan' },
  POSTED: { label: '已过账', color: 'green' },
};

export default function CashflowAssignPage() {
  const { user } = useAuth();
  const { message, modal } = App.useApp();
  const navigate = useNavigate();

  const [periods, setPeriods] = useState([]);
  const [periodId, setPeriodId] = useState(null);
  const [cashflowItems, setCashflowItems] = useState([]);

  const [rows, setRows] = useState([]);          // 现金类凭证对手分录行（cashflow-query rows）
  const [loading, setLoading] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [presetVid, setPresetVid] = useState(null);   // 正在单张预设的 voucher_id
  const [onlyUnmarked, setOnlyUnmarked] = useState(false);

  // 批量预设回执
  const [busy, setBusy] = useState(false);
  const [overwrite, setOverwrite] = useState(false);
  const [receipt, setReceipt] = useState(null);

  // 主数据：期间 + 现金流量项目。
  useEffect(() => {
    (async () => {
      try {
        const [{ data: pd }, { data: cf }] = await Promise.all([
          getAccountingPeriods(),
          apiQuery('cashflow_item', { filters: { is_active: true }, order_by: 'code', limit: 500 }),
        ]);
        const ps = pd?.periods || [];
        setPeriods(ps);
        setCashflowItems(cf?.data || []);
        const open = ps.find((p) => p.status === 'OPEN') || ps[0];
        if (open) setPeriodId(open.id);
      } catch (e) {
        message.error('主数据加载失败：' + (e.response?.data?.detail || e.message));
      }
    })();
  }, [message]);

  const itemById = useMemo(() => new Map(cashflowItems.map((c) => [c.id, c])), [cashflowItems]);

  // 行 key：voucher_id + line_number 唯一。
  const rowKey = (r) => `${r.voucher_id}-${r.line_number}`;

  // 拉本期现金类凭证对手分录（status=ALL 含草稿，方便记账后即标）。
  const runQuery = useCallback(async () => {
    if (!periodId || !user?.company_id) return;
    setLoading(true);
    setReceipt(null);
    try {
      const { data } = await getCashflowQuery({ company_id: user.company_id, period_id: periodId, status: 'ALL' });
      setRows(data?.rows || []);
      setLoaded(true);
    } catch (e) {
      if (e.response?.status === 404) {
        message.warning('现金流量查询端点待后端开通（404）');
        setRows([]); setLoaded(true);
      } else {
        message.error('现金流量分录查询失败：' + (e.response?.data?.detail || e.message));
        setRows([]);
      }
    } finally { setLoading(false); }
  }, [periodId, user, message]);

  useEffect(() => { if (periodId && user?.company_id) runQuery(); }, [periodId, user, runQuery]);

  // 单张凭证按规则预设：补标该凭证对手分录的现金流量项目（finance.assign_cashflow voucher_id）。
  const presetOne = useCallback(async (r) => {
    setPresetVid(r.voucher_id);
    try {
      const { data } = await assignCashflow({ voucher_id: r.voucher_id, overwrite });
      const res = (data?.results || [])[0];
      if (data?.marked) message.success(data.message || `已补标 ${data.marked} 行`);
      else if (res && res.unclassified) message.warning(`该凭证 ${res.unclassified} 行未命中规则，请下钻录入页手工指定`);
      else message.info(data?.message || '该凭证无需补标 / 已标');
      await runQuery();
    } catch (e) {
      message.error('单张预设失败：' + (e.response?.data?.detail || e.message));
    } finally { setPresetVid(null); }
  }, [overwrite, message, runQuery]);

  // 下钻凭证录入页手工挂现金流量项目（逐行写归 AuxAccountingModal，VOUCHER 唯一写路径）。
  const drillEntry = useCallback((r) => navigate(`/finance/voucher?id=${r.voucher_id}`), [navigate]);

  // 批量预设：整期按规则补标。
  const runBatch = useCallback(() => {
    if (!periodId || !user?.company_id) return;
    modal.confirm({
      title: '按规则批量预设本期现金流量项目',
      content: `将扫描 ${periodLabel()} 全部含现金类科目的凭证，按现金流量规则自动补标对手分录的现金流量项目。${overwrite ? '【覆盖模式】已标项目也会被规则结果覆盖。' : '默认仅补标未标项目（已标不动）。'}`,
      okText: '执行批量预设',
      onOk: async () => {
        setBusy(true);
        setReceipt(null);
        try {
          const { data } = await assignCashflow({ period_id: periodId, company_id: user.company_id, overwrite });
          setReceipt(data);
          message.success(data?.message || `批量预设完成：补标 ${data?.marked ?? 0} 行`);
          await runQuery();
        } catch (e) {
          message.error('批量预设失败：' + (e.response?.data?.detail || e.message));
        } finally { setBusy(false); }
      },
    });
    // eslint-disable-next-line
  }, [periodId, user, overwrite, modal, message, runQuery]);

  const periodLabel = useCallback(() => {
    const p = periods.find((x) => x.id === periodId);
    return p ? p.label : (periodId ? `期间 #${periodId}` : '—');
  }, [periods, periodId]);

  // 可见行（仅未标过滤）。
  const visibleRows = useMemo(
    () => (onlyUnmarked ? rows.filter((r) => !r.cashflow_item_id) : rows),
    [rows, onlyUnmarked],
  );

  const stat = useMemo(() => {
    const marked = rows.filter((r) => r.cashflow_item_id).length;
    return { total: rows.length, marked, unmarked: rows.length - marked };
  }, [rows]);

  const columns = [
    {
      title: '凭证号', dataIndex: 'voucher_number', width: 150, fixed: 'left',
      render: (v, r) => (
        <span style={{ fontFamily: MONO }}>
          {v || `#${r.voucher_id}`}<span style={{ color: '#bfbbb5', marginLeft: 4 }}>·{r.line_number}</span>
        </span>
      ),
    },
    { title: '日期', dataIndex: 'voucher_date', width: 105 },
    {
      title: '状态', dataIndex: 'voucher_status', width: 92,
      render: (v) => { const mt = STATUS_META[v] || { label: v, color: 'default' }; return <Tag color={mt.color}>{mt.label}</Tag>; },
    },
    {
      title: '科目', dataIndex: 'account_code', width: 200,
      render: (v, r) => (
        <span><span style={{ fontFamily: MONO, color: '#777169', marginRight: 6 }}>{v}</span>{r.account_name}</span>
      ),
    },
    { title: '摘要', dataIndex: 'description', width: 180, ellipsis: true, render: (v) => v || <Dash /> },
    { title: '借方（本位币）', dataIndex: 'base_debit', width: 130, align: 'right', render: money },
    { title: '贷方（本位币）', dataIndex: 'base_credit', width: 130, align: 'right', render: money },
    {
      title: '现金流量项目', dataIndex: 'cashflow_item_id', width: 280,
      render: (cur, r) => {
        if (!cur) return <Tag color="warning" style={{ margin: 0 }}>未标</Tag>;
        const it = itemById.get(cur);
        const code = r.cashflow_item_code || it?.code || '';
        const name = r.cashflow_item_name || it?.name || `#${cur}`;
        return (
          <Space size={6}>
            <CheckCircleTwoTone twoToneColor="#1f8f3a" />
            <span><span style={{ fontFamily: MONO, color: '#777169', marginRight: 4 }}>{code}</span>{name}</span>
            <DirTag dir={r.cashflow_direction || it?.direction} />
          </Space>
        );
      },
    },
    {
      title: '操作', dataIndex: '_a', width: 168, fixed: 'right',
      render: (_, r) => (
        <Space size={0}>
          <Tooltip title="按规则补标该凭证对手分录的现金流量项目">
            <Button
              type="link" size="small" icon={<ThunderboltOutlined />}
              loading={presetVid === r.voucher_id} onClick={() => presetOne(r)}
            >单张预设</Button>
          </Tooltip>
          <Tooltip title="下钻凭证录入页手工挂 / 改判现金流量项目">
            <Button type="link" size="small" icon={<EditOutlined />} onClick={() => drillEntry(r)}>手工</Button>
          </Tooltip>
        </Space>
      ),
    },
  ];

  return (
    <div>
      <div style={{ marginBottom: 16, display: 'flex', alignItems: 'baseline', gap: 12, flexWrap: 'wrap' }}>
        <h2 style={{ fontSize: 26, fontWeight: 300, letterSpacing: '-0.01em', color: '#000', margin: 0, lineHeight: 1.2 }}>
          现金流量指定
        </h2>
        <span style={{ color: '#777169', fontSize: 13 }}>
          财务 / 总账 · 给现金类凭证对手分录挂现金流量项目（经营 / 投资 / 筹资）· 单条手工 或 <code>finance.assign_cashflow</code> 整期按规则批量预设
        </span>
      </div>

      {/* 头：账簿 + 期间 + 批量预设 */}
      <Card size="small" style={{ borderRadius: 14, marginBottom: 12 }}>
        <Space size={24} wrap align="end">
          <Field label="账簿 / 核算组织（当前公司）">
            <Tag color="geekblue">{user?.company_name || `公司 #${user?.company_id ?? ''}`}</Tag>
          </Field>
          <Field label="会计期间">
            <Select
              size="small" value={periodId} style={{ width: 200 }} onChange={setPeriodId} loading={!periods.length}
              options={periods.map((p) => ({ value: p.id, label: `${p.label}${p.status !== 'OPEN' ? `（${p.status}）` : ''}` }))}
              placeholder="选择期间"
            />
          </Field>
          <Field label="仅看未标">
            <Switch checked={onlyUnmarked} onChange={setOnlyUnmarked} checkedChildren="未标" unCheckedChildren="全部" />
          </Field>
          <Field label="覆盖已标（批量预设）">
            <Switch checked={overwrite} onChange={setOverwrite} checkedChildren="覆盖" unCheckedChildren="保留" />
          </Field>
          <Button icon={<ReloadOutlined />} loading={loading} onClick={runQuery}>刷新</Button>
          <Tooltip title="按现金流量规则扫描本期含现金类科目的凭证，自动补标对手分录的现金流量项目">
            <Button type="primary" icon={<ThunderboltOutlined />} loading={busy} disabled={!periodId} onClick={runBatch}>
              整期按规则批量预设
            </Button>
          </Tooltip>
        </Space>
      </Card>

      {/* 统计条 */}
      {loaded && (
        <div style={{ marginBottom: 10, display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'center', color: '#777169', fontSize: 12.5 }}>
          <Tag>现金分录 {stat.total}</Tag>
          <Tag color="green">已标 {stat.marked}</Tag>
          <Tag color={stat.unmarked ? 'warning' : 'default'}>未标 {stat.unmarked}</Tag>
          <span>口径：现金类科目（1001/1002…）凭证的对手分录归集到现金流量项目；标后到「现金流量表 / T 型账」出表。</span>
        </div>
      )}

      {/* 批量预设回执 */}
      {receipt && <BatchReceipt receipt={receipt} itemById={itemById} />}

      {/* 现金分录台账 */}
      <Card size="small" style={{ borderRadius: 14 }} styles={{ body: { padding: 0 } }}>
        {!loaded ? (
          <Empty style={{ padding: 40 }} description="选择会计期间后自动列出现金类凭证分录" />
        ) : (
          <Spin spinning={loading}>
            <Table
              size="small"
              rowKey={rowKey}
              dataSource={visibleRows}
              columns={columns}
              locale={{ emptyText: onlyUnmarked ? '本期无未标现金分录 ✓' : '本期无现金类凭证分录' }}
              pagination={{ pageSize: 25, showSizeChanger: true, showTotal: (t) => `共 ${t} 条现金分录` }}
              scroll={{ x: 'max-content', y: 'calc(100vh - 430px)' }}
              sticky
              rowClassName={(r) => (!r.cashflow_item_id ? 'cf-unmarked-row' : '')}
            />
          </Spin>
        )}
      </Card>

      <div style={{ marginTop: 10, color: '#a8a39c', fontSize: 12 }}>
        提示：「单张预设」与「整期批量预设」均按规则经命令 <code>finance.assign_cashflow</code> 落库（命令唯一写）。
        规则未命中或需改判的分录，点「手工」下钻凭证录入页逐行指定（VOUCHER 写路径）；亦可到「现金流量项目」补全规则后重跑。
      </div>

      {/* 未标行浅黄底高亮（局部样式，避免动全局 css） */}
      <style>{`.cf-unmarked-row > td { background: rgba(251,245,228,0.5); }`}</style>
    </div>
  );
}

/* ---- 批量预设回执 ---- */
function BatchReceipt({ receipt, itemById }) {
  const results = receipt.results || [];
  return (
    <Card size="small" style={{ borderRadius: 14, marginBottom: 12, background: 'rgba(245,242,239,0.5)' }}
      title={<span><ThunderboltOutlined /> 批量预设回执</span>}
      extra={<Tag color="geekblue">{receipt.scope === 'period' ? '整期' : '单张'}</Tag>}>
      <Descriptions size="small" column={5} style={{ marginBottom: 8 }}>
        <Descriptions.Item label="扫描凭证">{receipt.scanned ?? '—'}</Descriptions.Item>
        <Descriptions.Item label="含现金凭证">{receipt.cash_vouchers ?? '—'}</Descriptions.Item>
        <Descriptions.Item label="补标行数"><b style={{ color: '#1f8f3a' }}>{receipt.marked ?? 0}</b></Descriptions.Item>
        <Descriptions.Item label="未命中">
          {receipt.unclassified ? <b style={{ color: '#b8860b' }}>{receipt.unclassified}</b> : 0}
        </Descriptions.Item>
        <Descriptions.Item label="说明" span={5}>{receipt.message}</Descriptions.Item>
      </Descriptions>

      {receipt.unclassified ? (
        <Alert type="warning" showIcon style={{ borderRadius: 8, marginBottom: 8 }}
          message={`有 ${receipt.unclassified} 行未命中规则`}
          description="未命中的现金分录无法自动归集到现金流量项目；请在上方台账逐条手工指定，或到「现金流量项目」补全规则后重跑。" />
      ) : null}

      {results.length > 0 && (
        <Table
          size="small" rowKey={(r) => r.voucher_id} pagination={{ pageSize: 8, hideOnSinglePage: true }}
          dataSource={results}
          columns={[
            { title: '凭证', dataIndex: 'voucher_id', width: 90, render: (v) => <span style={{ fontFamily: MONO }}>#{v}</span> },
            {
              title: '现金方向', dataIndex: 'cash_direction', width: 90,
              render: (d) => <DirTag dir={d} />,
            },
            { title: '补标行', dataIndex: 'marked', width: 70, align: 'right' },
            {
              title: '未命中', dataIndex: 'unclassified', width: 70, align: 'right',
              render: (v) => (v ? <span style={{ color: '#b8860b' }}>{v}</span> : 0),
            },
            {
              title: '明细', dataIndex: 'lines',
              render: (lines) => (
                <Space size={[6, 4]} wrap>
                  {(lines || []).map((ln, i) => (
                    <Tag key={i} color={ln.item_id ? 'green' : 'default'} style={{ margin: 0 }}>
                      <span style={{ fontFamily: MONO }}>{ln.account_code}</span>
                      {ln.item_id
                        ? <> → {itemById.get(ln.item_id)?.code || ''} {itemById.get(ln.item_id)?.name || `#${ln.item_id}`}{ln.rule_code ? `（${ln.rule_code}）` : ''}</>
                        : <span style={{ color: '#b8860b' }}> · {ln.note || '未命中'}</span>}
                    </Tag>
                  ))}
                </Space>
              ),
            },
          ]}
        />
      )}
    </Card>
  );
}

/* ---- 小积木 ---- */
function DirTag({ dir }) {
  if (dir === 'IN') return <Tag color="green" style={{ margin: 0 }}>流入</Tag>;
  if (dir === 'OUT') return <Tag color="volcano" style={{ margin: 0 }}>流出</Tag>;
  return <span style={{ color: '#d9d4cd' }}>—</span>;
}
function money(v) {
  const n = Number(v);
  if (!n) return <Dash />;
  return <span style={{ fontFamily: MONO }}>{fmtMoney(v)}</span>;
}
function Dash() { return <span style={{ color: '#d9d4cd' }}>—</span>; }
function Field({ label, children }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
      <span style={{ fontSize: 11, color: '#777169' }}>{label}</span>
      {children}
    </div>
  );
}
