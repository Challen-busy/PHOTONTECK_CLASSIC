/**
 * ARWriteoffPage —— 应收核销工作台（finance-gl·应收款管理，owns by C·核销界面 PM）
 *
 * 落「债权↔已收勾稽」：左栏待核销应收单（债权侧）/ 右栏待核销收款·预收（已收侧），多对多核销。
 *   · 顶部过滤：客户(F7) / 币别 / 结算组织 / 核销方案，拉 /api/reports/ar-open-items 出两侧未清明细。
 *   · 自动核销：选方案 → finance.writeoff(auto=true, scheme_id)，后端按 match_rule 配对（FIFO/同金额/按到期日/手工）。
 *   · 手工核销：左右各勾选 + 逐行填「本次核销额」→ 底部差额闸（两侧本次额相等且 >0 才放行）→ finance.writeoff(links)。
 *   · 反核销：选已核销 link → finance.unwriteoff（is_active=False 留痕 + 回退两单已核销额/状态）。
 *
 * 唯一写入：核销/反核销只调 finance.* 命令（execute_command 唯一写入路径），本页不在前端伪造写库。
 *   外币本次核销原币×(核销汇率−入账汇率)→汇兑损益由后端算并回 exchange_diff（口径⚠️后端待复核），前端只展示。
 *
 * 通用件：biz_type 参数化（默认 AR），应付款核销后续可复用本页骨架（换 biz_type=AP + 标签）。
 * 公司隔离由后端会话兜底；company_id 缺省取当前用户主公司（后端 payload 默认）。
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  App, Card, Select, Button, Space, Table, Tag, Row, Col as ACol, Statistic, InputNumber, Alert, Empty, Divider, Tooltip,
} from 'antd';
import { ReloadOutlined, ThunderboltOutlined, LinkOutlined, RollbackOutlined } from '@ant-design/icons';
import { useAuth } from '../../../auth';
import { query, getArOpenItems, writeoff, unwriteoff } from '../../../api';
import { MONO, fmtMoney, statusLabel } from '../financeHelpers';

// 本次核销状态标签（应收单 writeoff_status / 收款单 writeoff_status 取值）。
const WO_STATUS = {
  UNVERIFIED: { label: '未核销', color: 'default' },
  PARTIAL: { label: '部分核销', color: 'gold' },
  VERIFIED: { label: '已核销', color: 'green' },
};

const round2 = (x) => Math.round((Number(x) || 0) * 100) / 100;

export default function ARWriteoffPage() {
  const { user } = useAuth();
  const { message, modal } = App.useApp();

  // 过滤条
  const [customers, setCustomers] = useState([]);
  const [orgs, setOrgs] = useState([]);
  const [schemes, setSchemes] = useState([]);
  const [partyId, setPartyId] = useState(null);
  const [currency, setCurrency] = useState(null);
  const [settlementOrgId, setSettlementOrgId] = useState(null);
  const [schemeId, setSchemeId] = useState(null);

  // 两侧明细 + 本次核销额录入（key=doc_id → amount）
  const [debitItems, setDebitItems] = useState([]);   // 待核销应收（债权）
  const [creditItems, setCreditItems] = useState([]); // 待核销收款/预收（已收）
  const [debitSel, setDebitSel] = useState([]);       // 勾选的应收单 id
  const [creditSel, setCreditSel] = useState([]);     // 勾选的收款单 id
  const debitAmtRef = useRef({});                     // {doc_id: 本次核销额}
  const creditAmtRef = useRef({});
  const [, forceTick] = useState(0);                  // 录入额变更触发底部合计重算

  const [loading, setLoading] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  // 已核销关系（反核销用）
  const [links, setLinks] = useState([]);
  const [linksLoading, setLinksLoading] = useState(false);
  const [linkSel, setLinkSel] = useState([]);

  // 客户名 join 缓存
  const custById = useMemo(() => new Map(customers.map((c) => [c.id, c])), [customers]);
  const custName = useCallback((id) => {
    const c = custById.get(id);
    return c ? (c.short_name || c.name || `客户#${id}`) : (id ? `客户#${id}` : '—');
  }, [custById]);

  // 过滤条主数据（客户 F7 / 结算组织（公司）/ 核销方案）
  useEffect(() => {
    (async () => {
      try {
        const [{ data: cust }, { data: comp }, { data: sch }] = await Promise.all([
          query('customer', { limit: 1000, order_by: 'code' }),
          query('company', { limit: 100, order_by: 'id' }),
          query('writeoff_scheme', { filters: { biz_type: 'AR', is_active: true }, order_by: 'priority', limit: 100 }),
        ]);
        setCustomers(cust?.data || []);
        setOrgs(comp?.data || []);
        const ss = sch?.data || [];
        setSchemes(ss);
        // 默认核销方案 = 本 biz_type 默认（is_default），缺则最高优先级。
        const def = ss.find((s) => s.is_default) || ss[0];
        if (def) setSchemeId(def.id);
      } catch (e) {
        message.error('核销主数据加载失败：' + (e.response?.data?.detail || e.message));
      }
    })();
  }, [message]);

  // 拉两侧未清明细（按当前过滤）
  const loadOpen = useCallback(async () => {
    setLoading(true);
    try {
      const params = { biz_type: 'AR' };
      if (partyId) params.party_id = partyId;
      if (currency) params.currency = currency;
      const { data } = await getArOpenItems(params);
      setDebitItems(data?.debit_items || []);
      setCreditItems(data?.credit_items || []);
      // 切换过滤后清空旧勾选/录入额（避免跨筛选误带）
      setDebitSel([]); setCreditSel([]);
      debitAmtRef.current = {}; creditAmtRef.current = {};
      forceTick((t) => t + 1);
      setLoaded(true);
    } catch (e) {
      message.error('待核销明细加载失败：' + (e.response?.data?.detail || e.message));
      setDebitItems([]); setCreditItems([]);
    } finally { setLoading(false); }
  }, [partyId, currency, message]);

  // 已核销关系（通用 writeoff_link，biz_type=AR + is_active）
  const loadLinks = useCallback(async () => {
    setLinksLoading(true);
    try {
      const { data } = await query('writeoff_link', { filters: { biz_type: 'AR', is_active: true }, order_by: '-id', limit: 300 });
      setLinks(data?.data || []);
      setLinkSel([]);
    } catch (e) {
      message.error('核销关系加载失败：' + (e.response?.data?.detail || e.message));
      setLinks([]);
    } finally { setLinksLoading(false); }
  }, [message]);

  useEffect(() => { loadOpen(); loadLinks(); }, [loadOpen, loadLinks]);

  // 币别可选项（从两侧明细收集，免依赖币别主数据端点）
  const currencyOptions = useMemo(() => {
    const set = new Set();
    [...debitItems, ...creditItems].forEach((r) => r.currency && set.add(r.currency));
    return [...set].map((c) => ({ value: c, label: c }));
  }, [debitItems, creditItems]);

  // 本次核销额读写
  const setDebitAmt = (id, v) => { debitAmtRef.current[id] = v; forceTick((t) => t + 1); };
  const setCreditAmt = (id, v) => { creditAmtRef.current[id] = v; forceTick((t) => t + 1); };

  // 勾选行时默认带入未核销余额（用户可改小）；取消勾选清零。
  const onDebitSelChange = (keys) => {
    setDebitSel(keys);
    debitItems.forEach((r) => {
      if (keys.includes(r.id)) { if (debitAmtRef.current[r.id] == null) debitAmtRef.current[r.id] = r.open_amount; }
      else delete debitAmtRef.current[r.id];
    });
    forceTick((t) => t + 1);
  };
  const onCreditSelChange = (keys) => {
    setCreditSel(keys);
    creditItems.forEach((r) => {
      if (keys.includes(r.id)) { if (creditAmtRef.current[r.id] == null) creditAmtRef.current[r.id] = r.open_amount; }
      else delete creditAmtRef.current[r.id];
    });
    forceTick((t) => t + 1);
  };

  // 底部本次核销合计 + 差额闸
  const sums = useMemo(() => {
    let d = 0, c = 0;
    debitSel.forEach((id) => { d += Number(debitAmtRef.current[id]) || 0; });
    creditSel.forEach((id) => { c += Number(creditAmtRef.current[id]) || 0; });
    d = round2(d); c = round2(c);
    const diff = round2(d - c);
    return { debit: d, credit: c, diff, balanced: Math.abs(diff) < 0.005 && d > 0 };
  }, [debitSel, creditSel, debitItems, creditItems, currency]); // eslint-disable-line react-hooks/exhaustive-deps

  // 手工核销：左右各取 1（多对多由后端逐对消化；本页一次提交一组「单应收×单收款」或一笔均摊）
  // 规格 links 为 [{debit_doc_id,credit_doc_id,amount}]。手工时按「笛卡尔最小消化」：逐对配，直到任一侧本次额耗尽。
  const buildManualLinks = () => {
    // 把两侧勾选行按本次额展开成可消化队列
    const dq = debitSel
      .map((id) => ({ id, left: round2(Number(debitAmtRef.current[id]) || 0) }))
      .filter((x) => x.left > 0);
    const cq = creditSel
      .map((id) => ({ id, left: round2(Number(creditAmtRef.current[id]) || 0) }))
      .filter((x) => x.left > 0);
    const out = [];
    let di = 0, ci = 0;
    while (di < dq.length && ci < cq.length) {
      const take = round2(Math.min(dq[di].left, cq[ci].left));
      if (take <= 0) break;
      out.push({ debit_doc_id: dq[di].id, credit_doc_id: cq[ci].id, amount: take });
      dq[di].left = round2(dq[di].left - take);
      cq[ci].left = round2(cq[ci].left - take);
      if (dq[di].left <= 0) di++;
      if (cq[ci].left <= 0) ci++;
    }
    return out;
  };

  const doManualWriteoff = async () => {
    if (!sums.balanced) { message.warning('两侧「本次核销额」需相等且大于 0 才可核销'); return; }
    const linksPayload = buildManualLinks();
    if (!linksPayload.length) { message.warning('请在左右两侧各勾选单据并填本次核销额'); return; }
    setSubmitting(true);
    try {
      const payload = { biz_type: 'AR', auto: false, links: linksPayload };
      if (partyId) payload.party_id = partyId;
      if (currency) payload.currency = currency;
      if (settlementOrgId) payload.settlement_org_id = settlementOrgId;
      const { data } = await writeoff(payload);
      const exDiff = (data?.links || []).reduce((s, l) => s + (Number(l.exchange_diff) || 0), 0);
      message.success(`核销成功：写入 ${data?.created ?? linksPayload.length} 条关系${exDiff ? `（汇兑差合计 ${fmtMoney(exDiff)}）` : ''}`);
      await loadOpen(); await loadLinks();
    } catch (e) {
      message.error('核销失败：' + (e.response?.data?.detail || e.message));
    } finally { setSubmitting(false); }
  };

  const doAutoWriteoff = async () => {
    if (!schemeId) { message.warning('请选择核销方案'); return; }
    const sch = schemes.find((s) => s.id === schemeId);
    if (sch?.match_rule === 'MANUAL') { message.warning('「手工」方案不支持自动核销，请用手工核销或换自动方案'); return; }
    setSubmitting(true);
    try {
      const payload = { biz_type: 'AR', auto: true, scheme_id: schemeId };
      if (partyId) payload.party_id = partyId;
      if (currency) payload.currency = currency;
      if (settlementOrgId) payload.settlement_org_id = settlementOrgId;
      const { data } = await writeoff(payload);
      if (!data?.created) message.info('未配对到可核销组合（方案规则下无匹配债权/已收）');
      else message.success(`自动核销成功：写入 ${data.created} 条关系（方案 ${sch?.name || schemeId}）`);
      await loadOpen(); await loadLinks();
    } catch (e) {
      message.error('自动核销失败：' + (e.response?.data?.detail || e.message));
    } finally { setSubmitting(false); }
  };

  const doUnwriteoff = () => {
    if (!linkSel.length) { message.warning('请勾选要反核销的核销关系'); return; }
    modal.confirm({
      title: `反核销 ${linkSel.length} 条关系？`,
      content: '反核销将置 is_active=False 留痕，并回退两单已核销额与核销状态（外币会冲回汇兑差，口径以后端为准）。',
      okText: '反核销', okButtonProps: { danger: true },
      onOk: async () => {
        try {
          const { data } = await unwriteoff({ writeoff_link_ids: linkSel });
          const skipped = (data?.skipped || []).length;
          message.success(`反核销成功：${data?.reverted ?? 0} 条${skipped ? `（跳过 ${skipped} 条已反核销）` : ''}`);
          await loadOpen(); await loadLinks();
        } catch (e) {
          message.error('反核销失败：' + (e.response?.data?.detail || e.message));
        }
      },
    });
  };

  // ── 左栏：待核销应收（债权）列 ──
  const debitColumns = [
    { title: '应收单号', dataIndex: 'number', width: 150, fixed: 'left', render: (v, r) => <span style={{ fontFamily: MONO }}>{v || `#${r.id}`}</span> },
    { title: '客户', dataIndex: 'party_id', width: 130, render: (v) => custName(v) },
    { title: '业务日期', dataIndex: 'bill_date', width: 100, render: (v) => v || dash },
    { title: '到期日', dataIndex: 'due_date', width: 100, render: (v) => v || dash },
    { title: '原金额', dataIndex: 'amount', width: 110, align: 'right', render: money },
    { title: '已核销', dataIndex: 'written_off_amount', width: 100, align: 'right', render: money },
    { title: '未核销', dataIndex: 'open_amount', width: 110, align: 'right', render: (v) => <strong style={{ fontFamily: MONO }}>{fmtMoney(v)}</strong> },
    { title: '币别', dataIndex: 'currency', width: 56 },
    { title: '状态', dataIndex: 'writeoff_status', width: 90, render: woTag },
    {
      title: '本次核销额', dataIndex: '_amt', width: 140, fixed: 'right',
      render: (_, r) => (
        <InputNumber
          size="small" min={0} max={Number(r.open_amount) || 0} precision={2} controls={false}
          style={{ width: 120, fontFamily: MONO }} disabled={!debitSel.includes(r.id)}
          value={debitAmtRef.current[r.id]} onChange={(v) => setDebitAmt(r.id, v)}
          placeholder={debitSel.includes(r.id) ? '本次额' : '勾选后填'} />
      ),
    },
  ];

  // ── 右栏：待核销收款/预收（已收）列 ──
  const creditColumns = [
    { title: '收款单号', dataIndex: 'number', width: 150, fixed: 'left', render: (v, r) => <span style={{ fontFamily: MONO }}>{v || `#${r.id}`}</span> },
    { title: '客户', dataIndex: 'party_id', width: 130, render: (v) => custName(v) },
    { title: '收款日期', dataIndex: 'receipt_date', width: 100, render: (v) => v || dash },
    { title: '收款金额', dataIndex: 'amount', width: 110, align: 'right', render: money },
    { title: '已核销', dataIndex: 'written_off_amount', width: 100, align: 'right', render: money },
    { title: '未核销', dataIndex: 'open_amount', width: 110, align: 'right', render: (v) => <strong style={{ fontFamily: MONO }}>{fmtMoney(v)}</strong> },
    { title: '币别', dataIndex: 'currency', width: 56 },
    { title: '状态', dataIndex: 'writeoff_status', width: 90, render: woTag },
    {
      title: '本次核销额', dataIndex: '_amt', width: 140, fixed: 'right',
      render: (_, r) => (
        <InputNumber
          size="small" min={0} max={Number(r.open_amount) || 0} precision={2} controls={false}
          style={{ width: 120, fontFamily: MONO }} disabled={!creditSel.includes(r.id)}
          value={creditAmtRef.current[r.id]} onChange={(v) => setCreditAmt(r.id, v)}
          placeholder={creditSel.includes(r.id) ? '本次额' : '勾选后填'} />
      ),
    },
  ];

  // ── 反核销：已核销关系列 ──
  const linkColumns = [
    { title: '核销ID', dataIndex: 'id', width: 80, render: (v) => <span style={{ fontFamily: MONO }}>#{v}</span> },
    { title: '应收单', dataIndex: 'debit_doc_id', width: 150, render: (v, r) => <span style={{ fontFamily: MONO }}>{r.debit_doc_type} #{v}</span> },
    { title: '收款单', dataIndex: 'credit_doc_id', width: 150, render: (v, r) => <span style={{ fontFamily: MONO }}>{r.credit_doc_type} #{v}</span> },
    { title: '本次核销(原币)', dataIndex: 'amount', width: 130, align: 'right', render: money },
    { title: '本位币', dataIndex: 'base_amount', width: 120, align: 'right', render: money },
    {
      title: '汇兑差', dataIndex: 'exchange_diff', width: 110, align: 'right',
      render: (v) => Number(v) ? <Tooltip title="本次核销原币×(核销汇率−入账汇率)，口径以后端为准"><span style={{ fontFamily: MONO, color: '#cf1322' }}>{fmtMoney(v)}</span></Tooltip> : dash,
    },
    { title: '核销日期', dataIndex: 'write_date', width: 110, render: (v) => v || dash },
  ];

  const selectedScheme = schemes.find((s) => s.id === schemeId);

  return (
    <div>
      <div style={{ marginBottom: 16, display: 'flex', alignItems: 'baseline', gap: 12, flexWrap: 'wrap' }}>
        <h2 style={{ fontSize: 26, fontWeight: 300, letterSpacing: '-0.01em', color: '#000', margin: 0, lineHeight: 1.2 }}>
          应收核销
        </h2>
        <span style={{ color: '#777169', fontSize: 13 }}>
          财务 / 应收款管理 · 债权（应收单）↔ 已收（收款/预收）多对多勾稽 · 账簿 = {user?.company_name || `公司 #${user?.company_id ?? ''}`}
        </span>
      </div>

      {/* 过滤 + 操作条 */}
      <Card size="small" style={{ borderRadius: 14, marginBottom: 14 }}>
        <Space wrap size={16} align="end">
          <Fld label="客户（F7）">
            <Select size="small" style={{ width: 200 }} allowClear showSearch optionFilterProp="label"
              placeholder="全部客户" value={partyId ?? undefined} onChange={setPartyId}
              options={customers.map((c) => ({ value: c.id, label: `${c.short_name || c.name}${c.code ? `（${c.code}）` : ''}` }))} />
          </Fld>
          <Fld label="币别">
            <Select size="small" style={{ width: 110 }} allowClear placeholder="全部"
              value={currency ?? undefined} onChange={setCurrency} options={currencyOptions} />
          </Fld>
          <Fld label="结算组织">
            <Select size="small" style={{ width: 160 }} allowClear showSearch optionFilterProp="label"
              placeholder="默认本公司" value={settlementOrgId ?? undefined} onChange={setSettlementOrgId}
              options={orgs.map((o) => ({ value: o.id, label: o.short_name || o.name || `#${o.id}` }))} />
          </Fld>
          <Fld label="核销方案">
            <Select size="small" style={{ width: 200 }} value={schemeId ?? undefined} onChange={setSchemeId}
              options={schemes.map((s) => ({ value: s.id, label: `${s.name}（${SCHEME_RULE[s.match_rule] || s.match_rule}）${s.is_default ? ' ★' : ''}` }))} />
          </Fld>
          <Button size="small" icon={<ReloadOutlined />} loading={loading} onClick={loadOpen}>刷新明细</Button>
          <Button size="small" type="primary" ghost icon={<ThunderboltOutlined />} loading={submitting}
            disabled={!schemeId || selectedScheme?.match_rule === 'MANUAL'} onClick={doAutoWriteoff}>
            自动核销
          </Button>
        </Space>
        {selectedScheme?.match_rule === 'MANUAL' && (
          <Alert type="info" showIcon style={{ marginTop: 10, borderRadius: 10 }}
            message="当前选「手工」方案：请在下方左右两侧勾选单据并填本次核销额，差额闸平衡后点底部「手工核销」。" />
        )}
      </Card>

      {/* 双栏：左债权 右已收 */}
      <Row gutter={14}>
        <ACol span={12}>
          <Card size="small" title={<span style={{ fontWeight: 600 }}>待核销应收（债权侧）</span>}
            extra={<span style={{ fontSize: 12, color: '#777169' }}>{debitItems.length} 张 · 已选 {debitSel.length}</span>}
            style={{ borderRadius: 14 }} styles={{ body: { padding: 0 } }}>
            {loaded && !debitItems.length ? <Empty style={{ padding: 32 }} description="无未核销应收单" /> : (
              <Table size="small" rowKey="id" loading={loading} dataSource={debitItems} columns={debitColumns}
                rowSelection={{ selectedRowKeys: debitSel, onChange: onDebitSelChange }}
                pagination={{ pageSize: 15, size: 'small' }} scroll={{ x: 'max-content', y: 360 }} sticky />
            )}
          </Card>
        </ACol>
        <ACol span={12}>
          <Card size="small" title={<span style={{ fontWeight: 600 }}>待核销收款 / 预收（已收侧）</span>}
            extra={<span style={{ fontSize: 12, color: '#777169' }}>{creditItems.length} 张 · 已选 {creditSel.length}</span>}
            style={{ borderRadius: 14 }} styles={{ body: { padding: 0 } }}>
            {loaded && !creditItems.length ? <Empty style={{ padding: 32 }} description="无未核销收款单" /> : (
              <Table size="small" rowKey="id" loading={loading} dataSource={creditItems} columns={creditColumns}
                rowSelection={{ selectedRowKeys: creditSel, onChange: onCreditSelChange }}
                pagination={{ pageSize: 15, size: 'small' }} scroll={{ x: 'max-content', y: 360 }} sticky />
            )}
          </Card>
        </ACol>
      </Row>

      {/* 底部：本次核销合计 + 差额闸 + 手工核销 */}
      <Card size="small" style={{ borderRadius: 14, marginTop: 14 }}>
        <Row gutter={24} align="middle">
          <ACol><Statistic title="应收侧本次核销额" value={fmtMoney(sums.debit)} valueStyle={{ fontFamily: MONO, fontSize: 20 }} /></ACol>
          <ACol><Statistic title="已收侧本次核销额" value={fmtMoney(sums.credit)} valueStyle={{ fontFamily: MONO, fontSize: 20 }} /></ACol>
          <ACol>
            <Statistic title="差额（应收−已收）" value={fmtMoney(sums.diff)}
              valueStyle={{ fontFamily: MONO, fontSize: 20, color: sums.balanced ? '#389e0d' : '#cf1322' }} />
          </ACol>
          <ACol flex="auto" style={{ textAlign: 'right' }}>
            <Space>
              <Tag color={sums.balanced ? 'green' : 'red'}>{sums.balanced ? '差额闸通过' : '两侧本次额需相等且 > 0'}</Tag>
              <Button type="primary" icon={<LinkOutlined />} loading={submitting}
                disabled={!sums.balanced} onClick={doManualWriteoff}>手工核销</Button>
            </Space>
          </ACol>
        </Row>
      </Card>

      <Divider style={{ margin: '20px 0 12px' }} />

      {/* 反核销：已核销关系 */}
      <Card size="small" title={<span style={{ fontWeight: 600 }}>已核销关系（反核销）</span>}
        extra={(
          <Space>
            <Button size="small" icon={<ReloadOutlined />} loading={linksLoading} onClick={loadLinks}>刷新</Button>
            <Button size="small" danger icon={<RollbackOutlined />} disabled={!linkSel.length} onClick={doUnwriteoff}>
              反核销（{linkSel.length}）
            </Button>
          </Space>
        )}
        style={{ borderRadius: 14 }} styles={{ body: { padding: 0 } }}>
        {!linksLoading && !links.length ? <Empty style={{ padding: 28 }} description="暂无生效核销关系" /> : (
          <Table size="small" rowKey="id" loading={linksLoading} dataSource={links} columns={linkColumns}
            rowSelection={{ selectedRowKeys: linkSel, onChange: setLinkSel }}
            pagination={{ pageSize: 20 }} scroll={{ x: 'max-content' }} />
        )}
      </Card>
    </div>
  );
}

const SCHEME_RULE = { FIFO: '先进先出', SAME_AMOUNT: '同金额', BY_DUEDATE: '按到期日', MANUAL: '手工' };
const dash = <span style={{ color: '#bfbbb5' }}>—</span>;
function money(v) { const n = Number(v); if (!n) return <span style={{ color: '#d9d4cd' }}>—</span>; return <span style={{ fontFamily: MONO }}>{fmtMoney(v)}</span>; }
function woTag(v) { const s = WO_STATUS[v] || { label: statusLabel(v), color: 'default' }; return <Tag color={s.color}>{s.label}</Tag>; }
function Fld({ label, children }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
      <span style={{ fontSize: 11, color: '#777169' }}>{label}</span>
      {children}
    </div>
  );
}
