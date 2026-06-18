/**
 * ConsolidationReportPage —— 合并报表 / 多账簿合并（总账·finance-gl wave-7，owns by 前端A·合并报表视图 PM）
 *
 * 会计专家定调「可手工合」→ 半自动合并：各成员公司单体报表汇总 + 折算 + 手工抵消分录调整（非全自动权益法）。
 *   顶部：合并范围选择（query('consolidation_group')）+ 合并年度 + 期号 + tab（合并资产负债表 / 合并利润表）。
 *   主体：表格列 = [行项目, 各成员公司（按本位币→列报币折算后）, 抵消调整, 合并数]；
 *         行项目层级缩进（分组小计加粗）+ 段合计/总计加粗；presentation 货币标注；资产负债表勾稽徽章。
 *
 * 后端契约（routers/reports.py wave-7，已实现 + _company_filter 隔离 + 财务角色门）：
 *   GET /api/reports/consolidated-balance-sheet?group_id&period_year&period_number
 *   GET /api/reports/consolidated-income-statement?group_id&period_year&period_number
 *   成员单体 BS/IS 复用 wave-5 balance_sheet/income_statement，各行 closing/period/ytd × FX rate 折算后按 line_key 汇总；
 *   抵消列来自 EliminationEntry（statement=BS/IS）按 line_key（无则 account_code）聚合 net=debit-credit。
 *
 * 折算汇率缺失（≤期末日无 ExchangeRate）后端以 1.0 兜底并回 warning → 本页 Alert 醒目提示，不静默。
 * 缺成员同年同期号 → 该成员 included=false 不并入，亦由 warning 提示。端点 404 / error 优雅降级，不白屏。
 * 复用 financeHelpers（MONO / fmtMoney）。绝不硬编码科目 → 全按后端返回行树（line_key）渲染。
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { App, Card, Select, InputNumber, Tag, Tabs, Empty, Alert, Spin } from 'antd';
import { query } from '../../api';
import { getConsolidatedBalanceSheet, getConsolidatedIncomeStatement } from '../../api';
import { MONO, fmtMoney } from './financeHelpers';

const STANDARD_LABEL = { HKFRS: 'HKFRS（香港列报）', CAS: 'CAS（企业会计准则列报）' };

export default function ConsolidationReportPage() {
  const { message } = App.useApp();

  const [groups, setGroups] = useState([]);
  const [groupId, setGroupId] = useState(null);
  const now = new Date();
  const [periodYear, setPeriodYear] = useState(now.getFullYear());
  const [periodNumber, setPeriodNumber] = useState(now.getMonth() + 1);
  const [tab, setTab] = useState('bs');

  const [report, setReport] = useState(null);   // 当前 tab 的报表数据
  const [loading, setLoading] = useState(false);
  const [notReady, setNotReady] = useState(false);

  // 合并范围下拉（基础资料 consolidation_group，__queryable__）
  useEffect(() => {
    query('consolidation_group', { filters: { is_active: true }, order_by: 'code', limit: 200 })
      .then(({ data }) => {
        const gs = data?.data || [];
        setGroups(gs);
        if (gs.length) setGroupId(gs[0].id);
      })
      .catch((e) => message.error('合并范围加载失败：' + (e.response?.data?.detail || e.message)));
  }, [message]);

  const runQuery = useCallback(async () => {
    if (!groupId || !periodYear || !periodNumber) return;
    setLoading(true);
    setNotReady(false);
    const fn = tab === 'bs' ? getConsolidatedBalanceSheet : getConsolidatedIncomeStatement;
    const label = tab === 'bs' ? '合并资产负债表' : '合并利润表';
    try {
      const { data } = await fn({ group_id: groupId, period_year: periodYear, period_number: periodNumber });
      if (data?.error) { message.warning(data.error); setReport(null); }
      else setReport(data);
    } catch (e) {
      if (e.response?.status === 404) { setNotReady(true); setReport(null); }
      else { message.error(`${label}查询失败：` + (e.response?.data?.detail || e.message)); setReport(null); }
    } finally { setLoading(false); }
  }, [groupId, periodYear, periodNumber, tab, message]);

  useEffect(() => { runQuery(); }, [runQuery]);

  const groupMeta = useMemo(() => groups.find((g) => g.id === groupId) || null, [groups, groupId]);
  const members = report?.members || [];
  const warnings = report?.warnings || [];
  const ccy = report?.presentation_currency || groupMeta?.presentation_currency || '—';

  return (
    <div>
      <div style={{ marginBottom: 16, display: 'flex', alignItems: 'baseline', gap: 12, flexWrap: 'wrap' }}>
        <h2 style={{ fontSize: 26, fontWeight: 300, letterSpacing: '-0.01em', color: '#000', margin: 0, lineHeight: 1.2 }}>
          合并报表
        </h2>
        <span style={{ color: '#777169', fontSize: 13 }}>
          财务 / 总账 · Consolidation · 半自动合并（各成员单体报表汇总 + 折算 + 手工抵消） · 按同年同期号对齐成员期间
        </span>
      </div>

      {/* 筛选条：合并范围 + 年度 + 期号 */}
      <Card size="small" style={{ borderRadius: 14, marginBottom: 14 }}>
        <div style={{ display: 'flex', gap: 24, alignItems: 'flex-end', flexWrap: 'wrap' }}>
          <Field label="合并范围 / 合并主体">
            <Select size="small" value={groupId} style={{ width: 260 }} onChange={setGroupId} loading={!groups.length}
              placeholder="选择合并范围"
              options={groups.map((g) => ({ value: g.id, label: `${g.code} · ${g.name}` }))} />
          </Field>
          <Field label="合并年度">
            <InputNumber size="small" value={periodYear} onChange={(v) => v && setPeriodYear(v)}
              min={2000} max={2100} style={{ width: 110 }} controls />
          </Field>
          <Field label="合并期号">
            <InputNumber size="small" value={periodNumber} onChange={(v) => v && setPeriodNumber(v)}
              min={1} max={12} style={{ width: 90 }} controls />
          </Field>
          {report?.standard && (
            <Field label="列报准则">
              <Tag color="purple">{STANDARD_LABEL[report.standard] || report.standard}</Tag>
            </Field>
          )}
          <Field label="列报货币">
            <Tag color="gold">{ccy}</Tag>
          </Field>
          {report?.group_name && (
            <Field label="本期合并主体">
              <Tag color="geekblue">{report.group_code} · {report.group_name}</Tag>
            </Field>
          )}
        </div>
      </Card>

      <Tabs activeKey={tab} onChange={setTab} items={[
        { key: 'bs', label: '合并资产负债表' },
        { key: 'is', label: '合并利润表' },
      ]} style={{ marginBottom: 4 }} />

      {/* 折算汇率缺失 / 缺期间等后端 warning 醒目提示 */}
      {!notReady && warnings.length > 0 && (
        <Alert type="warning" showIcon style={{ borderRadius: 10, marginBottom: 12 }}
          message="合并提示（折算 / 期间对齐）"
          description={<ul style={{ margin: 0, paddingLeft: 18 }}>{warnings.map((w, i) => <li key={i}>{w}</li>)}</ul>} />
      )}

      {notReady ? (
        <Card size="small" style={{ borderRadius: 14 }}>
          <Alert type="warning" showIcon style={{ borderRadius: 10 }}
            message="合并报表端点待后端开通"
            description={`GET /api/reports/consolidated-${tab === 'bs' ? 'balance-sheet' : 'income-statement'} 暂未就绪（404）。前端已按契约对齐，端点上线后本页自动出表，无需改前端。`} />
        </Card>
      ) : (
        <Spin spinning={loading}>
          {!report ? (
            <Card size="small" style={{ borderRadius: 14 }}>
              <Empty style={{ padding: 40 }} description="选择合并范围与期间后自动出表" />
            </Card>
          ) : tab === 'bs' ? (
            <ConsolidatedBS report={report} members={members} ccy={ccy} />
          ) : (
            <ConsolidatedIS report={report} members={members} ccy={ccy} />
          )}
        </Spin>
      )}
    </div>
  );
}

