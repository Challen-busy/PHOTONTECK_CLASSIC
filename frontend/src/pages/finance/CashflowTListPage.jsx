/**
 * CashflowTListPage —— 现金流量 T 型账（总账·finance-gl wave-6，前端A·现金流量 PM）
 *
 * 调 GET /api/reports/cashflow-tlist（后端 reports.py wave-6）。与「现金流量表」（标准三栏表）互补：
 *   T 型账以「流入 | 流出」左右两栏直观呈现各现金流量项目的资金来去，便于资金分析。
 *
 *   头：账簿（当前公司，只读）+ 会计期间。
 *   主体：经营 / 投资 / 筹资三大类锚点（父项加粗）→ 子项目挂下；每行左借（流入 inflow）右贷（流出 outflow），
 *         本期 + 本年累计两套数；大类小计 + 三大合计 + 净现金流量（净额 = 流入 − 流出，正绿负红）。
 *
 * 取数底座（与后端一致，本页不二次加工）：已过账（POSTED）+ 已标 cashflow_item_id 的现金对手分录归集；
 *   金额 = |base_debit − base_credit|，按项目 direction 计入流入/流出栏。未标 / 未过账不进 T 型账（去「现金流量指定」补标后再看）。
 *
 * 空数据 / 端点 404 优雅降级。★禁碰 App.jsx / Layout.jsx / api.js（routesToWire 返回）。
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { App, Card, Select, Tag, Empty, Alert, Spin, Segmented } from 'antd';
import { useAuth } from '../../auth';
import { getAccountingPeriods, getCashflowTList } from '../../api';
import { MONO, fmtMoney } from './financeHelpers';

export default function CashflowTListPage() {
  const { user } = useAuth();
  const { message } = App.useApp();

  const [periods, setPeriods] = useState([]);
  const [periodId, setPeriodId] = useState(null);
  const [report, setReport] = useState(null);
  const [loading, setLoading] = useState(false);
  const [notReady, setNotReady] = useState(false);
  const [scope, setScope] = useState('period');  // period | ytd 显示口径切换

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

  const runQuery = useCallback(async () => {
    if (!periodId || !user?.company_id) return;
    setLoading(true);
    setNotReady(false);
    try {
      const { data } = await getCashflowTList({ company_id: user.company_id, period_id: periodId });
      if (data?.error) { message.warning(data.error); setReport(null); }
      else setReport(data);
    } catch (e) {
      if (e.response?.status === 404) { setNotReady(true); setReport(null); }
      else { message.error('现金流量 T 型账查询失败：' + (e.response?.data?.detail || e.message)); setReport(null); }
    } finally { setLoading(false); }
  }, [periodId, user, message]);

  useEffect(() => { if (periodId && user?.company_id) runQuery(); }, [periodId, user, runQuery]);

  const periodLabel = useMemo(() => {
    const p = periods.find((x) => x.id === periodId);
    return p ? p.label : (periodId ? `期间 #${periodId}` : '—');
  }, [periods, periodId]);

  // period | ytd 取数小工具：从行/小计对象按当前 scope 取流入/流出。
  const inOf = useCallback((o) => Number((scope === 'ytd' ? o?.inflow_ytd : o?.inflow_period) || 0), [scope]);
  const outOf = useCallback((o) => Number((scope === 'ytd' ? o?.outflow_ytd : o?.outflow_period) || 0), [scope]);

  const activities = report?.data?.activities || [];
  const totalIn = report?.data?.total_inflow;
  const totalOut = report?.data?.total_outflow;
  const net = report?.data?.net_cashflow;
  const netVal = net ? Number(scope === 'ytd' ? net.ytd : net.period) : 0;

  return (
    <div>
      <div style={{ marginBottom: 16, display: 'flex', alignItems: 'baseline', gap: 12, flexWrap: 'wrap' }}>
        <h2 style={{ fontSize: 26, fontWeight: 300, letterSpacing: '-0.01em', color: '#000', margin: 0, lineHeight: 1.2 }}>
          现金流量 T 型账
        </h2>
        <span style={{ color: '#777169', fontSize: 13 }}>
          财务 / 总账 · Cash Flow T-Account · 各现金流量项目「流入 | 流出」T 型直观呈现 · 经营 / 投资 / 筹资三大类
        </span>
      </div>

      {/* 筛选条 */}
      <Card size="small" style={{ borderRadius: 14, marginBottom: 14 }}>
        <div style={{ display: 'flex', gap: 24, alignItems: 'flex-end', flexWrap: 'wrap' }}>
          <Field label="账簿 / 核算组织（当前公司）">
            <Tag color="geekblue">{user?.company_name || `公司 #${user?.company_id ?? ''}`}</Tag>
          </Field>
          <Field label="会计期间">
            <Select size="small" value={periodId} style={{ width: 200 }} onChange={setPeriodId} loading={!periods.length}
              options={periods.map((p) => ({ value: p.id, label: `${p.label}${p.status !== 'OPEN' ? `（${p.status}）` : ''}` }))}
              placeholder="选择期间" />
          </Field>
          <Field label="口径">
            <Segmented size="small" value={scope} onChange={setScope}
              options={[{ value: 'period', label: '本期数' }, { value: 'ytd', label: '本年累计' }]} />
          </Field>
          {report?.currency && (
            <Field label="本位币">
              <Tag>{report.currency}</Tag>
            </Field>
          )}
        </div>
      </Card>

      {notReady ? (
        <Card size="small" style={{ borderRadius: 14 }}>
          <Alert type="warning" showIcon style={{ borderRadius: 10 }}
            message="现金流量 T 型账端点待后端开通"
            description="GET /api/reports/cashflow-tlist 暂未就绪（404）。前端已按契约对齐，端点上线后本页自动出表。" />
        </Card>
      ) : (
        <Spin spinning={loading}>
          {!report ? (
            <Card size="small" style={{ borderRadius: 14 }}>
              <Empty style={{ padding: 40 }} description="选择会计期间后自动出表" />
            </Card>
          ) : (
            <Card size="small" style={{ borderRadius: 14 }} styles={{ body: { padding: 0 } }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13.5 }}>
                <thead>
                  <tr style={{ borderBottom: '1px solid #efece8', background: 'rgba(245,242,239,0.5)' }}>
                    <th style={{ textAlign: 'left', padding: '10px 16px', fontWeight: 500, color: '#777169' }}>现金流量项目</th>
                    <th style={{ textAlign: 'center', padding: '10px 8px', fontWeight: 500, color: '#777169', width: 56 }}>方向</th>
                    <th style={{ textAlign: 'right', padding: '10px 16px', fontWeight: 500, color: '#1f8f3a', width: 200, borderLeft: '1px solid #efece8' }}>
                      流入（借）
                    </th>
                    <th style={{ textAlign: 'right', padding: '10px 16px', fontWeight: 500, color: '#b42318', width: 200, borderLeft: '1px solid #efece8' }}>
                      流出（贷）
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {activities.length === 0 && (
                    <tr><td colSpan={4} style={{ padding: 30 }}>
                      <Empty image={Empty.PRESENTED_IMAGE_SIMPLE}
                        description="本期无现金流量数据（需已过账 + 已标现金流量项目；先到「现金流量指定」补标）" />
                    </td></tr>
                  )}
                  {activities.map((act) => (
                    <ActivityBlock key={act.item_id} activity={act} inOf={inOf} outOf={outOf} />
                  ))}

                  {/* 三大合计 */}
                  {(totalIn || totalOut) && (
                    <tr style={{ borderTop: '2px solid #d9d4cd', background: 'rgba(245,242,239,0.6)' }}>
                      <td colSpan={2} style={{ padding: '11px 16px', fontWeight: 700 }}>合计</td>
                      <TCell value={inOf(totalIn)} side="in" bold />
                      <TCell value={outOf(totalOut)} side="out" bold />
                    </tr>
                  )}
                  {/* 净现金流量 */}
                  {net && (
                    <tr style={{ borderTop: '1px solid #d9d4cd', background: 'rgba(245,242,239,0.85)' }}>
                      <td colSpan={2} style={{ padding: '12px 16px', fontWeight: 700 }}>
                        现金及现金等价物净增加额（流入 − 流出）
                      </td>
                      <td colSpan={2} style={{
                        padding: '12px 16px', textAlign: 'right', fontFamily: MONO, fontWeight: 700, fontSize: 15,
                        color: netVal < 0 ? '#b42318' : (netVal > 0 ? '#1f8f3a' : '#3a3733'),
                      }}>
                        {netVal === 0 ? '0.00' : (netVal > 0 ? `净流入 ${fmtMoney(netVal)}` : `净流出 ${fmtMoney(Math.abs(netVal))}`)}
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </Card>
          )}
          {report && (
            <div style={{ marginTop: 10, color: '#a8a39c', fontSize: 12 }}>
              {report.company_code} · {periodLabel}（第 {report.period_number} 期）· 单位：{report.currency} ·
              {scope === 'ytd' ? ' 本年累计' : ' 本期数'} · 已过账 + 已标现金流量项目归集（金额 = |本位币借 − 贷|）
            </div>
          )}
        </Spin>
      )}
    </div>
  );
}

