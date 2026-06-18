/**
 * OpeningBalancePage —— 期初建账（科目期初余额录入 + 试算平衡，总账·配账主数据 wave-3，前端A·科目+期初 PM）
 *
 * 期初建账 = 启用账簿前，把各科目的「期初余额（本位币，借/贷一边）」录入首期 account_balance.opening_*。
 *
 * 数据来源（只读 /api/query，不绕底座）：
 *   - 期间列表：/api/reports/periods（已实现，按当前账簿公司隔离）→ 选启用首期。
 *   - 叶子科目：query('account', is_active+is_leaf) —— 仅叶子科目可挂期初余额（非叶=汇总，由下级累加）。
 *   - 现有期初：query('account_balance', period_id) → 回填已录的 opening_debit/opening_credit。
 *
 * 试算平衡（前端实时校验，口径同 reports.trial_balance 的 opening 断言）：
 *   - Σ期初借方 必须 = Σ期初贷方（容差 0.005），否则**不允许保存**（保存按钮禁用 + 差额红字提示）。
 *
 * 保存机制（守"唯一写入路径"，绝不伪造写）：
 *   - account_balance 表当前仅 __queryable__、**无 __doc_types__**，故无 /api/transition 写路径，
 *     也无专门的「期初建账」引擎命令。本页完成录入 + 试算平衡 UI，「保存期初」按钮先做**校验闸 + TODO**：
 *     平衡通过后弹出说明「待后端 ➕ 期初建账命令（OPENING_BALANCE / account_balance 写路径）」，
 *     不调任何非 transition 写端点、不在前端伪造成功。后端开通后，本页改为把平衡通过的网格提交至该路径。
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { Alert, App, Button, InputNumber, Select, Space, Statistic, Table, Tag, Modal } from 'antd';
import { ReloadOutlined, SaveOutlined } from '@ant-design/icons';
import { query, getAccountingPeriods } from '../../../api';
import { MONO, ACCOUNT_TYPE_LABEL, fmtMoney, num, summarizeEntries } from '../financeHelpers';

export default function OpeningBalancePage() {
  const { message } = App.useApp();
  const [periods, setPeriods] = useState([]);
  const [periodId, setPeriodId] = useState(null);
  const [accounts, setAccounts] = useState([]);
  const [rows, setRows] = useState([]);        // [{account_id, code, name, account_type, opening_debit, opening_credit}]
  const [loading, setLoading] = useState(false);

  // 期间列表（启用首期通常 = 最早 OPEN 期）。
  useEffect(() => {
    getAccountingPeriods()
      .then((res) => {
        const list = res.data?.periods || res.data?.data || (Array.isArray(res.data) ? res.data : []);
        setPeriods(list);
        if (list.length && periodId == null) setPeriodId(list[0]?.id ?? null);
      })
      .catch((e) => message.error(e.response?.data?.detail || '加载会计期间失败（/api/reports/periods）'));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // 叶子科目 + 该期已录期初 → 合并成录入网格。
  const load = useCallback(async () => {
    if (periodId == null) return;
    setLoading(true);
    try {
      const [acctRes, balRes] = await Promise.all([
        query('account', { filters: { is_active: true, is_leaf: true }, order_by: 'code', limit: 2000 }),
        query('account_balance', { filters: { period_id: periodId }, limit: 5000 }),
      ]);
      const accts = acctRes.data?.data || [];
      setAccounts(accts);
      const balByAcct = new Map();
      (balRes.data?.data || []).forEach((b) => balByAcct.set(b.account_id, b));
      setRows(accts.map((a) => {
        const b = balByAcct.get(a.id);
        return {
          account_id: a.id, code: a.code, name: a.name,
          account_type: a.account_type, balance_direction: a.balance_direction,
          opening_debit: b ? num(b.opening_debit) : 0,
          opening_credit: b ? num(b.opening_credit) : 0,
        };
      }));
    } catch (e) {
      message.error(e.response?.data?.detail || '加载科目 / 期初余额失败');
    } finally {
      setLoading(false);
    }
  }, [periodId, message]);

  useEffect(() => { load(); }, [load]);

  const setCell = (accountId, key, val) => {
    setRows((prev) => prev.map((r) => r.account_id === accountId ? { ...r, [key]: num(val) } : r));
  };

  // 试算平衡（复用 financeHelpers.summarizeEntries：把期初借/贷映射成 debit/credit + base_*）。
  const balanceRows = useMemo(
    () => rows.map((r) => ({
      debit: r.opening_debit, credit: r.opening_credit,
      base_debit: r.opening_debit, base_credit: r.opening_credit,
    })),
    [rows]
  );
  const summary = useMemo(() => summarizeEntries(balanceRows), [balanceRows]);
  const nonZeroCount = useMemo(
    () => rows.filter((r) => num(r.opening_debit) !== 0 || num(r.opening_credit) !== 0).length,
    [rows]
  );

  const onSave = () => {
    if (!summary.balanced) {
      message.error('试算不平衡：期初借方合计 ≠ 贷方合计，不能保存');
      return;
    }
    Modal.info({
      title: '期初余额已录入并试算平衡',
      width: 520,
      content: (
        <div style={{ lineHeight: 1.7 }}>
          <p>
            借方合计 <b style={{ fontFamily: MONO }}>{fmtMoney(summary.totalDebitBase)}</b>
            ＝ 贷方合计 <b style={{ fontFamily: MONO }}>{fmtMoney(summary.totalCreditBase)}</b>，
            试算平衡通过（{nonZeroCount} 个科目有期初值）。
          </p>
          <Alert
            type="warning" showIcon style={{ borderRadius: 8 }}
            message="期初写路径待后端开通"
            description={
              <span>
                account_balance 表当前为引擎可查实体（__queryable__）但**无 doc_type / 无 /api/transition 写路径**，
                也尚无专门的「期初建账」引擎命令。本页已完成录入 + 试算平衡校验；待后端 ➕ 期初建账命令
                （写首期 account_balance.opening_debit/opening_credit）后，本「保存」即提交至该唯一写入路径。
                现阶段不调非 transition 写端点、不伪造保存成功。
              </span>
            }
          />
        </div>
      ),
    });
  };

  const columns = [
    {
      title: '科目编码', dataIndex: 'code', width: 120,
      render: (v) => <span style={{ fontFamily: MONO, color: '#1f4e79' }}>{v}</span>,
    },
    { title: '科目名称', dataIndex: 'name', ellipsis: true },
    {
      title: '类别', dataIndex: 'account_type', width: 90,
      render: (v) => ACCOUNT_TYPE_LABEL[v] || v,
    },
    {
      title: '余额方向', dataIndex: 'balance_direction', width: 90,
      render: (v) => <Tag color={v === 'DEBIT' ? 'blue' : 'gold'}>{v === 'DEBIT' ? '借' : '贷'}</Tag>,
    },
    {
      title: '期初借方（本位币）', dataIndex: 'opening_debit', width: 180, align: 'right',
      render: (v, r) => (
        <InputNumber
          size="small" style={{ width: '100%' }} min={0} controls={false}
          precision={2} value={r.opening_debit || undefined} placeholder="0.00"
          formatter={(x) => (x == null || x === '' ? '' : Number(x).toLocaleString('en-US'))}
          parser={(x) => (x || '').replace(/,/g, '')}
          onChange={(val) => setCell(r.account_id, 'opening_debit', val)}
        />
      ),
    },
    {
      title: '期初贷方（本位币）', dataIndex: 'opening_credit', width: 180, align: 'right',
      render: (v, r) => (
        <InputNumber
          size="small" style={{ width: '100%' }} min={0} controls={false}
          precision={2} value={r.opening_credit || undefined} placeholder="0.00"
          formatter={(x) => (x == null || x === '' ? '' : Number(x).toLocaleString('en-US'))}
          parser={(x) => (x || '').replace(/,/g, '')}
          onChange={(val) => setCell(r.account_id, 'opening_credit', val)}
        />
      ),
    },
  ];

  const periodOptions = (Array.isArray(periods) ? periods : []).map((p) => ({
    label: `${p.year ?? p.fiscal_year ?? p.start_date?.slice(0, 4) ?? ''} 第${p.period_number}期（${p.start_date} ~ ${p.end_date}）${p.status === 'CLOSED' ? ' · 已结账' : ''}`,
    value: p.id,
  }));

  return (
    <div>
      <div style={{ marginBottom: 16, display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end' }}>
        <div>
          <h2 style={{ fontSize: 26, fontWeight: 300, letterSpacing: '-0.01em', color: '#000', margin: 0, lineHeight: 1.2 }}>
            期初建账
          </h2>
          <span style={{ color: '#777169', fontSize: 13 }}>财务 / 总账 · 配账主数据 · 各科目期初余额录入（本位币）+ 试算平衡（借合计＝贷合计）</span>
        </div>
        <Space>
          <Select
            style={{ width: 360 }} placeholder="选择启用会计期间（首期）"
            value={periodId ?? undefined} options={periodOptions} onChange={setPeriodId}
            showSearch optionFilterProp="label"
          />
          <Button icon={<ReloadOutlined />} onClick={load}>刷新</Button>
        </Space>
      </div>

      <Alert
        type="info" showIcon style={{ marginBottom: 16, borderRadius: 12 }}
        message="期初余额仅叶子科目录入；非叶（汇总）科目由下级累加"
        description="试算平衡通过（Σ期初借 ＝ Σ期初贷）才允许保存。account_balance 当前无引擎写路径，「保存期初」先做平衡闸校验，待后端 ➕ 期初建账命令后提交至唯一写入路径（不伪造保存）。"
      />

      {periodId == null ? (
        <Alert type="warning" showIcon message="请先选择启用会计期间" description="期间来自 /api/reports/periods（按当前账簿公司隔离）。若为空，需先在「期末结账 / 期间」侧建立会计年度与首期。" />
      ) : (
        <>
          <Table
            rowKey="account_id"
            loading={loading}
            columns={columns}
            dataSource={rows}
            size="small"
            pagination={false}
            scroll={{ y: 'calc(100vh - 430px)' }}
          />

          {/* 底部试算平衡条 */}
          <div style={{
            marginTop: 12, padding: '12px 20px', borderRadius: 12,
            background: summary.balanced ? '#ebf5ee' : '#fdecea',
            border: `1px solid ${summary.balanced ? '#b7e0c2' : '#f5c2bd'}`,
            display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 24, flexWrap: 'wrap',
          }}>
            <Space size={40}>
              <Statistic title="期初借方合计" value={summary.totalDebitBase} precision={2}
                valueStyle={{ fontFamily: MONO, fontSize: 20 }} />
              <Statistic title="期初贷方合计" value={summary.totalCreditBase} precision={2}
                valueStyle={{ fontFamily: MONO, fontSize: 20 }} />
              <Statistic
                title="差额（借−贷）" value={summary.diff} precision={2}
                valueStyle={{ fontFamily: MONO, fontSize: 20, color: summary.balanced ? '#1f8f3a' : '#b42318' }}
              />
              <div style={{ alignSelf: 'center' }}>
                {summary.balanced
                  ? <Tag color="green" style={{ fontSize: 13, padding: '4px 12px' }}>试算平衡 ✓</Tag>
                  : <Tag color="red" style={{ fontSize: 13, padding: '4px 12px' }}>不平衡 · 不能保存</Tag>}
              </div>
            </Space>
            <Button
              type="primary" size="large" icon={<SaveOutlined />}
              disabled={!summary.balanced}
              onClick={onSave}
            >
              保存期初
            </Button>
          </div>
        </>
      )}
    </div>
  );
}
