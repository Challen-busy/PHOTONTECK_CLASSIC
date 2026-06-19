/**
 * PeriodClosePage —— 期末结账向导（总账·finance-gl wave-2，模块 B）
 *
 * 对齐金蝶「选账簿 → 执行 → 回执」期末惯例。录音顺序：过账 → 调汇 → 结转损益 → 结账。
 *   头：账簿/核算组织（= 当前公司，会话隔离只读）+ 会计期间选择（OPEN/CLOSED 状态可见）。
 *   分步向导（Steps）：
 *     1 期末调汇 —— 预览外币货币性科目重估差额 → 生成调汇凭证（草稿，需财务过账）。
 *     2 结转损益 —— 预览收入/费用结转到本年利润 → 生成结转凭证（草稿，需财务过账）。
 *     3 期末结账 —— 前置校验清单（本期无未过账凭证/试算平衡/调汇+结转已过账/逐月上期已结）→ 锁期 CLOSED。
 *   每步：前置/预览清单 + 执行按钮 + 结果回执（凭证号/差额/校验逐项 √×）。
 *   反结账：已结账期间提供「反结账」（CLOSED→OPEN，逐月），错账重做。
 *
 * 引擎对齐：调后端命令 finance.fx_revaluation / carry_forward_pl / close_period / reopen_period
 *   （经 /api/finance/period-close/* 路由 → execute_command）。生成的期末凭证走标准 VOUCHER 状态机
 *   审核/过账（本页不绕过过账闸）—— 生成草稿后请到「凭证录入」页审核过账，再回本页结账。
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  App, Button, Card, Select, Steps, Tag, Space, Table, Alert, Spin, Descriptions, Result, Tooltip,
} from 'antd';
import {
  SwapOutlined, FundOutlined, LockOutlined, UnlockOutlined, ReloadOutlined, CheckCircleTwoTone,
  CloseCircleTwoTone, FileDoneOutlined,
} from '@ant-design/icons';
import api from '../../api';
import { getAccountingPeriods } from '../../api';
import { useAuth } from '../../auth';
import { MONO, fmtMoney, statusLabel } from './financeHelpers';

const STEP_KEYS = ['fx', 'pl', 'close'];

// 期末结账命令端点（main.py 已 include routers/finance_period_close）。
const EP = {
  fxPreview: '/finance/period-close/fx-revaluation',
  fx: '/finance/period-close/fx-revaluation',
  plPreview: '/finance/period-close/carry-forward-pl',
  pl: '/finance/period-close/carry-forward-pl',
  precheck: '/finance/period-close/precheck',
  close: '/finance/period-close/close',
  reopen: '/finance/period-close/reopen',
};

export default function PeriodClosePage() {
  const { user } = useAuth();
  const { message, modal } = App.useApp();

  const [periods, setPeriods] = useState([]);
  const [periodId, setPeriodId] = useState(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [step, setStep] = useState(0);

  // 各步预览 / 回执缓存（按 period 重置）。
  const [fxPreview, setFxPreview] = useState(null);
  const [fxReceipt, setFxReceipt] = useState(null);
  const [plPreview, setPlPreview] = useState(null);
  const [plReceipt, setPlReceipt] = useState(null);
  const [checks, setChecks] = useState(null);
  const [closeReceipt, setCloseReceipt] = useState(null);

  const period = useMemo(() => periods.find((p) => p.id === periodId) || null, [periods, periodId]);
  const isClosed = period?.status === 'CLOSED';
  const isOpen = period?.status === 'OPEN';

  const reloadPeriods = useCallback(async () => {
    const { data } = await getAccountingPeriods();
    setPeriods(data?.periods || []);
    return data?.periods || [];
  }, []);

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const ps = await reloadPeriods();
        if (!alive) return;
        // 默认选当前年最早的 OPEN 期间（逐月结账从前往后）。
        const firstOpen = ps.find((p) => p.status === 'OPEN');
        setPeriodId((prev) => prev ?? (firstOpen?.id ?? ps[0]?.id ?? null));
      } catch (e) {
        message.error('会计期间加载失败：' + (e.response?.data?.detail || e.message));
      } finally {
        if (alive) setLoading(false);
      }
    })();
    return () => { alive = false; };
  }, [message, reloadPeriods]);

  // 切期间 → 清各步状态。
  const resetSteps = useCallback(() => {
    setStep(0);
    setFxPreview(null); setFxReceipt(null);
    setPlPreview(null); setPlReceipt(null);
    setChecks(null); setCloseReceipt(null);
  }, []);
  useEffect(() => { resetSteps(); }, [periodId, resetSteps]);

  const handleErr = (e, fallback) => {
    message.error(fallback + '：' + (e.response?.data?.detail || e.message));
  };

  // command result 内嵌 success:false（校验未过 → 200 + details.checks），统一识别。
  const failed = (data) => data && data.success === false;

  // === 步骤 1：期末调汇 ===
  const runFxPreview = useCallback(async () => {
    if (!periodId) return;
    setBusy(true);
    try {
      const { data } = await api.post(EP.fxPreview, { period_id: periodId, preview: true });
      if (failed(data)) { message.error(data.error || '调汇预览失败'); return; }
      setFxPreview(data);
    } catch (e) { handleErr(e, '调汇预览失败'); }
    finally { setBusy(false); }
  }, [periodId]); // eslint-disable-line

  const runFx = useCallback(async () => {
    if (!periodId) return;
    setBusy(true);
    try {
      const { data } = await api.post(EP.fx, { period_id: periodId });
      if (failed(data)) { message.error(data.error || '调汇失败'); return; }
      setFxReceipt(data);
      if (data.created) message.success(data.message || '调汇凭证已生成（草稿）');
      else message.info(data.message || '本期无需调汇 / 已生成');
    } catch (e) { handleErr(e, '调汇失败'); }
    finally { setBusy(false); }
  }, [periodId]); // eslint-disable-line

  // === 步骤 2：结转损益 ===
  const runPlPreview = useCallback(async () => {
    if (!periodId) return;
    setBusy(true);
    try {
      const { data } = await api.post(EP.plPreview, { period_id: periodId, preview: true });
      if (failed(data)) { message.error(data.error || '结转预览失败'); return; }
      setPlPreview(data);
    } catch (e) { handleErr(e, '结转预览失败'); }
    finally { setBusy(false); }
  }, [periodId]); // eslint-disable-line

  const runPl = useCallback(async () => {
    if (!periodId) return;
    setBusy(true);
    try {
      const { data } = await api.post(EP.pl, { period_id: periodId });
      if (failed(data)) { message.error(data.error || '结转损益失败'); return; }
      setPlReceipt(data);
      if (data.created) message.success(data.message || '结转损益凭证已生成（草稿）');
      else message.info(data.message || '本期无损益余额 / 已生成');
    } catch (e) { handleErr(e, '结转损益失败'); }
    finally { setBusy(false); }
  }, [periodId]); // eslint-disable-line

  // === 步骤 3：结账前置校验 + 结账 ===
  const runPrecheck = useCallback(async () => {
    if (!periodId) return;
    setBusy(true);
    try {
      const { data } = await api.post(EP.precheck, { period_id: periodId });
      if (failed(data)) { message.error(data.error || '前置校验失败'); return; }
      setChecks(data);
    } catch (e) { handleErr(e, '前置校验失败'); }
    finally { setBusy(false); }
  }, [periodId]); // eslint-disable-line

  const runClose = useCallback(async () => {
    if (!periodId) return;
    setBusy(true);
    try {
      const { data } = await api.post(EP.close, { period_id: periodId });
      if (failed(data)) {
        // 前置校验未过：把 details.checks 回填到清单高亮未过项。
        const c = data.details?.checks;
        if (c) setChecks({ checks: c, can_close: false });
        message.error(data.error || '结账未通过前置校验');
        return;
      }
      setCloseReceipt(data);
      if (data.closed) {
        message.success(data.message || '期末结账完成（已锁期）');
        await reloadPeriods();
      } else {
        message.info(data.message || '该期已结账');
      }
    } catch (e) { handleErr(e, '结账失败'); }
    finally { setBusy(false); }
  }, [periodId, reloadPeriods]); // eslint-disable-line

  const onReopen = useCallback(() => {
    if (!periodId) return;
    modal.confirm({
      title: '反结账（撤销期末结账）',
      content: `将 ${period?.label} 由 CLOSED 反结回 OPEN（逐月：后续期已结账则须先反结后续期）。用于错账重做，留痕原结账人。`,
      okText: '确认反结账', okButtonProps: { danger: true },
      onOk: async () => {
        setBusy(true);
        try {
          const { data } = await api.post(EP.reopen, { period_id: periodId });
          if (failed(data)) { message.error(data.error || '反结账失败'); return; }
          message.success(data.message || '已反结账');
          await reloadPeriods();
          resetSteps();
        } catch (e) { handleErr(e, '反结账失败'); }
        finally { setBusy(false); }
      },
    });
  }, [periodId, period, modal, reloadPeriods, resetSteps]); // eslint-disable-line

  if (loading) return <Spin size="large" style={{ display: 'block', margin: '80px auto' }} />;

  return (
    <div>
      <div style={{ marginBottom: 16, display: 'flex', alignItems: 'baseline', gap: 12, flexWrap: 'wrap' }}>
        <h2 style={{ fontSize: 26, fontWeight: 300, letterSpacing: '-0.01em', color: '#000', margin: 0, lineHeight: 1.2 }}>
          期末结账
        </h2>
        <span style={{ color: '#777169', fontSize: 13 }}>
          财务 / 总账 · 录音顺序 <b>过账 → 调汇 → 结转损益 → 结账</b> · 命令 <code>finance.fx_revaluation / carry_forward_pl / close_period</code>
        </span>
      </div>

      {/* 头：账簿 + 期间 */}
      <Card size="small" style={{ borderRadius: 14, marginBottom: 12 }}>
        <Space size={28} wrap align="end">
          <Field label="账簿 / 核算组织">
            <Tag color="geekblue">{user?.company_name || `公司 #${user?.company_id ?? ''}`}</Tag>
          </Field>
          <Field label="会计期间">
            <Select
              size="small" value={periodId} style={{ width: 240 }} onChange={setPeriodId}
              options={periods.map((p) => ({
                value: p.id,
                label: `${p.label}（${p.status}）`,
              }))}
              placeholder="选择结账期间"
            />
          </Field>
          {period && (
            <Field label="期间状态">
              <PeriodStatusTag status={period.status} />
            </Field>
          )}
          {period && (
            <Field label="期间日期">
              <span style={{ fontFamily: MONO, fontSize: 13 }}>{period.start_date} ~ {period.end_date}</span>
            </Field>
          )}
          {isClosed && (
            <Button danger icon={<UnlockOutlined />} loading={busy} onClick={onReopen}>反结账</Button>
          )}
        </Space>
      </Card>

      {isClosed && (
        <Alert
          style={{ marginBottom: 12, borderRadius: 12 }}
          type="success" showIcon icon={<LockOutlined />}
          message={`${period.label} 已结账（CLOSED，锁期）`}
          description="该期间凭证不可再过账/反过账；如需更正请先「反结账」回 OPEN（逐月）。"
        />
      )}

      {/* 向导 */}
      <Card size="small" style={{ borderRadius: 14 }}>
        <Steps
          size="small" current={step} onChange={setStep}
          style={{ marginBottom: 20 }}
          items={[
            { title: '期末调汇', icon: <SwapOutlined /> },
            { title: '结转损益', icon: <FundOutlined /> },
            { title: '期末结账', icon: <LockOutlined /> },
          ]}
        />

        {step === 0 && (
          <StepFx
            disabled={!isOpen || busy} busy={busy}
            preview={fxPreview} receipt={fxReceipt}
            onPreview={runFxPreview} onRun={runFx} onNext={() => setStep(1)}
          />
        )}
        {step === 1 && (
          <StepPl
            disabled={!isOpen || busy} busy={busy}
            preview={plPreview} receipt={plReceipt}
            onPreview={runPlPreview} onRun={runPl}
            onPrev={() => setStep(0)} onNext={() => setStep(2)}
          />
        )}
        {step === 2 && (
          <StepClose
            disabled={!isOpen || busy} busy={busy} isClosed={isClosed}
            checks={checks} receipt={closeReceipt}
            onPrecheck={runPrecheck} onClose={runClose} onPrev={() => setStep(1)}
          />
        )}
      </Card>
    </div>
  );
}

