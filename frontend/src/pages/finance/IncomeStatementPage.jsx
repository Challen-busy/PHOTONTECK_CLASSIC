/**
 * IncomeStatementPage —— 利润表（总账·wave-5，owns by 前端A·三大财务报表 PM）
 *
 * 调 GET /api/reports/income-statement（后端 routers/reports.py wave-5 已实现）。
 *   顶部：账簿（当前公司，只读）+ 会计期间选择器（getAccountingPeriods）。
 *   主体：标准利润表 —— 行项目（sign +1 加 / -1 减，前端按 sign 渲染加减号缩进）；
 *         本期数 vs 本年累计 两列，金额右对齐 MONO；净利润行最粗合计。
 *
 * 口径（与后端一致，本页不二次加工）：行值=该类科目正常方向净额（正），sign 标示对净利润加减；
 *   净利润 = Σ sign×值，由后端给出（net_profit）。准则二分（HKFRS / CAS）行项目由后端结构驱动，前端不硬编码科目。
 * 本年累计 = 同会计年度 period_number ≤ 当期 的发生额累加（后端算）。空数据 / 端点 404 优雅降级。
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { App, Card, Select, Tag, Empty, Alert, Spin } from 'antd';
import { useAuth } from '../../auth';
import { getAccountingPeriods, getIncomeStatement } from '../../api';
import { MONO, fmtMoney } from './financeHelpers';

const STANDARD_LABEL = { HKFRS: 'HKFRS（香港）', CAS: 'CAS（企业会计准则）' };

export default function IncomeStatementPage() {
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
      const { data } = await getIncomeStatement({ company_id: user.company_id, period_id: periodId });
      if (data?.error) { message.warning(data.error); setReport(null); }
      else setReport(data);
    } catch (e) {
      if (e.response?.status === 404) { setNotReady(true); setReport(null); }
      else { message.error('利润表查询失败：' + (e.response?.data?.detail || e.message)); setReport(null); }
    } finally { setLoading(false); }
  }, [periodId, user, message]);

  useEffect(() => { if (periodId && user?.company_id) runQuery(); }, [periodId, user, runQuery]);

  const periodLabel = useMemo(() => {
    const p = periods.find((x) => x.id === periodId);
    return p ? p.label : (periodId ? `期间 #${periodId}` : '—');
  }, [periods, periodId]);

  const lines = report?.data?.lines || [];
  const net = report?.data?.net_profit;

  return (
    <div>
      <div style={{ marginBottom: 16, display: 'flex', alignItems: 'baseline', gap: 12, flexWrap: 'wrap' }}>
        <h2 style={{ fontSize: 26, fontWeight: 300, letterSpacing: '-0.01em', color: '#000', margin: 0, lineHeight: 1.2 }}>
          利润表
        </h2>
        <span style={{ color: '#777169', fontSize: 13 }}>
          财务 / 总账 · Income Statement · 账簿 = 当前公司 · 本期数 vs 本年累计 · 准则行项目由后端驱动
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
          {report?.standard && (
            <Field label="会计准则">
              <Tag color="purple">{STANDARD_LABEL[report.standard] || report.standard}</Tag>
            </Field>
          )}
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
            message="利润表端点待后端开通"
            description="GET /api/reports/income-statement 暂未就绪（404）。前端已按契约对齐，端点上线后本页自动出表。" />
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
                    <th style={{ textAlign: 'right', padding: '10px 16px', fontWeight: 500, color: '#777169', width: 160 }}>本期数</th>
                    <th style={{ textAlign: 'right', padding: '10px 16px', fontWeight: 500, color: '#777169', width: 160 }}>本年累计</th>
                  </tr>
                </thead>
                <tbody>
                  {lines.length === 0 && (
                    <tr><td colSpan={3} style={{ padding: 30 }}><Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="本期无损益数据" /></td></tr>
                  )}
                  {lines.map((ln) => (
                    <tr key={ln.line_key} style={{ borderTop: '1px solid #f6f4f1' }}>
                      <td style={{ padding: '8px 16px 8px 28px', color: '#3a3733' }}>
                        <span style={{
                          display: 'inline-block', width: 16, color: ln.sign < 0 ? '#c2410c' : '#1f8f3a',
                          fontFamily: MONO, fontWeight: 600,
                        }}>{ln.sign < 0 ? '−' : '+'}</span>
                        {ln.label}
                        <span style={{ color: '#bfbbb5', fontSize: 11, marginLeft: 6 }}>{ln.label_en}</span>
                      </td>
                      <Amount value={ln.period} />
                      <Amount value={ln.ytd} />
                    </tr>
                  ))}
                  {/* 净利润合计行 */}
                  {net && (
                    <tr style={{ borderTop: '2px solid #d9d4cd', background: 'rgba(245,242,239,0.7)' }}>
                      <td style={{ padding: '12px 16px', fontWeight: 700 }}>
                        {net.label || '净利润'}
                        <span style={{ color: '#a8a39c', fontWeight: 400, fontSize: 11, marginLeft: 6 }}>{net.label_en}</span>
                      </td>
                      <Amount value={net.period} bold profit />
                      <Amount value={net.ytd} bold profit />
                    </tr>
                  )}
                </tbody>
              </table>
            </Card>
          )}
          {report && (
            <div style={{ marginTop: 10, color: '#a8a39c', fontSize: 12 }}>
              {report.company_code} · {periodLabel}（第 {report.period_number} 期）· 单位：{report.currency} · 净利润 = Σ（sign × 行值）
            </div>
          )}
        </Spin>
      )}
    </div>
  );
}

// 金额单元格：净利润行（profit）按正负着色（盈绿亏红）；普通行黑色。
function Amount({ value, bold, profit }) {
  const n = Number(value);
  let color = '#3a3733';
  if (profit) color = n < 0 ? '#b42318' : (n > 0 ? '#1f8f3a' : '#3a3733');
  return (
    <td style={{ padding: bold ? '12px 16px' : '8px 16px', textAlign: 'right', fontFamily: MONO, fontWeight: bold ? 700 : 400, color }}>
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
