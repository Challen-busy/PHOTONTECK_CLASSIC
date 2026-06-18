/**
 * CashFlowStatementPage —— 现金流量表（总账·wave-5，owns by 前端A·三大财务报表 PM）
 *
 * 调 GET /api/reports/cash-flow-statement（后端 routers/reports.py wave-5 已实现）。
 *   顶部：账簿（当前公司，只读）+ 会计期间选择器（getAccountingPeriods）。
 *   主体：标准现金流量表 —— activities 树（经营/投资/筹资三大类小计加粗 → 子项目缩进）；
 *         本期数 vs 本年累计 两列，金额右对齐 MONO；底部「现金及现金等价物净增加额」合计行。
 *
 * 取数底座（与后端一致，本页不二次加工）：VoucherEntry.cashflow_item_id → CashflowItem 树（经营/投资/筹资），
 *   按已过账凭证分录归集；IN 项目=借增、OUT=贷增取净；未标 cashflow_item 的现金分录入 unclassified（不并入三大类）。
 * 空数据 / 端点 404 优雅降级。
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { App, Card, Select, Tag, Empty, Alert, Spin } from 'antd';
import { useAuth } from '../../auth';
import { getAccountingPeriods, getCashFlowStatement } from '../../api';
import { MONO, fmtMoney } from './financeHelpers';

export default function CashFlowStatementPage() {
  const { user } = useAuth();
  const { message } = App.useApp();

  const [periods, setPeriods] = useState([]);
  const [periodId, setPeriodId] = useState(null);
  const [report, setReport] = useState(null);
  const [loading, setLoading] = useState(false);
  const [notReady, setNotReady] = useState(false);

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
      const { data } = await getCashFlowStatement({ company_id: user.company_id, period_id: periodId });
      if (data?.error) { message.warning(data.error); setReport(null); }
      else setReport(data);
    } catch (e) {
      if (e.response?.status === 404) { setNotReady(true); setReport(null); }
      else { message.error('现金流量表查询失败：' + (e.response?.data?.detail || e.message)); setReport(null); }
    } finally { setLoading(false); }
  }, [periodId, user, message]);

  useEffect(() => { if (periodId && user?.company_id) runQuery(); }, [periodId, user, runQuery]);

  const periodLabel = useMemo(() => {
    const p = periods.find((x) => x.id === periodId);
    return p ? p.label : (periodId ? `期间 #${periodId}` : '—');
  }, [periods, periodId]);

  const activities = report?.data?.activities || [];
  const unclassified = report?.data?.unclassified;
  const netInc = report?.data?.net_increase;
  const hasUnclassified = unclassified && (Number(unclassified.period) || Number(unclassified.ytd));

  return (
    <div>
      <div style={{ marginBottom: 16, display: 'flex', alignItems: 'baseline', gap: 12, flexWrap: 'wrap' }}>
        <h2 style={{ fontSize: 26, fontWeight: 300, letterSpacing: '-0.01em', color: '#000', margin: 0, lineHeight: 1.2 }}>
          现金流量表
        </h2>
        <span style={{ color: '#777169', fontSize: 13 }}>
          财务 / 总账 · Cash Flow Statement · 账簿 = 当前公司 · 经营 / 投资 / 筹资三大类 · 本期数 vs 本年累计
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
            message="现金流量表端点待后端开通"
            description="GET /api/reports/cash-flow-statement 暂未就绪（404）。前端已按契约对齐，端点上线后本页自动出表。" />
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
                    <th style={{ textAlign: 'left', padding: '10px 16px', fontWeight: 500, color: '#777169' }}>项目</th>
                    <th style={{ textAlign: 'center', padding: '10px 8px', fontWeight: 500, color: '#777169', width: 56 }}>方向</th>
                    <th style={{ textAlign: 'right', padding: '10px 16px', fontWeight: 500, color: '#777169', width: 160 }}>本期数</th>
                    <th style={{ textAlign: 'right', padding: '10px 16px', fontWeight: 500, color: '#777169', width: 160 }}>本年累计</th>
                  </tr>
                </thead>
                <tbody>
                  {activities.length === 0 && !hasUnclassified && (
                    <tr><td colSpan={4} style={{ padding: 30 }}><Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="本期无现金流量数据" /></td></tr>
                  )}
                  {activities.map((act) => (
                    <ActivityBlock key={act.item_id} activity={act} />
                  ))}
                  {/* 未分类（未标 cashflow_item 的现金分录，不并入三大类，单列提示） */}
                  {hasUnclassified && (
                    <tr style={{ borderTop: '1px solid #efece8', background: 'rgba(251,245,228,0.4)' }}>
                      <td style={{ padding: '8px 16px', color: '#b8860b' }}>
                        {unclassified.label || '未归类现金流量'}
                        <span style={{ color: '#bfbbb5', fontSize: 11, marginLeft: 6 }}>（未标现金流量项目，不并入三大类）</span>
                      </td>
                      <td />
                      <Amount value={unclassified.period} />
                      <Amount value={unclassified.ytd} />
                    </tr>
                  )}
                  {/* 净增加额合计行 */}
                  {netInc && (
                    <tr style={{ borderTop: '2px solid #d9d4cd', background: 'rgba(245,242,239,0.7)' }}>
                      <td colSpan={2} style={{ padding: '12px 16px', fontWeight: 700 }}>
                        {netInc.label || '现金及现金等价物净增加额'}
                      </td>
                      <Amount value={netInc.period} bold flow />
                      <Amount value={netInc.ytd} bold flow />
                    </tr>
                  )}
                </tbody>
              </table>
            </Card>
          )}
          {report && (
            <div style={{ marginTop: 10, color: '#a8a39c', fontSize: 12 }}>
              {report.company_code} · {periodLabel}（第 {report.period_number} 期）· 单位：{report.currency} · IN=流入 / OUT=流出，已过账分录归集
            </div>
          )}
        </Spin>
      )}
    </div>
  );
}