/* ============ 步骤 1：期末调汇 ============ */
function StepFx({ disabled, busy, preview, receipt, onPreview, onRun, onNext }) {
  return (
    <div>
      <StepHint
        title="期末调汇（外币货币性科目重估本位币）"
        desc="外币货币性科目按期末汇率重估本位币，差额计入汇兑损益（CAS 6603 财务费用 / HK 6601 Finance costs），生成调汇凭证（草稿）。无外币科目或差额为 0 时无需调汇。"
      />
      <Space style={{ marginBottom: 12 }}>
        <Button icon={<ReloadOutlined />} disabled={busy} loading={busy} onClick={onPreview}>预览重估差额</Button>
        <Button type="primary" icon={<SwapOutlined />} disabled={disabled} loading={busy} onClick={onRun}>
          生成调汇凭证
        </Button>
      </Space>

      {preview && (
        <Card size="small" style={{ marginBottom: 12, borderRadius: 10 }} title="重估差额预览">
          <Table
            size="small" rowKey={(r, i) => r.account_code + i} pagination={false}
            dataSource={preview.rows || []}
            locale={{ emptyText: '无外币货币性科目需重估' }}
            columns={[
              { title: '科目', dataIndex: 'account_code', render: (v, r) => <span style={{ fontFamily: MONO }}>{v} {r.account_name}</span> },
              { title: '币别', dataIndex: 'currency' },
              { title: '期末汇率', dataIndex: 'new_rate', align: 'right' },
              { title: '账面本位币', dataIndex: 'book_base', align: 'right', render: (v) => <Mono>{fmtMoney(v)}</Mono> },
              { title: '重估本位币', dataIndex: 'revalued_base', align: 'right', render: (v) => <Mono>{fmtMoney(v)}</Mono> },
              { title: '差额', dataIndex: 'diff', align: 'right', render: (v) => <Mono color={v >= 0 ? '#1f8f3a' : '#b42318'}>{fmtMoney(v)}</Mono> },
            ]}
            summary={() => (
              <Table.Summary.Row>
                <Table.Summary.Cell index={0} colSpan={5} align="right"><b>差额合计</b></Table.Summary.Cell>
                <Table.Summary.Cell index={5} align="right"><Mono>{fmtMoney(preview.total_diff)}</Mono></Table.Summary.Cell>
              </Table.Summary.Row>
            )}
          />
        </Card>
      )}

      {receipt && <ReceiptCard receipt={receipt} kind="调汇" extra={
        receipt.total_diff != null && <Tag>差额合计 {fmtMoney(receipt.total_diff)}</Tag>
      } />}

      <StepNav onNext={onNext} />
    </div>
  );
}

