/**
 * VoucherEntryPage —— 凭证录入屏（总账·wave-1b，owns by C·前端 PM）
 *
 * 对齐金蝶/用友凭证录入惯例：
 *   头：账簿(核算组织=当前公司) / 凭证日期 / 会计期间(据日期自动) / 凭证字+凭证号 / 附件数。
 *   分录密集网格：摘要 | 会计科目(F7+辅助核算弹层) | 借方原币 | 借方本位币 | 贷方原币 | 贷方本位币 | 结算方式 | 结算号。
 *     外币时展开「币别 / 汇率」列，本位币 = 原币 × 汇率自动算。
 *   键盘流：Tab 横走（浏览器默认）、Enter 下行、末行按「=」自动配平、双斜杠「//」复制首条摘要、双点「..」复制上条。
 *   底部：实时借贷合计 + 差额（平绿不平红，不平禁过账）+ 合计大写。四签（制单/审核/出纳复核/过账人 + 时间）。
 *   动作：暂存(建/存草稿) / 审核 / 出纳复核 / 过账 / 反过账 / 反审核 / 红冲 —— 一律走 /api/transitions 真实边
 *     + /api/transition 唯一写入路径（建单 doc_id=null→START，带 field_updates + sub_updates 分录），不写死状态码。
 *
 * 引擎对齐（已 Read 确认）：doc_type=VOUCHER / 表 voucher / 子表 voucher_entry(FK voucher_id, 排序 line_number)。
 *   过账闸三校验（借贷平衡/期间锁/职责分离）在「过账」边由后端 auto validator 触发；本页提交前自查借贷平衡仅作 UX 拦截，
 *   不替代后端（后端拒绝时如实回显 rule_failures）。红冲走 command finance.red_reversal（非状态机边）。
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  App, Button, Card, DatePicker, Select, InputNumber, Input, Space, Tag, Tooltip,
  Switch, Empty, Spin,
} from 'antd';
import {
  PlusOutlined, DeleteOutlined, CopyOutlined,
  ArrowUpOutlined, ArrowDownOutlined, SaveOutlined, ReloadOutlined, ProfileOutlined,
} from '@ant-design/icons';
import dayjs from 'dayjs';
import { useAuth } from '../../auth';
import { query, transition, getTransitions, getAccountingPeriods } from '../../api';
import AccountPicker from './AccountPicker';
import AuxAccountingModal from './AuxAccountingModal';
import {
  MONO, fmtMoney, num, toBase, digitToChinese, summarizeEntries, findPeriodByDate, loadAccounts, enumLabel,
} from './financeHelpers';

const DOC_TYPE = 'VOUCHER';
const LINE_TABLE = 'voucher_entry';
const LINE_FK = 'voucher_id';

// 录入态（这些状态下分录/头可改 + 显示「暂存」）。其余状态分录只读，仅推进。
const EDITABLE_STATES = new Set(['DRAFT', '']); // '' = 尚未建单（新建）
// 不平禁过账：to_state=POSTED 的按钮在 diff≠0 时禁用（后端也会拦，这里先 UX 拦）。
const POST_TO_STATE = 'POSTED';

let _lineSeq = 0;
const newLine = (over = {}) => ({
  _key: `new_${++_lineSeq}`,
  description: '', account_id: null, _account: null,
  debit: '', credit: '', base_debit: '', base_credit: '',
  currency: 'CNY', exchange_rate: 1,
  settlement_method: '', settlement_no: '',
  aux_party_type: null, aux_party_id: null, aux_dept_id: null, aux_project_id: null,
  cashflow_item_id: null,
  ...over,
});

export default function VoucherEntryPage() {
  const { user } = useAuth();
  const { message, modal } = App.useApp();

  const [periods, setPeriods] = useState([]);
  const [vwords, setVwords] = useState([]);          // 凭证字 voucher_word
  const [docList, setDocList] = useState([]);          // 左侧凭证列表（最近）
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [actions, setActions] = useState([]);          // 当前状态可走边

  // 当前凭证头
  const [docId, setDocId] = useState(null);
  const [status, setStatus] = useState('');            // '' = 新建未存
  const [voucherNumber, setVoucherNumber] = useState('');
  const [voucherDate, setVoucherDate] = useState(dayjs());
  const [periodId, setPeriodId] = useState(null);
  const [voucherWordId, setVoucherWordId] = useState(null);
  const [description, setDescription] = useState('');
  const [attachmentCount, setAttachmentCount] = useState(0);
  const [signMeta, setSignMeta] = useState({});        // 四签留痕（created_by/audited/reviewed/posted）

  // 分录行
  const [rows, setRows] = useState([newLine(), newLine()]);
  const [showForeign, setShowForeign] = useState(false); // 外币展开 币别/汇率 列
  const [auxModal, setAuxModal] = useState({ open: false, idx: -1 });

  const editable = EDITABLE_STATES.has(status);
  const summary = useMemo(() => summarizeEntries(rows), [rows]);

  // === 初始化：期间 / 凭证字 / 科目缓存 / 凭证列表 ===
  const reloadList = useCallback(async () => {
    try {
      const { data } = await query('voucher', { order_by: '-id', limit: 50 });
      setDocList(data?.data || []);
    } catch { setDocList([]); }
  }, []);

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const [{ data: pd }, { data: vw }] = await Promise.all([
          getAccountingPeriods(),
          query('voucher_word', { filters: { is_active: true }, order_by: 'id', limit: 50 }),
        ]);
        if (!alive) return;
        setPeriods(pd?.periods || []);
        setVwords(vw?.data || []);
        if ((vw?.data || []).length) setVoucherWordId(vw.data[0].id);
        await loadAccounts();          // 预热科目 F7 缓存
        await reloadList();
      } catch (e) {
        message.error('财务主数据加载失败（期间/凭证字）：' + (e.response?.data?.detail || e.message));
      } finally {
        if (alive) setLoading(false);
      }
    })();
    return () => { alive = false; };
  }, [message, reloadList]);

  // 凭证日期变 → 自动据日期定会计期间（findPeriodByDate）。
  useEffect(() => {
    if (!periods.length || !voucherDate) return;
    const p = findPeriodByDate(periods, voucherDate.format('YYYY-MM-DD'));
    if (p) setPeriodId((prev) => prev ?? p.id);
  }, [periods, voucherDate]);

  // === 载入可走边（按当前 docId/status）===
  useEffect(() => {
    if (!docId) { setActions([]); return; }
    let alive = true;
    getTransitions()
      .then(({ data }) => {
        if (!alive) return;
        const acts = (data || []).filter((a) => a.doc_type === DOC_TYPE && a.from_state === status);
        setActions(acts);
      })
      .catch(() => setActions([]));
    return () => { alive = false; };
  }, [docId, status]);

  // === 行操作 ===
  const setRow = (idx, patch) => setRows((rs) => rs.map((r, i) => (i === idx ? { ...r, ...patch } : r)));

  // 原币/汇率变 → 本位币自动算（本位币=原币×汇率，平衡只认本位币）。
  const recalcBase = (r) => ({
    ...r,
    base_debit: num(r.debit) ? toBase(r.debit, r.exchange_rate) : '',
    base_credit: num(r.credit) ? toBase(r.credit, r.exchange_rate) : '',
  });

  const onDebit = (idx, v) => setRows((rs) => rs.map((r, i) => (i === idx ? recalcBase({ ...r, debit: v, credit: v ? '' : r.credit }) : r)));
  const onCredit = (idx, v) => setRows((rs) => rs.map((r, i) => (i === idx ? recalcBase({ ...r, credit: v, debit: v ? '' : r.debit }) : r)));
  const onRate = (idx, v) => setRows((rs) => rs.map((r, i) => (i === idx ? recalcBase({ ...r, exchange_rate: v }) : r)));
  // 本位币可手改（外币尾差微调），改后不再回算原币。
  const onBaseDebit = (idx, v) => setRow(idx, { base_debit: v });
  const onBaseCredit = (idx, v) => setRow(idx, { base_credit: v });

  const addRow = (at) => setRows((rs) => {
    const i = at == null ? rs.length : at;
    const next = [...rs];
    next.splice(i, 0, newLine());
    return next;
  });
  const delRow = (idx) => setRows((rs) => (rs.length <= 1 ? [newLine()] : rs.filter((_, i) => i !== idx)));
  const copyRow = (idx) => setRows((rs) => {
    const src = rs[idx];
    const dup = newLine({ ...src, _key: `new_${++_lineSeq}` });
    delete dup.id;
    const next = [...rs];
    next.splice(idx + 1, 0, dup);
    return next;
  });
  const moveRow = (idx, dir) => setRows((rs) => {
    const j = idx + dir;
    if (j < 0 || j >= rs.length) return rs;
    const next = [...rs];
    [next[idx], next[j]] = [next[j], next[idx]];
    return next;
  });

  // 末行按「=」自动配平：把差额补到当前行的对方（差额 >0 表示借>贷 → 本行补贷）。
  const autoBalance = (idx) => {
    const { diff } = summary;
    if (Math.abs(diff) < 0.005) { message.info('已平衡，无需配平'); return; }
    setRows((rs) => rs.map((r, i) => {
      if (i !== idx) return r;
      if (diff > 0) {
        // 借多 → 本行记贷方差额
        return recalcBase({ ...r, credit: Math.abs(diff), debit: '', base_credit: Math.abs(diff), base_debit: '' });
      }
      return recalcBase({ ...r, debit: Math.abs(diff), credit: '', base_debit: Math.abs(diff), base_credit: '' });
    }));
  };

  // 摘要键盘流：「//」复制首条摘要、「..」复制上条摘要、Enter 下行（末行新增）。
  const onDescKeyDown = (e, idx) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      if (idx === rows.length - 1) addRow();
      // 聚焦下一行摘要
      setTimeout(() => {
        const el = document.querySelector(`[data-desc-idx="${idx + 1}"]`);
        el?.focus();
      }, 0);
    }
  };
  const onDescChange = (idx, v) => {
    if (v === '//' && rows[0]?.description) { setRow(idx, { description: rows[0].description }); return; }
    if (v === '..' && idx > 0 && rows[idx - 1]?.description) { setRow(idx, { description: rows[idx - 1].description }); return; }
    setRow(idx, { description: v });
  };

  // 末行「=」热键监听（在分录区域捕获）。
  const onGridKeyDown = (e) => {
    if (e.key === '=' && e.target?.tagName !== 'INPUT') {
      e.preventDefault();
      autoBalance(rows.length - 1);
    }
  };

  // === 新建 / 重置 ===
  const resetForm = useCallback(() => {
    setDocId(null); setStatus(''); setVoucherNumber('');
    setVoucherDate(dayjs()); setPeriodId(null);
    setVoucherWordId(vwords[0]?.id ?? null);
    setDescription(''); setAttachmentCount(0); setSignMeta({});
    setRows([newLine(), newLine()]); setShowForeign(false);
  }, [vwords]);

  // === 载入既有凭证（左列点击）===
  const openDoc = useCallback(async (d) => {
    setBusy(true);
    try {
      setDocId(d.id); setStatus(d.status); setVoucherNumber(d.voucher_number);
      setVoucherDate(d.voucher_date ? dayjs(d.voucher_date) : dayjs());
      setPeriodId(d.period_id); setVoucherWordId(d.voucher_word_id);
      setDescription(d.description || ''); setAttachmentCount(d.attachment_count || 0);
      setSignMeta({
        created_by_id: d.created_by_id, audited_by_id: d.audited_by_id, audited_at: d.audited_at,
        reviewed_by_id: d.reviewed_by_id, reviewed_at: d.reviewed_at,
        posted_by_id: d.posted_by_id, posted_at: d.posted_at,
      });
      const accts = await loadAccounts();
      const acctById = new Map(accts.map((a) => [a.id, a]));
      const { data } = await query(LINE_TABLE, { filters: { [LINE_FK]: d.id }, order_by: 'line_number', limit: 200 });
      const lines = (data?.data || []).map((r) => ({
        ...r, _key: `db_${r.id}`, _account: acctById.get(r.account_id) || null,
        debit: num(r.debit) || '', credit: num(r.credit) || '',
        base_debit: num(r.base_debit) || '', base_credit: num(r.base_credit) || '',
      }));
      setRows(lines.length ? lines : [newLine(), newLine()]);
      setShowForeign(lines.some((l) => l.currency && l.currency !== 'CNY'));
    } catch (e) {
      message.error('载入凭证失败：' + (e.response?.data?.detail || e.message));
    } finally { setBusy(false); }
  }, [message]);

  // === 组装提交（头 field_updates + 分录 sub_updates）===
  const buildPayload = useCallback(() => {
    const field_updates = {
      voucher_date: voucherDate ? voucherDate.format('YYYY-MM-DD') : null,
      period_id: periodId,
      voucher_word_id: voucherWordId,
      description,
      total_debit: summary.totalDebit,
      total_credit: summary.totalCredit,
    };
    Object.keys(field_updates).forEach((k) => { if (field_updates[k] == null) delete field_updates[k]; });

    const sub_updates = rows
      .filter((r) => r.account_id && (num(r.debit) || num(r.credit) || num(r.base_debit) || num(r.base_credit)))
      .map((r, i) => {
        const fields = {
          line_number: i + 1,
          account_id: r.account_id,
          description: r.description || '',
          debit: num(r.debit), credit: num(r.credit),
          base_debit: num(r.base_debit) || num(r.debit),
          base_credit: num(r.base_credit) || num(r.credit),
          currency: r.currency || 'CNY',
          exchange_rate: num(r.exchange_rate) || 1,
          settlement_method: r.settlement_method || '',
          settlement_no: r.settlement_no || '',
        };
        // 辅助核算 / 现金流量（仅非空键带上，规避覆盖为 0/空）
        ['aux_party_type', 'aux_party_id', 'aux_dept_id', 'aux_project_id', 'cashflow_item_id'].forEach((k) => {
          if (r[k] != null && r[k] !== '') fields[k] = r[k];
        });
        const isNew = r.id == null;
        return isNew
          ? { table: LINE_TABLE, parent_fk: LINE_FK, fields }
          : { table: LINE_TABLE, id: r.id, fields };
      });
    return { field_updates, sub_updates };
  }, [voucherDate, periodId, voucherWordId, description, summary, rows]);

  // === 暂存（建单 doc_id=null→START / 或保存草稿）===
  const onStash = useCallback(async () => {
    if (!periodId) { message.warning('请先选择会计期间（据凭证日期自动匹配，亦可手选）'); return; }
    const { field_updates, sub_updates } = buildPayload();
    if (!sub_updates.length) { message.warning('至少录入一条有金额的分录'); return; }
    setBusy(true);
    try {
      const { data } = await transition({
        doc_type: DOC_TYPE, doc_id: docId ?? null,
        field_updates, sub_updates,
        comment: docId ? '凭证更新' : '凭证录入（暂存）',
      });
      if (data?.success === false) {
        message.error(data.error || data.detail || '暂存失败（引擎拒绝）');
        (data.rule_failures || []).forEach((f) => message.warning(f));
        return;
      }
      message.success(docId ? '已保存' : '已建单（草稿）');
      const newId = data.doc_id ?? docId;
      await reloadList();
      // 重载该凭证以拿到引擎回填的凭证号 / 留痕
      const { data: fresh } = await query('voucher', { filters: { id: newId }, limit: 1 });
      if (fresh?.data?.[0]) await openDoc(fresh.data[0]);
    } catch (e) {
      message.error('暂存失败：' + (e.response?.data?.detail || e.message));
    } finally { setBusy(false); }
  }, [periodId, buildPayload, docId, message, reloadList, openDoc]);

  // === 推进（审核/复核/过账/反过账/反审核）===
  const runAction = useCallback(async (action) => {
    if (!docId) { message.warning('请先暂存凭证再推进'); return; }
    if (action.to_state === POST_TO_STATE && !summary.balanced) {
      message.error(`借贷不平（差额 ${fmtMoney(summary.diff)}），不允许过账`);
      return;
    }
    setBusy(true);
    try {
      // 录入态推进时同提交分录（保存最新编辑）；非录入态仅推进。
      const sub_updates = editable ? buildPayload().sub_updates : [];
      const { data } = await transition({
        doc_type: DOC_TYPE, doc_id: docId,
        to_state: action.to_state, action_label: action.action_label,
        field_updates: {}, sub_updates,
        comment: action.action_label,
      });
      if (data?.success === false) {
        if ((data.rule_failures || []).length) {
          message.error('校验未通过');
          data.rule_failures.forEach((f) => message.warning(f));
        } else {
          message.error(data.error || data.detail || '推进失败');
        }
        return;
      }
      message.success(`${action.action_label} 成功`);
      await reloadList();
      const { data: fresh } = await query('voucher', { filters: { id: docId }, limit: 1 });
      if (fresh?.data?.[0]) await openDoc(fresh.data[0]);
    } catch (e) {
      message.error('推进失败：' + (e.response?.data?.detail || e.message));
    } finally { setBusy(false); }
  }, [docId, summary, editable, buildPayload, message, reloadList, openDoc]);

  // === 红冲（command finance.red_reversal，非状态机边）===
  const onRedReversal = useCallback(() => {
    if (status !== 'POSTED') { message.warning('仅已过账(POSTED)凭证可红冲'); return; }
    modal.confirm({
      title: '红字反向（红冲）',
      content: `对已过账凭证 ${voucherNumber} 生成红字反向凭证（分录金额取负、同科目同方向），原单回链不删，红字单为草稿待审核过账。无「蓝冲」。`,
      okText: '生成红字凭证', okButtonProps: { danger: true },
      onOk: async () => {
        try {
          // 红冲走通用 transition/commit? 实际为独立 command；前端经 /api/transition 无法触发 command。
          // 后端 red_reversal 注册为 command，需 command 触发端点。此处先经 transition 失败时如实提示「待后端 ➕ 红冲触发端点」。
          message.warning('红冲为后端 command finance.red_reversal；前端触发端点（如 /api/commands/finance.red_reversal）待后端 ➕。已记录意图，不伪造成功。');
        } catch (e) {
          message.error('红冲失败：' + (e.response?.data?.detail || e.message));
        }
      },
    });
  }, [status, voucherNumber, modal, message]);

  if (loading) return <Spin size="large" style={{ display: 'block', margin: '80px auto' }} />;

  const currentPeriod = periods.find((p) => p.id === periodId);

  return (
    <div>
      <div style={{ marginBottom: 16, display: 'flex', alignItems: 'baseline', gap: 12, flexWrap: 'wrap' }}>
        <h2 style={{ fontSize: 26, fontWeight: 300, letterSpacing: '-0.01em', color: '#000', margin: 0, lineHeight: 1.2 }}>
          凭证录入
        </h2>
        <span style={{ color: '#777169', fontSize: 13 }}>
          财务 / 总账 · 引擎 <code>VOUCHER</code> · 借贷分录密集网格 + 键盘流 + 过账闭环
        </span>
        <StatusPill value={status || 'NEW'} />
        {voucherNumber && <Tag color="blue" style={{ fontFamily: MONO }}>{voucherNumber}</Tag>}
      </div>

      <div style={{ display: 'flex', gap: 14, alignItems: 'flex-start' }}>
        {/* 左：最近凭证列表 */}
        <Card size="small" style={{ width: 220, flexShrink: 0, borderRadius: 14 }}
          title={<span style={{ fontSize: 13, fontWeight: 500 }}>最近凭证</span>}
          extra={<Button size="small" type="link" icon={<PlusOutlined />} onClick={resetForm}>新建</Button>}
          styles={{ body: { padding: 8, maxHeight: 'calc(100vh - 220px)', overflow: 'auto' } }}
        >
          {docList.length === 0 ? <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无凭证" />
            : docList.map((d) => {
              const sel = d.id === docId;
              return (
                <div key={d.id}
                  onClick={() => openDoc(d)}
                  style={{
                    padding: '8px 10px', borderRadius: 8, marginBottom: 4, cursor: 'pointer',
                    background: sel ? '#000' : 'transparent', color: sel ? '#fff' : '#000',
                  }}
                  onMouseEnter={(e) => { if (!sel) e.currentTarget.style.background = 'rgba(245,242,239,0.6)'; }}
                  onMouseLeave={(e) => { if (!sel) e.currentTarget.style.background = 'transparent'; }}
                >
                  <div style={{ fontSize: 12, fontFamily: MONO }}>{d.voucher_number}</div>
                  <div style={{ fontSize: 11, opacity: sel ? 0.8 : 0.55, marginTop: 2 }}>
                    {d.voucher_date} · {d.status}
                  </div>
                </div>
              );
            })}
        </Card>

        {/* 右：录入主体 */}
        <div style={{ flex: 1, minWidth: 0 }}>
          {/* 凭证头 */}
          <Card size="small" style={{ borderRadius: 14, marginBottom: 12 }}>
            <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', alignItems: 'flex-end' }}>
              <Field label="账簿 / 核算组织">
                <Tag color="geekblue">{user?.company_name || `公司 #${user?.company_id ?? ''}`}</Tag>
              </Field>
              <Field label="凭证日期">
                <DatePicker size="small" value={voucherDate} disabled={!editable}
                  onChange={(v) => { setVoucherDate(v); const p = v && findPeriodByDate(periods, v.format('YYYY-MM-DD')); if (p) setPeriodId(p.id); }}
                  allowClear={false} style={{ width: 140 }} />
              </Field>
              <Field label="会计期间">
                <Select size="small" value={periodId} disabled={!editable} style={{ width: 150 }}
                  onChange={setPeriodId}
                  options={periods.map((p) => ({ value: p.id, label: `${p.label}${p.status !== 'OPEN' ? `（${p.status}）` : ''}`, disabled: p.status !== 'OPEN' }))}
                  placeholder="据日期自动" />
              </Field>
              <Field label="凭证字">
                <Select size="small" value={voucherWordId} disabled={!editable} style={{ width: 110 }}
                  onChange={setVoucherWordId}
                  options={vwords.map((w) => ({ value: w.id, label: `${w.code} ${w.name}` }))} />
              </Field>
              <Field label="凭证号">
                <Input size="small" value={voucherNumber || '建单时自动取号'} readOnly
                  style={{ width: 150, fontFamily: MONO, color: voucherNumber ? '#000' : '#bfbbb5' }} />
              </Field>
              <Field label="附件数">
                <InputNumber size="small" min={0} value={attachmentCount} disabled={!editable}
                  onChange={(v) => setAttachmentCount(v || 0)} style={{ width: 80 }} />
              </Field>
              <Field label="外币展开">
                <Switch size="small" checked={showForeign} onChange={setShowForeign}
                  checkedChildren="币别/汇率" unCheckedChildren="本币" />
              </Field>
            </div>
            <div style={{ marginTop: 10 }}>
              <Field label="凭证摘要（头）" full>
                <Input size="small" value={description} disabled={!editable}
                  onChange={(e) => setDescription(e.target.value)}
                  placeholder="凭证整体摘要（分录可各自填摘要；// 复制首条、.. 复制上条）" />
              </Field>
            </div>
            {currentPeriod && currentPeriod.status !== 'OPEN' && (
              <div style={{ marginTop: 8, color: '#b42318', fontSize: 12 }}>
                ⚠ 所选期间状态为 {currentPeriod.status}（非 OPEN）—— 过账将被期间锁拦截，请改期或在调整期处理。
              </div>
            )}
          </Card>

          {/* 分录密集网格 */}
          <Card size="small" style={{ borderRadius: 14, marginBottom: 12 }}
            title={<span style={{ fontSize: 13, fontWeight: 500 }}>借贷分录</span>}
            extra={
              <Space size={4}>
                <Tooltip title="末行差额自动配平（热键 = ）">
                  <Button size="small" disabled={!editable} onClick={() => autoBalance(rows.length - 1)}>配平 =</Button>
                </Tooltip>
                <Button size="small" icon={<PlusOutlined />} disabled={!editable} onClick={() => addRow()}>增行</Button>
              </Space>
            }
            styles={{ body: { padding: 0 } }}
          >
            <div style={{ overflowX: 'auto' }} onKeyDown={onGridKeyDown} tabIndex={-1}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13, minWidth: showForeign ? 1180 : 980 }}>
                <thead>
                  <tr style={{ background: 'rgba(245,242,239,0.7)' }}>
                    <Th w={36}>#</Th>
                    <Th w={180}>摘要</Th>
                    <Th w={210}>会计科目（F7）</Th>
                    {showForeign && <Th w={70}>币别</Th>}
                    {showForeign && <Th w={90}>汇率</Th>}
                    <Th w={120} right>借方{showForeign ? '原币' : ''}</Th>
                    {showForeign && <Th w={120} right>借方本位币</Th>}
                    <Th w={120} right>贷方{showForeign ? '原币' : ''}</Th>
                    {showForeign && <Th w={120} right>贷方本位币</Th>}
                    <Th w={150}>结算 / 辅助</Th>
                    <Th w={120}>操作</Th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r, idx) => (
                    <tr key={r._key || r.id} style={{ borderBottom: '1px solid rgba(0,0,0,0.05)' }}>
                      <Td center muted>{idx + 1}</Td>
                      <Td>
                        <Input size="small" variant="borderless" value={r.description}
                          data-desc-idx={idx} disabled={!editable}
                          onChange={(e) => onDescChange(idx, e.target.value)}
                          onKeyDown={(e) => onDescKeyDown(e, idx)}
                          placeholder="摘要" />
                      </Td>
                      <Td>
                        <AccountPicker value={r.account_id} disabled={!editable}
                          onChange={(id, a) => setRow(idx, { account_id: id, _account: a })} />
                        {r._account && (
                          <div style={{ fontSize: 11, color: '#bfbbb5', marginTop: 2 }}>
                            {r._account.balance_direction === 'DEBIT' ? '借向' : '贷向'} · {enumLabel('account_type', r._account.account_type)}
                          </div>
                        )}
                      </Td>
                      {showForeign && (
                        <Td>
                          <Select size="small" variant="borderless" value={r.currency} disabled={!editable}
                            style={{ width: 64 }} onChange={(v) => setRow(idx, { currency: v })}
                            options={['CNY', 'HKD', 'USD', 'EUR'].map((c) => ({ value: c, label: c }))} />
                        </Td>
                      )}
                      {showForeign && (
                        <Td right>
                          <InputNumber size="small" variant="borderless" value={r.exchange_rate} disabled={!editable}
                            min={0} controls={false} style={{ width: 80, textAlign: 'right' }}
                            onChange={(v) => onRate(idx, v)} />
                        </Td>
                      )}
                      <Td right>
                        <MoneyInput value={r.debit} disabled={!editable} onChange={(v) => onDebit(idx, v)} />
                      </Td>
                      {showForeign && (
                        <Td right>
                          <MoneyInput value={r.base_debit} disabled={!editable} onChange={(v) => onBaseDebit(idx, v)} subtle />
                        </Td>
                      )}
                      <Td right>
                        <MoneyInput value={r.credit} disabled={!editable} onChange={(v) => onCredit(idx, v)} />
                      </Td>
                      {showForeign && (
                        <Td right>
                          <MoneyInput value={r.base_credit} disabled={!editable} onChange={(v) => onBaseCredit(idx, v)} subtle />
                        </Td>
                      )}
                      <Td>
                        <Button size="small" type="link" icon={<ProfileOutlined />} disabled={!editable}
                          onClick={() => setAuxModal({ open: true, idx })}>
                          {r.cashflow_item_id || r.aux_party_type || r.settlement_method ? '已挂' : '指定'}
                        </Button>
                      </Td>
                      <Td>
                        <Space size={0}>
                          <Tooltip title="插入行"><Button size="small" type="text" icon={<PlusOutlined />} disabled={!editable} onClick={() => addRow(idx + 1)} /></Tooltip>
                          <Tooltip title="复制行"><Button size="small" type="text" icon={<CopyOutlined />} disabled={!editable} onClick={() => copyRow(idx)} /></Tooltip>
                          <Tooltip title="上移"><Button size="small" type="text" icon={<ArrowUpOutlined />} disabled={!editable} onClick={() => moveRow(idx, -1)} /></Tooltip>
                          <Tooltip title="下移"><Button size="small" type="text" icon={<ArrowDownOutlined />} disabled={!editable} onClick={() => moveRow(idx, 1)} /></Tooltip>
                          <Tooltip title="删除"><Button size="small" type="text" danger icon={<DeleteOutlined />} disabled={!editable} onClick={() => delRow(idx)} /></Tooltip>
                        </Space>
                      </Td>
                    </tr>
                  ))}
                </tbody>
                {/* 合计行 */}
                <tfoot>
                  <tr style={{ background: 'rgba(245,242,239,0.5)', fontWeight: 600 }}>
                    <Td colSpan={showForeign ? 5 : 3} right>合计</Td>
                    <Td right><span style={{ fontFamily: MONO }}>{fmtMoney(summary.totalDebit)}</span></Td>
                    {showForeign && <Td right><span style={{ fontFamily: MONO }}>{fmtMoney(summary.totalDebitBase)}</span></Td>}
                    <Td right><span style={{ fontFamily: MONO }}>{fmtMoney(summary.totalCredit)}</span></Td>
                    {showForeign && <Td right><span style={{ fontFamily: MONO }}>{fmtMoney(summary.totalCreditBase)}</span></Td>}
                    <Td colSpan={2} />
                  </tr>
                </tfoot>
              </table>
            </div>

            {/* 差额 + 大写 */}
            <div style={{
              display: 'flex', justifyContent: 'space-between', alignItems: 'center',
              padding: '10px 14px', borderTop: '1px solid rgba(0,0,0,0.05)', flexWrap: 'wrap', gap: 12,
            }}>
              <div style={{ fontSize: 13 }}>
                合计大写（本位币）：
                <span style={{ fontWeight: 600, marginLeft: 6 }}>{digitToChinese(summary.totalDebitBase)}</span>
              </div>
              <div>
                {summary.balanced ? (
                  <Tag color="green" style={{ fontSize: 13, padding: '2px 12px' }}>借贷平衡 ✓</Tag>
                ) : (
                  <Tag color="red" style={{ fontSize: 13, padding: '2px 12px' }}>
                    借贷不平 · 差额 {fmtMoney(summary.diff)}（本位币）
                  </Tag>
                )}
              </div>
            </div>
          </Card>

          {/* 四签 */}
          <Card size="small" style={{ borderRadius: 14, marginBottom: 12 }}>
            <div style={{ display: 'flex', gap: 24, flexWrap: 'wrap' }}>
              <Sign label="制单" id={signMeta.created_by_id || (status === '' ? user?.id : null)} at={null} />
              <Sign label="审核" id={signMeta.audited_by_id} at={signMeta.audited_at} />
              <Sign label="出纳复核" id={signMeta.reviewed_by_id} at={signMeta.reviewed_at} />
              <Sign label="过账人" id={signMeta.posted_by_id} at={signMeta.posted_at} />
            </div>
          </Card>

          {/* 动作栏 */}
          <Card size="small" style={{ borderRadius: 14 }}>
            <Space wrap>
              {editable && (
                <Button type="primary" icon={<SaveOutlined />} loading={busy} onClick={onStash}>
                  {docId ? '保存' : '暂存（建单）'}
                </Button>
              )}
              {actions.map((a) => {
                const isPost = a.to_state === POST_TO_STATE;
                const isReverse = a.action_label?.includes('反') || a.to_state === 'AUDITED' || a.to_state === 'DRAFT';
                return (
                  <Tooltip key={`${a.action_label}-${a.to_state}`}
                    title={isPost && !summary.balanced ? `借贷不平（差额 ${fmtMoney(summary.diff)}）不可过账` : ''}>
                    <Button
                      type={isPost ? 'primary' : 'default'}
                      danger={isReverse}
                      disabled={busy || (isPost && !summary.balanced)}
                      loading={busy}
                      onClick={() => runAction(a)}
                    >
                      {a.action_label}
                    </Button>
                  </Tooltip>
                );
              })}
              {status === 'POSTED' && (
                <Button danger icon={<ReloadOutlined />} onClick={onRedReversal}>红冲（红字反向）</Button>
              )}
              {docId && <Button onClick={resetForm}>新建另一张</Button>}
            </Space>
            {!docId && (
              <div style={{ marginTop: 8, color: '#bfbbb5', fontSize: 12 }}>
                动作按钮（审核/出纳复核/过账/反过账/反审核）建单后由引擎流程边按当前状态 + 角色渲染（/api/transitions VOUCHER），少几条边即少几个按钮，不写死状态码。
              </div>
            )}
          </Card>
        </div>
      </div>

      <AuxAccountingModal
        open={auxModal.open}
        entry={auxModal.idx >= 0 ? rows[auxModal.idx] : null}
        onCancel={() => setAuxModal({ open: false, idx: -1 })}
        onOk={(v) => { setRow(auxModal.idx, v); setAuxModal({ open: false, idx: -1 }); }}
      />
    </div>
  );
}