// 三大类活动块：顶层小计（加粗）+ 子项目（缩进）。每行左流入右流出 T 型。
function ActivityBlock({ activity, inOf, outOf }) {
  const sub = activity.subtotal || {};
  return (
    <>
      <tr style={{ borderTop: '1px solid #efece8', background: 'rgba(245,242,239,0.35)' }}>
        <td style={{ padding: '8px 16px', fontWeight: 600 }}>
          <span style={{ fontFamily: MONO, color: '#bfbbb5', fontSize: 11, marginRight: 6 }}>{activity.code}</span>
          {activity.name}
        </td>
        <td style={{ textAlign: 'center' }}><DirTag dir={activity.direction} /></td>
        <TCell value={inOf(sub)} side="in" semi />
        <TCell value={outOf(sub)} side="out" semi />
      </tr>
      {(activity.lines || []).map((ln) => (
        <tr key={ln.item_id} style={{ borderTop: '1px solid #f6f4f1' }}>
          <td style={{ padding: '6px 16px 6px 32px', color: '#3a3733' }}>
            <span style={{ fontFamily: MONO, color: '#bfbbb5', fontSize: 11, marginRight: 6 }}>{ln.code}</span>
            {ln.name}
          </td>
          <td style={{ textAlign: 'center' }}><DirTag dir={ln.direction} /></td>
          <TCell value={inOf(ln)} side="in" />
          <TCell value={outOf(ln)} side="out" />
        </tr>
      ))}
    </>
  );
}

function DirTag({ dir }) {
  if (dir === 'IN') return <Tag color="green" style={{ margin: 0 }}>流入</Tag>;
  if (dir === 'OUT') return <Tag color="volcano" style={{ margin: 0 }}>流出</Tag>;
  return <span style={{ color: '#d9d4cd' }}>—</span>;
}

// T 型账金额单元：流入栏绿、流出栏红（仅在该栏有值时着色），0 占位破折号。带左竖线分隔借贷两栏。
function TCell({ value, side, bold, semi }) {
  const n = Number(value);
  const color = n ? (side === 'in' ? '#1f8f3a' : '#b42318') : '#d9d4cd';
  return (
    <td style={{
      padding: bold ? '11px 16px' : '6px 16px',
      textAlign: 'right', fontFamily: MONO,
      fontWeight: bold ? 700 : (semi ? 600 : 400),
      color, borderLeft: '1px solid #f3f0ec',
    }}>
      {n ? fmtMoney(value) : '—'}
    </td>
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