/* ============ 步骤 2：结转损益 ============ */
function StepPl({ disabled, busy, preview, receipt, onPreview, onRun, onPrev, onNext }) {
  return (
    <div>
      <StepHint
        title="结转损益（收入/费用结转到本年利润）"
        desc="收入类（借方冲平）/ 费用成本类（贷方冲平）期末本位币余额结转到本年利润（CAS 4103 / HK 3201 Retained earnings），生成结转损益凭证（草稿）。"
      />
      <Space style={{ marginBottom: 12 }}>
        <Button icon={<ReloadOutlined />} disabled={busy} loading={busy} onClick={onPreview}>预览结转</Button>
        <Button type="primary" icon={<FundOutlined />} disabled={disabled} loading={busy} onClick={onRun}>
          生成结转损益凭证
        </Button>
      </Space>

      {preview && (
        <Card size="small" style={{ marginBottom: 12, borderRadius: 10 }}
          title={<span>结转预览 · 本期{Number(preview.net_profit) >= 0 ? '净利润' : '净亏损'} <Mono color={Number(preview.net_profit) >= 0 ? '#1f8f3a' : '#b42318'}>{fmtMoney(Math.abs(preview.net_profit))}</Mono></span>}>
          <Table
            size="small" rowKey={(r, i) => r.account_code + i} pagination={false}
            dataSource={preview.rows || []}
            locale={{ emptyText: '本期无损益类余额' }}
            columns={[
              { title: '科目', dataIndex: 'account_code', render: (v, r) => <span style={{ fontFamily: MONO }}>{v} {r.account_name}</span> },
              { title: '类型', dataIndex: 'type' },
              { title: '结转方向', dataIndex: 'side' },
              { title: '金额（本位币）', dataIndex: 'amount', align: 'right', render: (v) => <Mono>{fmtMoney(v)}</Mono> },
            ]}
          />
        </Card>
      )}

      {receipt && <ReceiptCard receipt={receipt} kind="结转损益" extra={
        receipt.net_profit != null && <Tag color={Number(receipt.net_profit) >= 0 ? 'green' : 'red'}>
          本期{Number(receipt.net_profit) >= 0 ? '净利润' : '净亏损'} {fmtMoney(Math.abs(receipt.net_profit))}
        </Tag>
      } />}

      <StepNav onPrev={onPrev} onNext={onNext} />
    </div>
  );
}