/* ============================ 合并资产负债表 ============================ */
function ConsolidatedBS({ report, members, ccy }) {
  const assets = report.data?.assets || {};
  const liab = report.data?.liabilities || {};
  const equity = report.data?.equity || {};
  const check = report.check;

  return (
    <>
      <Card size="small" style={{ borderRadius: 14 }} styles={{ body: { padding: 0 } }}>
        <ConsolTable
          members={members}
          ccy={ccy}
          amountCols={[
            { key: 'per_company', isPer: true },
            { key: 'elimination', title: '抵消调整' },
            { key: 'consolidated', title: '合并数' },
          ]}
          sections={[
            { label: '资产 Assets', rows: assets.rows || [],
              memberTotals: assets.member_totals, elimTotal: assets.elimination_total,
              consolTotal: assets.consolidated_total, totalLabel: '资产总计', totalLabelEn: 'Total assets' },
            { label: '负债 Liabilities', rows: liab.rows || [],
              memberTotals: liab.member_totals, elimTotal: liab.elimination_total,
              consolTotal: liab.consolidated_total, totalLabel: '负债总计', totalLabelEn: 'Total liabilities' },
            { label: '权益 Equity', rows: equity.rows || [],
              memberTotals: equity.member_totals, elimTotal: equity.elimination_total,
              consolTotal: equity.consolidated_total, totalLabel: '权益总计', totalLabelEn: 'Total equity' },
          ]}
          perKey="per_company"
        />
      </Card>

      {/* 勾稽校验徽章：合并 资产合计 = 负债 + 权益合计 */}
      {check && (
        <Card size="small" style={{ borderRadius: 14, marginTop: 14 }}>
          <div style={{ display: 'flex', gap: 32, alignItems: 'center', flexWrap: 'wrap' }}>
            <div>
              <div style={{ fontSize: 11, color: '#777169', marginBottom: 4 }}>合并资产合计</div>
              <span style={{ fontFamily: MONO, fontSize: 16, fontWeight: 600 }}>{fmtMoney(check.assets_total)}</span>
            </div>
            <div style={{ fontSize: 18, color: '#bfbbb5' }}>=</div>
            <div>
              <div style={{ fontSize: 11, color: '#777169', marginBottom: 4 }}>合并负债 + 权益合计</div>
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

      <FootNote report={report} ccy={ccy}
        extra="合并数 = Σ各成员（本位币→列报币折算后）+ 抵消净额（借−贷）· 含「*」行的留存收益已并入未过账损益" />
    </>
  );
}

/* ============================ 合并利润表 ============================ */
function ConsolidatedIS({ report, members, ccy }) {
  const lines = report.data?.lines || [];
  const net = report.data?.net_profit;
  const cols = members.filter((mb) => mb.included);

  // 双口径切换：本期数 / 本年累计
  const [scope, setScope] = useState('period'); // period | ytd
  const perKey = scope === 'period' ? 'per_company_period' : 'per_company_ytd';
  const consolKey = scope === 'period' ? 'consolidated_period' : 'consolidated_ytd';

  return (
    <>
      <div style={{ marginBottom: 8 }}>
        <Tabs size="small" activeKey={scope} onChange={setScope} items={[
          { key: 'period', label: '本期数' },
          { key: 'ytd', label: '本年累计' },
        ]} />
      </div>
      <Card size="small" style={{ borderRadius: 14 }} styles={{ body: { padding: 0 } }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
          <thead>
            <tr style={{ borderBottom: '1px solid #efece8', background: 'rgba(245,242,239,0.5)' }}>
              <th style={{ textAlign: 'left', padding: '8px 12px', fontWeight: 500, color: '#777169' }}>项目</th>
              {cols.map((mb) => <MemberTh key={mb.company_id} mb={mb} ccy={ccy} />)}
              <th style={{ textAlign: 'right', padding: '8px 12px', fontWeight: 500, color: '#777169', width: 120 }}>抵消调整</th>
              <th style={{ textAlign: 'right', padding: '8px 12px', fontWeight: 600, color: '#3a3733', width: 130 }}>合并数</th>
            </tr>
          </thead>
          <tbody>
            {lines.length === 0 && (
              <tr><td colSpan={cols.length + 3} style={{ padding: 30 }}>
                <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="本期无损益数据" /></td></tr>
            )}
            {lines.map((ln) => (
              <tr key={ln.line_key} style={{ borderTop: '1px solid #f6f4f1' }}>
                <td style={{ padding: '7px 12px 7px 28px', color: '#3a3733' }}>
                  <span style={{
                    display: 'inline-block', width: 16, color: ln.sign < 0 ? '#c2410c' : '#1f8f3a',
                    fontFamily: MONO, fontWeight: 600,
                  }}>{ln.sign < 0 ? '−' : '+'}</span>
                  {ln.label}
                  <span style={{ color: '#bfbbb5', fontSize: 11, marginLeft: 6 }}>{ln.label_en}</span>
                </td>
                {cols.map((mb) => <Amount key={mb.company_id} value={ln[perKey]?.[mb.company_id]} />)}
                <Amount value={ln.elimination} dim />
                <Amount value={ln[consolKey]} semi />
              </tr>
            ))}
            {/* 净利润合计行（最粗） */}
            {net && (
              <tr style={{ borderTop: '2px solid #d9d4cd', background: 'rgba(245,242,239,0.7)' }}>
                <td style={{ padding: '11px 12px', fontWeight: 700 }}>
                  {net.label || '净利润'}
                  <span style={{ color: '#a8a39c', fontWeight: 400, fontSize: 11, marginLeft: 6 }}>{net.label_en}</span>
                </td>
                {cols.map((mb) => (
                  <Amount key={mb.company_id}
                    value={(scope === 'period' ? net.per_company_period : net.per_company_ytd)?.[mb.company_id]}
                    bold profit />
                ))}
                <Amount value={net.elimination} bold dim />
                <Amount value={scope === 'period' ? net.consolidated_period : net.consolidated_ytd} bold profit />
              </tr>
            )}
          </tbody>
        </table>
      </Card>

      <FootNote report={report} ccy={ccy}
        extra="合并数 = Σ各成员（本位币→列报币折算后 period/ytd）+ 抵消净额 · 净利润 = Σ（sign × 行值）" />
    </>
  );
}

/**
 * 通用合并报表表格（BS 用）：列 = [项目, 各成员公司(折算后), 抵消调整, 合并数]，
 * 按 sections（资产/负债/权益）分段：段标题加粗 → 行项目缩进 → 段合计加粗。
 */
function ConsolTable({ members, ccy, sections, perKey }) {
  const cols = members.filter((mb) => mb.included);
  return (
    <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
      <thead>
        <tr style={{ borderBottom: '1px solid #efece8', background: 'rgba(245,242,239,0.5)' }}>
          <th style={{ textAlign: 'left', padding: '8px 12px', fontWeight: 500, color: '#777169' }}>项目</th>
          {cols.map((mb) => <MemberTh key={mb.company_id} mb={mb} ccy={ccy} />)}
          <th style={{ textAlign: 'right', padding: '8px 12px', fontWeight: 500, color: '#777169', width: 120 }}>抵消调整</th>
          <th style={{ textAlign: 'right', padding: '8px 12px', fontWeight: 600, color: '#3a3733', width: 130 }}>合并数</th>
        </tr>
      </thead>
      <tbody>
        {sections.map((sec) => (
          <SectionBlock key={sec.label} section={sec} cols={cols} perKey={perKey} />
        ))}
      </tbody>
    </table>
  );
}

function SectionBlock({ section, cols, perKey }) {
  const { label, rows, memberTotals, elimTotal, consolTotal, totalLabel, totalLabelEn } = section;
  const colSpan = cols.length + 3;
  return (
    <>
      {/* 段标题行 */}
      <tr style={{ borderTop: '1px solid #efece8', background: 'rgba(245,242,239,0.45)' }}>
        <td colSpan={colSpan} style={{ padding: '8px 12px', fontWeight: 600, color: '#3a3733' }}>{label}</td>
      </tr>
      {rows.length === 0 && (
        <tr><td colSpan={colSpan} style={{ padding: '10px 28px', color: '#bfbbb5' }}>（本段无数据）</td></tr>
      )}
      {rows.map((ln) => (
        <tr key={ln.line_key} style={{ borderTop: '1px solid #f6f4f1' }}>
          <td style={{ padding: '6px 12px 6px 28px', color: '#3a3733' }}>
            {ln.label}
            {ln.includes_unposted_profit && <span title="含未过账损益" style={{ color: '#c2410c', marginLeft: 4 }}>*</span>}
            <span style={{ color: '#bfbbb5', fontSize: 11, marginLeft: 6 }}>{ln.label_en}</span>
          </td>
          {cols.map((mb) => <Amount key={mb.company_id} value={ln[perKey]?.[mb.company_id]} />)}
          <Amount value={ln.elimination} dim />
          <Amount value={ln.consolidated} semi />
        </tr>
      ))}
      {/* 段合计行（加粗） */}
      <tr style={{ borderTop: '1.5px solid #d9d4cd', background: 'rgba(245,242,239,0.6)' }}>
        <td style={{ padding: '9px 12px', fontWeight: 700 }}>
          {totalLabel}
          <span style={{ color: '#a8a39c', fontWeight: 400, fontSize: 11, marginLeft: 6 }}>{totalLabelEn}</span>
        </td>
        {cols.map((mb) => <Amount key={mb.company_id} value={memberTotals?.[mb.company_id]} bold />)}
        <Amount value={elimTotal} bold dim />
        <Amount value={consolTotal} bold />
      </tr>
    </>
  );
}

// 成员公司列头：公司名 + 本位币 + 折算率（null=该期无数据，已被 included 过滤掉但 rate 仍可能缺）。
function MemberTh({ mb, ccy }) {
  const sameCcy = mb.currency === ccy;
  return (
    <th style={{ textAlign: 'right', padding: '6px 12px', fontWeight: 500, color: '#777169', width: 130 }}>
      <div style={{ fontWeight: 600, color: '#3a3733' }}>{mb.company_name}</div>
      <div style={{ fontSize: 10.5, color: '#a8a39c', fontWeight: 400 }}>
        {mb.company_code} · {mb.currency}
        {!sameCcy && mb.rate != null && <span style={{ marginLeft: 4 }}>×{Number(mb.rate).toFixed(4)}</span>}
      </div>
    </th>
  );
}

// 金额单元格：dim=抵消列（灰）；profit=净利润盈绿亏红；bold=合计；semi=合并列半粗。
function Amount({ value, bold, semi, dim, profit }) {
  const n = Number(value);
  let color = '#3a3733';
  if (dim) color = '#8c8780';
  if (profit) color = n < 0 ? '#b42318' : (n > 0 ? '#1f8f3a' : '#3a3733');
  return (
    <td style={{
      padding: bold ? '9px 12px' : '6px 12px', textAlign: 'right', fontFamily: MONO,
      fontWeight: bold ? 700 : (semi ? 600 : 400), color,
    }}>
      {n ? fmtMoney(value) : <span style={{ color: '#d9d4cd' }}>—</span>}
    </td>
  );
}

function FootNote({ report, ccy, extra }) {
  return (
    <div style={{ marginTop: 10, color: '#a8a39c', fontSize: 12 }}>
      {report.group_code} · {report.period_year} 年第 {report.period_number} 期 · 列报货币：{ccy} · {extra}
    </div>
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
