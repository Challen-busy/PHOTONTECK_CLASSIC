/**
 * BalanceSheetPage —— 资产负债表（总账·wave-5，owns by 前端A·三大财务报表 PM）
 *
 * 调 GET /api/reports/balance-sheet（后端 routers/reports.py wave-5 已实现）。
 *   顶部：账簿（当前公司，只读，company_id 取自会话 user）+ 会计期间选择器（getAccountingPeriods）。
 *   主体：标准财务报表样式 —— 左资产 / 右「负债+权益」对照；行项目层级缩进；小计/合计加粗；
 *         期末数 vs 年初数 两列，金额右对齐 MONO。底部「资产 = 负债 + 权益」勾稽校验徽章。
 *
 * 准则二分（HKFRS / CAS）由后端按 Company.region 决定，groups 顺序 / 行项目 / equity.label 全由后端返回结构驱动，
 *   前端按返回的行树渲染，绝不硬编码科目（科目码 → 报表行映射在后端常量表）。
 *
 * 取数底座：AccountBalance（余额真相，含留存收益行 includes_unposted_profit 标记）。公司隔离由后端兜底。
 * 空数据 / 端点 404 优雅降级（提示「报表端点待后端开通」，不白屏）。
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { App, Card, Select, Tag, Empty, Alert, Spin } from 'antd';
import { useAuth } from '../../auth';
import { getAccountingPeriods, getBalanceSheet } from '../../api';
import { MONO, fmtMoney } from './financeHelpers';

const STANDARD_LABEL = { HKFRS: 'HKFRS（香港）', CAS: 'CAS（企业会计准则）' };

export default function BalanceSheetPage() {
  const { user } = useAuth();
  const { message } = App.useApp();

  const [periods, setPeriods] = useState([]);
  const [periodId, setPeriodId] = useState(null);
  const [report, setReport] = useState(null);
  const [loading, setLoading] = useState(false);
  const [notReady, setNotReady] = useState(false); // 端点 404 降级标记

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
      const { data } = await getBalanceSheet({ company_id: user.company_id, period_id: periodId });
      if (data?.error) { message.warning(data.error); setReport(null); }
      else setReport(data);
    } catch (e) {
      if (e.response?.status === 404) { setNotReady(true); setReport(null); }
      else { message.error('资产负债表查询失败：' + (e.response?.data?.detail || e.message)); setReport(null); }
    } finally { setLoading(false); }
  }, [periodId, user, message]);

  useEffect(() => { if (periodId && user?.company_id) runQuery(); }, [periodId, user, runQuery]);

  const periodLabel = useMemo(() => {
    const p = periods.find((x) => x.id === periodId);
    return p ? p.label : (periodId ? `期间 #${periodId}` : '—');
  }, [periods, periodId]);

  const check = report?.check;

  return (
    <div>
      <div style={{ marginBottom: 16, display: 'flex', alignItems: 'baseline', gap: 12, flexWrap: 'wrap' }}>
        <h2 style={{ fontSize: 26, fontWeight: 300, letterSpacing: '-0.01em', color: '#000', margin: 0, lineHeight: 1.2 }}>
          资产负债表
        </h2>
        <span style={{ color: '#777169', fontSize: 13 }}>
          财务 / 总账 · Balance Sheet · 账簿 = 当前公司 · 准则与行项目由后端按 region 驱动（HKFRS / CAS）
        </span>
      </div>

      {/* 筛选条：账簿（只读）+ 期间 */}
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
            message="资产负债表端点待后端开通"
            description="GET /api/reports/balance-sheet 暂未就绪（404）。前端已按契约对齐，端点上线后本页自动出表，无需改前端。" />
        </Card>
      ) : (
        <Spin spinning={loading}>
          {!report ? (
            <Card size="small" style={{ borderRadius: 14 }}>
              <Empty style={{ padding: 40 }} description="选择会计期间后自动出表" />
            </Card>
          ) : (
            <>
              {/* 资产 | 负债+权益 双栏对照（标准平衡式排版） */}
              <div style={{ display: 'flex', gap: 14, alignItems: 'flex-start', flexWrap: 'wrap' }}>
                <Card size="small" title="资产 Assets" style={{ borderRadius: 14, flex: '1 1 440px', minWidth: 380 }}
                  styles={{ body: { padding: 0 } }}>
                  <ReportTable
                    groups={report.data?.assets?.groups || []}
                    totalLabel="资产总计"
                    totalLabelEn="Total assets"
                    totalClosing={report.data?.assets?.total_closing}
                    totalOpening={report.data?.assets?.total_opening}
                  />
                </Card>

                <Card size="small" title="负债及权益 Liabilities & Equity" style={{ borderRadius: 14, flex: '1 1 440px', minWidth: 380 }}
                  styles={{ body: { padding: 0 } }}>
                  <ReportTable
                    groups={report.data?.liabilities?.groups || []}
                    equity={report.data?.equity}
                    totalLabel="负债及权益总计"
                    totalLabelEn="Total liabilities & equity"
                    totalClosing={(report.data?.liabilities?.total_closing || 0) + (report.data?.equity?.total_closing || 0)}
                    totalOpening={(report.data?.liabilities?.total_opening || 0) + (report.data?.equity?.total_opening || 0)}
                  />
                </Card>
              </div>

              {/* 勾稽校验徽章：资产 = 负债 + 权益 */}
              {check && (
                <Card size="small" style={{ borderRadius: 14, marginTop: 14 }}>
                  <div style={{ display: 'flex', gap: 32, alignItems: 'center', flexWrap: 'wrap' }}>
                    <div>
                      <div style={{ fontSize: 11, color: '#777169', marginBottom: 4 }}>资产合计</div>
                      <span style={{ fontFamily: MONO, fontSize: 16, fontWeight: 600 }}>{fmtMoney(check.assets_total)}</span>
                    </div>
                    <div style={{ fontSize: 18, color: '#bfbbb5' }}>=</div>
                    <div>
                      <div style={{ fontSize: 11, color: '#777169', marginBottom: 4 }}>负债 + 权益合计</div>
                      <span style={{ fontFamily: MONO, fontSize: 16, fontWeight: 600 }}>{fmtMoney(check.liabilities_plus_equity)}</span>
                    </div>
                    <div style={{ marginLeft: 'auto' }}>
                      {check.balanced
                        ? <Tag color="green" style={{ fontSize: 14, padding: '4px 14px' }}>勾稽平衡 ✓</Tag>
                        : <Tag color="red" style={{ fontSize: 14, padding: '4px 14px' }}>
                            不平衡（差额 {fmtMoney((check.assets_total || 0) - (check.liabilities_plus_equity || 0))}）
                          </Tag>}
                    </div>
                  </div>
                </Card>
              )}

              <div style={{ marginTop: 10, color: '#a8a39c', fontSize: 12 }}>
                {report.company_code} · {periodLabel} · 单位：{report.currency} · 含「*」行的留存收益已并入未过账损益
              </div>
            </>
          )}
        </Spin>
      )}
    </div>
  );
}