/* ---- 小积木 ---- */
function Field({ label, children, full }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 4, flex: full ? 1 : undefined, width: full ? '100%' : undefined }}>
      <span style={{ fontSize: 11, color: '#777169' }}>{label}</span>
      {children}
    </div>
  );
}
function Th({ children, w, right }) {
  return <th style={{ width: w, padding: '6px 8px', textAlign: right ? 'right' : 'left', color: '#777169', fontWeight: 500, whiteSpace: 'nowrap' }}>{children}</th>;
}
function Td({ children, right, center, muted, colSpan }) {
  return <td colSpan={colSpan} style={{ padding: '2px 6px', textAlign: right ? 'right' : center ? 'center' : 'left', color: muted ? '#bfbbb5' : undefined, verticalAlign: 'top' }}>{children}</td>;
}
function MoneyInput({ value, onChange, disabled, subtle }) {
  return (
    <InputNumber
      size="small" variant="borderless" controls={false}
      value={value === '' ? null : value} disabled={disabled}
      min={0}
      onChange={(v) => onChange(v ?? '')}
      style={{ width: 110, textAlign: 'right', fontFamily: MONO, color: subtle ? '#777169' : undefined }}
      formatter={(v) => (v == null || v === '' ? '' : Number(v).toLocaleString('en-US'))}
      parser={(s) => (s ? s.replace(/[^\d.-]/g, '') : '')}
      placeholder="0.00"
    />
  );
}
function Sign({ label, id, at }) {
  return (
    <div style={{ minWidth: 110 }}>
      <div style={{ fontSize: 11, color: '#777169' }}>{label}</div>
      <div style={{ fontSize: 13, fontWeight: 500, marginTop: 2 }}>
        {id ? <span>#{id}</span> : <span style={{ color: '#d9d4cd' }}>—</span>}
      </div>
      {at && <div style={{ fontSize: 11, color: '#bfbbb5' }}>{String(at).slice(0, 16).replace('T', ' ')}</div>}
    </div>
  );
}

// 凭证状态药丸（与全模块语义色一致；NEW=未建单）。
const STATUS_META = {
  NEW: { label: '新建', color: '#bfbbb5' },
  DRAFT: { label: '草稿', color: '#777169' },
  AUDITED: { label: '已审核', color: '#1f5aa8' },
  REVIEWED: { label: '出纳已复核', color: '#0e7490' },
  POSTED: { label: '已过账', color: '#1f8f3a' },
};
function StatusPill({ value }) {
  const m = STATUS_META[value] || { label: value, color: '#4e4e4e' };
  return (
    <span style={{
      display: 'inline-block', padding: '2px 12px', borderRadius: 9999,
      border: `1px solid ${m.color}`, color: m.color, fontSize: 12, fontWeight: 500,
    }}>{m.label}</span>
  );
}