/* ============ 步骤 3：期末结账 ============ */
function StepClose({ disabled, busy, isClosed, checks, receipt, onPrecheck, onClose, onPrev }) {
  const canClose = checks?.can_close;
  return (
    <div>
      <StepHint
        title="期末结账（前置校验 → 锁期 CLOSED）"
        desc="前置校验：本期所有凭证已过账、试算平衡、期末调汇与结转损益已生成并过账、逐月上一期已结账。全部通过方可锁期。"
      />

      {isClosed && receipt == null && (
        <Alert style={{ marginBottom: 12 }} type="success" showIcon message="该期间已结账（CLOSED）" />
      )}

      <Space style={{ marginBottom: 12 }}>
        <Button icon={<ReloadOutlined />} disabled={busy} loading={busy} onClick={onPrecheck}>前置校验</Button>
        <Tooltip title={checks && !canClose ? '存在未通过项，先处理再结账' : ''}>
          <Button
            type="primary" danger icon={<LockOutlined />}
            disabled={disabled || (checks && !canClose)} loading={busy} onClick={onClose}
          >
            执行结账（锁期）
          </Button>
        </Tooltip>
      </Space>

      {checks?.checks && (
        <Card size="small" style={{ marginBottom: 12, borderRadius: 10 }}
          title={<span>前置校验清单 {canClose
            ? <Tag color="green">全部通过 ✓</Tag>
            : <Tag color="red">存在未通过项</Tag>}</span>}>
          <Table
            size="small" rowKey="key" pagination={false} dataSource={checks.checks}
            columns={[
              {
                title: '校验项', dataIndex: 'label',
                render: (v, r) => (
                  <Space>
                    {r.passed
                      ? <CheckCircleTwoTone twoToneColor="#1f8f3a" />
                      : <CloseCircleTwoTone twoToneColor="#b42318" />}
                    <span style={{ color: r.passed ? '#000' : '#b42318' }}>{v}</span>
                  </Space>
                ),
              },
              { title: '明细', dataIndex: 'detail', render: (v) => <span style={{ color: '#777169', fontSize: 12 }}>{v}</span> },
            ]}
          />
        </Card>
      )}

      {receipt?.closed && (
        <Result
          status="success" icon={<FileDoneOutlined style={{ color: '#1f8f3a' }} />}
          title={receipt.message}
          subTitle={`结账人 #${receipt.closed_by_id} · ${receipt.period_label}`}
        />
      )}

      <StepNav onPrev={onPrev} />
    </div>
  );
}