// 三大类活动块：顶层小计行（加粗）+ 子项目（缩进 1 级）。
function ActivityBlock({ activity }) {
  return (
    <>
      <tr style={{ borderTop: '1px solid #efece8', background: 'rgba(245,242,239,0.35)' }}>
        <td style={{ padding: '8px 16px', fontWeight: 600 }}>{activity.name}</td>
        <td style={{ textAlign: 'center' }}><DirTag dir={activity.direction} /></td>
        <Amount value={activity.subtotal_period} semi />
        <Amount value={activity.subtotal_ytd} semi />
      </tr>
      {(activity.lines || []).map((ln) => (
        <tr key={ln.item_id} style={{ borderTop: '1px solid #f6f4f1' }}>
          <td style={{ padding: '6px 16px 6px 32px', color: '#3a3733' }}>
            <span style={{ fontFamily: MONO, color: '#bfbbb5', fontSize: 11, marginRight: 6 }}>{ln.code}</span>
            {ln.name}
          </td>
          <td style={{ textAlign: 'center' }}><DirTag dir={ln.direction} /></td>
          <Amount value={ln.period} />
          <Amount value={ln.ytd} />
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

// 金额单元格：净增加额行（flow）按正负着色（净流入绿/净流出红）。
function Amount({ value, bold, semi, flow }) {
  const n = Number(value);
  let color = '#3a3733';
  if (flow) color = n < 0 ? '#b42318' : (n > 0 ? '#1f8f3a' : '#3a3733');
  return (
    <td style={{ padding: bold ? '12px 16px' : '6px 16px', textAlign: 'right', fontFamily: MONO, fontWeight: bold ? 700 : (semi ? 600 : 400), color }}>
      {n ? fmtMoney(value) : <span style={{ color: '#d9d4cd' }}>—</span>}
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