/**
 * 报表分组表格：按后端 groups 行树渲染（分组小计 → 行项目缩进），
 * equity（权益块，仅负债侧传入）作为独立分组接在负债 groups 之后，最后给总计行。
 * 列：项目（缩进）| 期末数 | 年初数（金额右对齐 MONO）。
 */
function ReportTable({ groups = [], equity, totalLabel, totalLabelEn, totalClosing, totalOpening }) {
  return (
    <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
      <thead>
        <tr style={{ borderBottom: '1px solid #efece8', background: 'rgba(245,242,239,0.5)' }}>
          <th style={{ textAlign: 'left', padding: '8px 12px', fontWeight: 500, color: '#777169' }}>项目</th>
          <th style={{ textAlign: 'right', padding: '8px 12px', fontWeight: 500, color: '#777169', width: 130 }}>期末数</th>
          <th style={{ textAlign: 'right', padding: '8px 12px', fontWeight: 500, color: '#777169', width: 130 }}>年初数</th>
        </tr>
      </thead>
      <tbody>
        {groups.map((g) => <GroupBlock key={g.group_key} group={g} />)}
        {equity && (
          <GroupBlock
            group={{
              group_key: 'equity',
              label: equity.label,
              label_en: equity.label_en,
              lines: equity.lines || [],
              subtotal_closing: equity.total_closing,
              subtotal_opening: equity.total_opening,
            }}
          />
        )}
        {/* 总计行（最粗） */}
        <tr style={{ borderTop: '2px solid #d9d4cd', background: 'rgba(245,242,239,0.7)' }}>
          <td style={{ padding: '10px 12px', fontWeight: 700 }}>
            {totalLabel}
            <span style={{ color: '#a8a39c', fontWeight: 400, fontSize: 11, marginLeft: 6 }}>{totalLabelEn}</span>
          </td>
          <Amount value={totalClosing} bold />
          <Amount value={totalOpening} bold />
        </tr>
      </tbody>
    </table>
  );
}

// 单个分组：小计行（加粗）+ 其下行项目（缩进 1 级）。
function GroupBlock({ group }) {
  return (
    <>
      <tr style={{ borderTop: '1px solid #efece8', background: 'rgba(245,242,239,0.35)' }}>
        <td style={{ padding: '8px 12px', fontWeight: 600 }}>
          {group.label}
          <span style={{ color: '#a8a39c', fontWeight: 400, fontSize: 11, marginLeft: 6 }}>{group.label_en}</span>
        </td>
        <Amount value={group.subtotal_closing} semi />
        <Amount value={group.subtotal_opening} semi />
      </tr>
      {(group.lines || []).map((ln) => (
        <tr key={ln.line_key} style={{ borderTop: '1px solid #f6f4f1' }}>
          <td style={{ padding: '6px 12px 6px 28px', color: '#3a3733' }}>
            {ln.label}
            {ln.includes_unposted_profit && <span title="含未过账损益" style={{ color: '#c2410c', marginLeft: 4 }}>*</span>}
            <span style={{ color: '#bfbbb5', fontSize: 11, marginLeft: 6 }}>{ln.label_en}</span>
          </td>
          <Amount value={ln.closing} />
          <Amount value={ln.opening} />
        </tr>
      ))}
    </>
  );
}

function Amount({ value, bold, semi }) {
  const n = Number(value);
  return (
    <td style={{ padding: bold ? '10px 12px' : '6px 12px', textAlign: 'right', fontFamily: MONO, fontWeight: bold ? 700 : (semi ? 600 : 400) }}>
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