/* ---- 小积木 ---- */
function Field({ label, children }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
      <span style={{ fontSize: 11, color: '#777169' }}>{label}</span>
      {children}
    </div>
  );
}
function StepHint({ title, desc }) {
  return (
    <div style={{ marginBottom: 14 }}>
      <div style={{ fontSize: 15, fontWeight: 500, marginBottom: 4 }}>{title}</div>
      <div style={{ fontSize: 12, color: '#777169', lineHeight: 1.6 }}>{desc}</div>
    </div>
  );
}
function StepNav({ onPrev, onNext }) {
  return (
    <div style={{ marginTop: 16, display: 'flex', gap: 8 }}>
      {onPrev && <Button onClick={onPrev}>上一步</Button>}
      {onNext && <Button type="dashed" onClick={onNext}>下一步</Button>}
    </div>
  );
}
function Mono({ children, color }) {
  return <span style={{ fontFamily: MONO, color }}>{children}</span>;
}
function ReceiptCard({ receipt, kind, extra }) {
  return (
    <Card size="small" style={{ marginBottom: 12, borderRadius: 10, background: 'rgba(245,242,239,0.5)' }}
      title={<span>{kind}回执</span>} extra={extra}>
      <Descriptions size="small" column={2}>
        <Descriptions.Item label="是否生成凭证">
          {receipt.created ? <Tag color="green">已生成（草稿）</Tag> : <Tag>未生成</Tag>}
        </Descriptions.Item>
        {receipt.voucher_number && (
          <Descriptions.Item label="凭证号"><Mono>{receipt.voucher_number}</Mono></Descriptions.Item>
        )}
        {receipt.voucher_status && (
          <Descriptions.Item label="凭证状态"><Tag>{statusLabel(receipt.voucher_status)}</Tag></Descriptions.Item>
        )}
        <Descriptions.Item label="说明" span={2}>{receipt.message}</Descriptions.Item>
      </Descriptions>
      {receipt.created && (
        <Alert style={{ marginTop: 8 }} type="info" showIcon
          message="凭证为草稿——请到「凭证录入」页审核并过账后，再回本页执行结账（过账闸：本期须无未过账凭证）。" />
      )}
    </Card>
  );
}

function PeriodStatusTag({ status }) {
  const meta = {
    OPEN: { label: '未结账 OPEN', color: 'blue' },
    LOCKED: { label: '已锁定 LOCKED', color: 'orange' },
    CLOSED: { label: '已结账 CLOSED', color: 'green' },
  }[status] || { label: status, color: 'default' };
  return <Tag color={meta.color}>{meta.label}</Tag>;
}
