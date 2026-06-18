/**
 * ConsolidationGroupPage —— 合并范围 + 抵消分录管理（总账·finance-gl wave-7 合并报表）
 *
 * 会计专家定调：合并报表「可手工合」(非全自动权益法) → 半自动：各成员单体报表汇总 + 折算 + 手工抵消调整。
 * 本页是合并报表的「配置端」：定义合并范围（成员公司集 + 列报货币 + 准则）、录入手工抵消分录；
 *   出表端是合并资产负债表 / 合并利润表两张报表页（调 /api/reports/consolidated-*）。
 *
 * 两块（Tab 切换）：
 *  1) 合并范围 ConsolidationGroup：列/建/改。成员公司多选（跨公司，落 consolidation_member 子表，随 sub_updates 提交）、
 *     列报货币 presentation_currency、合并准则 standard。走引擎唯一写入 /api/transition（doc_type=CONSOLIDATION_GROUP，
 *     seed_consolidation 已种单态 ACTIVE 自环编辑机）。
 *  2) 抵消分录 EliminationEntry：选 范围 + 年度 + 期号 → 列/录手工抵消调整（报表行 line_key / 口径 BS|IS / 借 / 贷 / 摘要）。
 *     走引擎唯一写入 /api/transition（doc_type=ELIMINATION_ENTRY）。同组同期同行可多笔抵消（无业务唯一键，各自成行）。
 *
 * 取数：合并范围/抵消分录均 company_scoped（后端 _company_filter 隔离创建公司）；成员公司清单 query('company')（全局可查）。
 * 绝不在前端伪造写：写一律走 transition()，引擎拒绝时如实弹错。
 * ★禁碰 App.jsx / Layout.jsx / api.js —— 路由 / 导航 / api 方法签名走 routesToWire 由主 agent 统一接。
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  App, Button, Card, Form, Input, InputNumber, Modal, Segmented, Select, Space, Spin,
  Table, Tag, Descriptions, Empty, Switch,
} from 'antd';
import {
  PlusOutlined, EditOutlined, HistoryOutlined, ReloadOutlined, BankOutlined,
} from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import { query, transition } from '../../api';
import { BizEditableTable } from '../../components/biz';
import { MONO, fmtMoney, num } from './financeHelpers';

const CCY_OPTIONS = [
  { value: 'CNY', label: 'CNY 人民币' },
  { value: 'HKD', label: 'HKD 港元' },
  { value: 'USD', label: 'USD 美元' },
];
const STANDARD_OPTIONS = [
  { value: 'CAS', label: 'CAS（企业会计准则）' },
  { value: 'HKFRS', label: 'HKFRS（香港）' },
];
const STMT_OPTIONS = [
  { value: 'BS', label: 'BS 资产负债表' },
  { value: 'IS', label: 'IS 利润表' },
];

export default function ConsolidationGroupPage() {
  const { message } = App.useApp();

  const [tab, setTab] = useState('GROUP'); // GROUP 合并范围 / ELIM 抵消分录

  // 成员公司候选（全局可查）+ 合并范围列表（两块共用）
  const [companies, setCompanies] = useState([]);
  const [groups, setGroups] = useState([]);
  const [loading, setLoading] = useState(true);

  const reloadGroups = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await query('consolidation_group', { order_by: 'code', limit: 200 });
      setGroups(data?.data || []);
    } catch (e) {
      message.error('合并范围加载失败：' + (e.response?.data?.detail || e.message));
    } finally {
      setLoading(false);
    }
  }, [message]);

  useEffect(() => {
    reloadGroups();
    query('company', { order_by: 'id', limit: 200 })
      .then(({ data }) => setCompanies(data?.data || []))
      .catch(() => {});
  }, [reloadGroups]);

  const companyById = useMemo(() => {
    const m = new Map();
    companies.forEach((c) => m.set(c.id, c));
    return m;
  }, [companies]);
  const companyOptions = useMemo(
    () => companies.map((c) => ({
      value: c.id,
      label: `${c.code || ''} ${c.short_name || c.name || ''}`.trim() + (c.currency ? ` · ${c.currency}` : ''),
    })),
    [companies],
  );

  return (
    <div>
      <div style={{ marginBottom: 16, display: 'flex', alignItems: 'baseline', gap: 12, flexWrap: 'wrap' }}>
        <h2 style={{ fontSize: 26, fontWeight: 300, letterSpacing: '-0.01em', color: '#000', margin: 0, lineHeight: 1.2 }}>
          合并范围 / 抵消
        </h2>
        <span style={{ color: '#777169', fontSize: 13 }}>
          财务 / 总账 · 合并报表配置 · 半自动合并（各成员单体报表汇总 + 折算 + 手工抵消）· 出表见「合并资产负债表 / 合并利润表」
        </span>
      </div>

      <Card size="small" style={{ borderRadius: 14, marginBottom: 12 }}>
        <Segmented
          value={tab}
          onChange={setTab}
          options={[
            { value: 'GROUP', label: '合并范围（成员公司 / 列报货币 / 准则）' },
            { value: 'ELIM', label: '抵消分录（手工抵消调整）' },
          ]}
        />
      </Card>

      {tab === 'GROUP' ? (
        <GroupTab
          groups={groups}
          loading={loading}
          companyOptions={companyOptions}
          companyById={companyById}
          onReload={reloadGroups}
        />
      ) : (
        <EliminationTab
          groups={groups}
        />
      )}
    </div>
  );
}

/* ============================ 合并范围 ============================ */

function GroupTab({ groups, loading, companyOptions, companyById, onReload }) {
  const { message } = App.useApp();
  const navigate = useNavigate();

  const [editorOpen, setEditorOpen] = useState(false);
  const [editing, setEditing] = useState(null); // null=新建
  const [form] = Form.useForm();
  const [memberIds, setMemberIds] = useState([]);      // 选中的成员公司 id（多选）
  const [existingMembers, setExistingMembers] = useState([]); // 已有 consolidation_member 行（编辑时带 id，用于 sub_updates 增删）
  const [saving, setSaving] = useState(false);

  const openEditor = useCallback(async (g) => {
    setEditing(g || null);
    form.resetFields();
    if (g) {
      form.setFieldsValue({
        code: g.code, name: g.name,
        presentation_currency: g.presentation_currency || 'CNY',
        standard: g.standard || 'CAS',
        description: g.description || '',
        is_active: g.is_active !== false,
      });
      try {
        const { data } = await query('consolidation_member', {
          filters: { group_id: g.id }, order_by: 'id', limit: 100,
        });
        const rows = data?.data || [];
        setExistingMembers(rows);
        setMemberIds(rows.filter((r) => r.is_active !== false).map((r) => r.member_company_id));
      } catch {
        setExistingMembers([]);
        setMemberIds([]);
      }
    } else {
      form.setFieldsValue({ presentation_currency: 'CNY', standard: 'CAS', is_active: true, description: '' });
      setExistingMembers([]);
      setMemberIds([]);
    }
    setEditorOpen(true);
  }, [form]);

  const onSave = async () => {
    let values;
    try {
      values = await form.validateFields();
    } catch {
      return;
    }
    if (!memberIds.length) {
      message.warning('请至少选择一个成员公司');
      return;
    }
    setSaving(true);
    try {
      const field_updates = {};
      for (const [k, v] of Object.entries(values)) {
        if (v === undefined || v === '') continue;
        field_updates[k] = v;
      }
      // 成员公司多选 → consolidation_member 子表 sub_updates（参 MasterDataPage 子表范式：parent_fk=group_id）。
      //   新选中且无既有行 → 新增；既有行不在选中集 → 停用（_delete）；既有行仍选中 → 重激活（is_active=true）。
      const byCompany = new Map();
      existingMembers.forEach((r) => byCompany.set(r.member_company_id, r));
      const sub_updates = [];
      memberIds.forEach((cid) => {
        const ex = byCompany.get(cid);
        if (ex) {
          sub_updates.push({ table: 'consolidation_member', id: ex.id, fields: { member_company_id: cid, ownership_pct: ex.ownership_pct ?? 100, is_active: true } });
        } else {
          sub_updates.push({ table: 'consolidation_member', parent_fk: 'group_id', fields: { member_company_id: cid, ownership_pct: 100, is_active: true } });
        }
      });
      existingMembers.forEach((r) => {
        if (!memberIds.includes(r.member_company_id)) {
          sub_updates.push({ table: 'consolidation_member', id: r.id, _delete: true, fields: {} });
        }
      });
      const { data } = await transition({
        doc_type: 'CONSOLIDATION_GROUP',
        doc_id: editing?.id ?? null,
        field_updates,
        sub_updates,
        comment: editing?.id ? '合并范围更新' : '合并范围建档',
      });
      if (data?.success === false) {
        message.error(data.error || data.detail || '保存失败（引擎拒绝）');
        return;
      }
      message.success(editing?.id ? '合并范围已更新' : '合并范围已建档');
      setEditorOpen(false);
      onReload();
    } catch (e) {
      message.error('保存失败：' + (e.response?.data?.detail || e.message || '引擎写路径未就绪'));
    } finally {
      setSaving(false);
    }
  };

  const columns = useMemo(() => [
    { title: '范围码', dataIndex: 'code', width: 130, fixed: 'left',
      render: (v) => <span style={{ fontFamily: MONO }}>{v}</span> },
    { title: '合并范围名称', dataIndex: 'name', width: 200, ellipsis: true },
    { title: '列报货币', dataIndex: 'presentation_currency', width: 100,
      render: (v) => <Tag>{v || '—'}</Tag> },
    { title: '合并准则', dataIndex: 'standard', width: 130,
      render: (v) => <Tag color="purple">{v === 'HKFRS' ? 'HKFRS' : 'CAS'}</Tag> },
    { title: '说明', dataIndex: 'description', ellipsis: true,
      render: (v) => v || <span style={{ color: '#bfbbb5' }}>—</span> },
    { title: '状态', dataIndex: 'is_active', width: 72,
      render: (v) => v === false ? <Tag>停用</Tag> : <Tag color="green">启用</Tag> },
    {
      title: '操作', key: '_action', width: 160, fixed: 'right',
      render: (_, r) => (
        <Space size={2}>
          <Button type="link" size="small" icon={<EditOutlined />} onClick={() => openEditor(r)}>编辑</Button>
          <Button type="link" size="small" icon={<HistoryOutlined />}
            onClick={() => navigate(`/history/CONSOLIDATION_GROUP/${r.id}`)}>历史</Button>
        </Space>
      ),
    },
  ], [openEditor, navigate]);

  return (
    <>
      <Card size="small" style={{ borderRadius: 14, marginBottom: 12 }}>
        <div style={{ display: 'flex', gap: 16, alignItems: 'center', flexWrap: 'wrap' }}>
          <span style={{ color: '#777169', fontSize: 13 }}>
            <BankOutlined /> 一个合并范围 = 一组成员公司 + 列报货币 + 列报准则。成员经子表跨公司挂入；合并端按列报货币折算后按 line_key 汇总（同币 rate=1）。
          </span>
          <div style={{ flex: 1 }} />
          <Space>
            <Button icon={<ReloadOutlined />} onClick={onReload}>刷新</Button>
            <Button type="primary" icon={<PlusOutlined />} onClick={() => openEditor(null)}>新建合并范围</Button>
          </Space>
        </div>
      </Card>

      <Card size="small" style={{ borderRadius: 14 }} styles={{ body: { padding: 0 } }}>
        <Spin spinning={loading}>
          <Table
            rowKey="id"
            size="small"
            dataSource={groups}
            columns={columns}
            pagination={{ pageSize: 20, size: 'small' }}
            scroll={{ x: 'max-content' }}
            expandable={{
              expandedRowRender: (r) => <MemberPreview groupId={r.id} companyById={companyById} />,
              rowExpandable: () => true,
            }}
            locale={{ emptyText: '暂无合并范围，点「新建合并范围」创建' }}
          />
        </Spin>
      </Card>

      {/* 新建 / 编辑合并范围 */}
      <Modal
        open={editorOpen}
        onCancel={() => setEditorOpen(false)}
        title={editing?.id ? `编辑合并范围 · ${editing.code}` : '新建合并范围'}
        width={680}
        okText="保存"
        confirmLoading={saving}
        onOk={onSave}
        maskClosable={false}
        destroyOnHidden
      >
        <Form form={form} layout="vertical" style={{ marginTop: 8 }}>
          <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
            <Form.Item name="code" label="范围码" rules={[{ required: true, message: '请填范围码' }]} style={{ width: 200 }}>
              <Input placeholder="如 CG-ALL / CG-HK" disabled={!!editing?.id} />
            </Form.Item>
            <Form.Item name="name" label="合并范围名称" rules={[{ required: true, message: '请填名称' }]} style={{ width: 280 }}>
              <Input placeholder="如 全集团合并 / 香港组合并" />
            </Form.Item>
          </div>
          <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
            <Form.Item name="presentation_currency" label="列报货币" rules={[{ required: true }]} style={{ width: 200 }}
              tooltip="合并后统一币种；各成员本位币按汇率折算到此货币（同币 rate=1）">
              <Select options={CCY_OPTIONS} />
            </Form.Item>
            <Form.Item name="standard" label="合并列报准则" rules={[{ required: true }]} style={{ width: 240 }}
              tooltip="仅作列报口径标注；各成员单体报表仍按其公司 region 出准则-aware 行树，合并端按行键并集对齐">
              <Select options={STANDARD_OPTIONS} />
            </Form.Item>
            <Form.Item name="is_active" label="启用" valuePropName="checked" style={{ width: 90 }}>
              <Switch />
            </Form.Item>
          </div>
          <Form.Item name="description" label="说明">
            <Input placeholder="合并范围说明（可选）" />
          </Form.Item>
          <Form.Item
            label="成员公司（多选，跨公司）"
            required
            tooltip="纳入本合并范围的成员公司；半自动合并下按 100% 简单汇总（持股比例仅作手工抵消参考）"
          >
            <Select
              mode="multiple"
              value={memberIds}
              onChange={setMemberIds}
              options={companyOptions}
              placeholder="选择纳入合并的成员公司"
              optionFilterProp="label"
              showSearch
              style={{ width: '100%' }}
            />
          </Form.Item>
        </Form>
      </Modal>
    </>
  );
}

// 展开行：合并范围已挂成员公司预览（轻量只读）。
function MemberPreview({ groupId, companyById }) {
  const [rows, setRows] = useState(null);
  useEffect(() => {
    let alive = true;
    query('consolidation_member', { filters: { group_id: groupId }, order_by: 'id', limit: 100 })
      .then(({ data }) => { if (alive) setRows(data?.data || []); })
      .catch(() => { if (alive) setRows([]); });
    return () => { alive = false; };
  }, [groupId]);
  if (rows == null) return <Spin size="small" />;
  const active = rows.filter((r) => r.is_active !== false);
  if (!active.length) return <span style={{ color: '#bfbbb5' }}>未挂成员公司</span>;
  return (
    <Space size={[8, 8]} wrap>
      <span style={{ color: '#777169', fontSize: 12 }}>成员公司：</span>
      {active.map((r) => {
        const c = companyById.get(r.member_company_id);
        return (
          <Tag key={r.id} color="geekblue">
            {c ? (c.short_name || c.name || c.code) : `公司 #${r.member_company_id}`}
            {c?.currency ? ` · ${c.currency}` : ''}
            {Number(r.ownership_pct) !== 100 ? ` · ${num(r.ownership_pct)}%` : ''}
          </Tag>
        );
      })}
    </Space>
  );
}

/* ============================ 抵消分录 ============================ */

function EliminationTab({ groups }) {
  const { message } = App.useApp();
  const navigate = useNavigate();

  const now = new Date();
  const [groupId, setGroupId] = useState(null);
  const [periodYear, setPeriodYear] = useState(now.getFullYear());
  const [periodNumber, setPeriodNumber] = useState(now.getMonth() + 1);

  const [entries, setEntries] = useState([]);
  const [loading, setLoading] = useState(false);

  const [editorOpen, setEditorOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [form] = Form.useForm();
  const [saving, setSaving] = useState(false);

  const selectedGroup = useMemo(() => groups.find((g) => g.id === groupId), [groups, groupId]);

  // 默认选第一个合并范围
  useEffect(() => {
    if (groupId == null && groups.length) setGroupId(groups[0].id);
  }, [groups, groupId]);

  const reloadEntries = useCallback(async () => {
    if (!groupId) { setEntries([]); return; }
    setLoading(true);
    try {
      const { data } = await query('elimination_entry', {
        filters: { group_id: groupId, period_year: periodYear, period_number: periodNumber },
        order_by: 'id', limit: 500,
      });
      setEntries(data?.data || []);
    } catch (e) {
      message.error('抵消分录加载失败：' + (e.response?.data?.detail || e.message));
    } finally {
      setLoading(false);
    }
  }, [groupId, periodYear, periodNumber, message]);

  useEffect(() => { reloadEntries(); }, [reloadEntries]);

  const openEditor = useCallback((e) => {
    setEditing(e || null);
    form.resetFields();
    if (e) {
      form.setFieldsValue({
        statement: e.statement || 'BS',
        line_key: e.line_key || '',
        account_code: e.account_code || '',
        debit: e.debit != null ? Number(e.debit) : 0,
        credit: e.credit != null ? Number(e.credit) : 0,
        memo: e.memo || '',
        is_active: e.is_active !== false,
      });
    } else {
      form.setFieldsValue({ statement: 'BS', debit: 0, credit: 0, is_active: true });
    }
    setEditorOpen(true);
  }, [form]);

  const onSave = async () => {
    if (!groupId) { message.warning('请先选择合并范围'); return; }
    let values;
    try {
      values = await form.validateFields();
    } catch {
      return;
    }
    if (!values.line_key && !values.account_code) {
      message.warning('行键 line_key 与科目码 account_code 至少填一项（合并端按其一归集抵消列）');
      return;
    }
    setSaving(true);
    try {
      const field_updates = {
        group_id: groupId,
        period_year: periodYear,
        period_number: periodNumber,
        statement: values.statement || 'BS',
        line_key: values.line_key || '',
        account_code: values.account_code || '',
        debit: num(values.debit),
        credit: num(values.credit),
        memo: values.memo || '',
        is_active: values.is_active !== false,
      };
      const { data } = await transition({
        doc_type: 'ELIMINATION_ENTRY',
        doc_id: editing?.id ?? null,
        field_updates,
        comment: editing?.id ? '抵消分录更新' : '抵消分录录入',
      });
      if (data?.success === false) {
        message.error(data.error || data.detail || '保存失败（引擎拒绝）');
        return;
      }
      message.success(editing?.id ? '抵消分录已更新' : '抵消分录已录入');
      setEditorOpen(false);
      reloadEntries();
    } catch (e) {
      message.error('保存失败：' + (e.response?.data?.detail || e.message || '引擎写路径未就绪'));
    } finally {
      setSaving(false);
    }
  };

  const totals = useMemo(() => {
    let dr = 0, cr = 0;
    entries.forEach((e) => { if (e.is_active !== false) { dr += num(e.debit); cr += num(e.credit); } });
    return { dr: Math.round(dr * 100) / 100, cr: Math.round(cr * 100) / 100 };
  }, [entries]);

  const columns = useMemo(() => [
    { title: '口径', dataIndex: 'statement', width: 80,
      render: (v) => <Tag color={v === 'IS' ? 'orange' : 'blue'}>{v === 'IS' ? 'IS 利润表' : 'BS 资负表'}</Tag> },
    { title: '报表行键 line_key', dataIndex: 'line_key', width: 200, ellipsis: true,
      render: (v) => v ? <span style={{ fontFamily: MONO }}>{v}</span> : <span style={{ color: '#bfbbb5' }}>—</span> },
    { title: '科目码', dataIndex: 'account_code', width: 120,
      render: (v) => v ? <span style={{ fontFamily: MONO }}>{v}</span> : <span style={{ color: '#bfbbb5' }}>—</span> },
    { title: '借方', dataIndex: 'debit', width: 130, align: 'right',
      render: (v) => num(v) ? <span style={{ fontFamily: MONO }}>{fmtMoney(v)}</span> : <span style={{ color: '#d9d4cd' }}>—</span> },
    { title: '贷方', dataIndex: 'credit', width: 130, align: 'right',
      render: (v) => num(v) ? <span style={{ fontFamily: MONO }}>{fmtMoney(v)}</span> : <span style={{ color: '#d9d4cd' }}>—</span> },
    { title: '净额（借-贷）', key: '_net', width: 130, align: 'right',
      render: (_, r) => {
        const n = num(r.debit) - num(r.credit);
        return <span style={{ fontFamily: MONO, color: n < 0 ? '#b42318' : '#3a3733' }}>{fmtMoney(n)}</span>;
      } },
    { title: '抵消事由', dataIndex: 'memo', ellipsis: true,
      render: (v) => v || <span style={{ color: '#bfbbb5' }}>—</span> },
    { title: '状态', dataIndex: 'is_active', width: 72,
      render: (v) => v === false ? <Tag>停用</Tag> : <Tag color="green">生效</Tag> },
    {
      title: '操作', key: '_action', width: 150, fixed: 'right',
      render: (_, r) => (
        <Space size={2}>
          <Button type="link" size="small" icon={<EditOutlined />} onClick={() => openEditor(r)}>编辑</Button>
          <Button type="link" size="small" icon={<HistoryOutlined />}
            onClick={() => navigate(`/history/ELIMINATION_ENTRY/${r.id}`)}>历史</Button>
        </Space>
      ),
    },
  ], [openEditor, navigate]);

  return (
    <>
      <Card size="small" style={{ borderRadius: 14, marginBottom: 12 }}>
        <div style={{ display: 'flex', gap: 20, alignItems: 'flex-end', flexWrap: 'wrap' }}>
          <Field label="合并范围">
            <Select
              size="small"
              value={groupId}
              onChange={setGroupId}
              style={{ width: 240 }}
              placeholder="选择合并范围"
              options={groups.map((g) => ({ value: g.id, label: `${g.code} ${g.name}（${g.presentation_currency}）` }))}
            />
          </Field>
          <Field label="合并期间年份">
            <InputNumber size="small" min={2000} max={2100} precision={0} value={periodYear}
              onChange={(v) => setPeriodYear(v || periodYear)} style={{ width: 120 }} />
          </Field>
          <Field label="期号">
            <InputNumber size="small" min={1} max={12} precision={0} value={periodNumber}
              onChange={(v) => setPeriodNumber(v || periodNumber)} style={{ width: 90 }} />
          </Field>
          {selectedGroup && (
            <Field label="列报货币 / 准则">
              <Space size={6}>
                <Tag>{selectedGroup.presentation_currency}</Tag>
                <Tag color="purple">{selectedGroup.standard}</Tag>
              </Space>
            </Field>
          )}
          <div style={{ flex: 1 }} />
          <Space>
            <Button size="small" icon={<ReloadOutlined />} onClick={reloadEntries}>刷新</Button>
            <Button size="small" type="primary" icon={<PlusOutlined />} disabled={!groupId} onClick={() => openEditor(null)}>
              录入抵消分录
            </Button>
          </Space>
        </div>
        <div style={{ marginTop: 8, fontSize: 12, color: '#a8a39c' }}>
          金额均为列报货币（{selectedGroup?.presentation_currency || '—'}）；同组同期同行可多笔抵消，各自成行。
          合并端按（范围 + 年 + 期 + 口径 + 行键/科目码）聚合净额 = Σ借 − Σ贷 落入合并报表「抵消列」。
        </div>
      </Card>

      <Card size="small" style={{ borderRadius: 14 }} styles={{ body: { padding: 0 } }}>
        <Spin spinning={loading}>
          {!groupId ? (
            <Empty style={{ padding: 40 }} description="选择合并范围后查看 / 录入抵消分录" />
          ) : (
            <Table
              rowKey="id"
              size="small"
              dataSource={entries}
              columns={columns}
              pagination={{ pageSize: 20, size: 'small' }}
              scroll={{ x: 'max-content' }}
              locale={{ emptyText: '本期暂无抵消分录，点「录入抵消分录」添加' }}
              summary={() => entries.length ? (
                <Table.Summary fixed>
                  <Table.Summary.Row style={{ background: 'rgba(245,242,239,0.6)' }}>
                    <Table.Summary.Cell index={0} colSpan={3}>
                      <span style={{ fontWeight: 600 }}>本期抵消合计</span>
                    </Table.Summary.Cell>
                    <Table.Summary.Cell index={3} align="right">
                      <span style={{ fontFamily: MONO, fontWeight: 600 }}>{fmtMoney(totals.dr)}</span>
                    </Table.Summary.Cell>
                    <Table.Summary.Cell index={4} align="right">
                      <span style={{ fontFamily: MONO, fontWeight: 600 }}>{fmtMoney(totals.cr)}</span>
                    </Table.Summary.Cell>
                    <Table.Summary.Cell index={5} align="right">
                      <span style={{ fontFamily: MONO, fontWeight: 600 }}>{fmtMoney(totals.dr - totals.cr)}</span>
                    </Table.Summary.Cell>
                    <Table.Summary.Cell index={6} colSpan={3} />
                  </Table.Summary.Row>
                </Table.Summary>
              ) : null}
            />
          )}
        </Spin>
      </Card>

      {/* 录入 / 编辑抵消分录 */}
      <Modal
        open={editorOpen}
        onCancel={() => setEditorOpen(false)}
        title={editing?.id ? '编辑抵消分录' : '录入抵消分录'}
        width={560}
        okText="保存"
        confirmLoading={saving}
        onOk={onSave}
        maskClosable={false}
        destroyOnHidden
      >
        <Descriptions size="small" column={1} style={{ marginBottom: 12 }}>
          <Descriptions.Item label="合并范围">
            {selectedGroup ? `${selectedGroup.code} ${selectedGroup.name}` : '—'}
            {selectedGroup && <Tag style={{ marginLeft: 6 }}>{selectedGroup.presentation_currency}</Tag>}
          </Descriptions.Item>
          <Descriptions.Item label="合并期间">{periodYear} 年 第 {periodNumber} 期</Descriptions.Item>
        </Descriptions>
        <Form form={form} layout="vertical">
          <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
            <Form.Item name="statement" label="报表口径" rules={[{ required: true }]} style={{ width: 180 }}>
              <Select options={STMT_OPTIONS} />
            </Form.Item>
            <Form.Item name="is_active" label="生效" valuePropName="checked" style={{ width: 90 }}>
              <Switch />
            </Form.Item>
          </div>
          <Form.Item name="line_key" label="报表行键 line_key"
            tooltip="对齐合并资产负债表 / 合并利润表的 line_key（与单体报表行键一致）；与科目码至少填一项">
            <Input placeholder="如 ar / intercompany_revenue（与报表行键一致）" />
          </Form.Item>
          <Form.Item name="account_code" label="科目码（line_key 为空时按码归集，可选）">
            <Input placeholder="如 1122（弱引用，仅在 line_key 空时生效）" />
          </Form.Item>
          <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
            <Form.Item name="debit" label={`抵消借方（${selectedGroup?.presentation_currency || '列报币'}）`} style={{ width: 220 }}>
              <InputNumber min={0} precision={2} style={{ width: '100%' }} placeholder="0.00" />
            </Form.Item>
            <Form.Item name="credit" label={`抵消贷方（${selectedGroup?.presentation_currency || '列报币'}）`} style={{ width: 220 }}>
              <InputNumber min={0} precision={2} style={{ width: '100%' }} placeholder="0.00" />
            </Form.Item>
          </div>
          <Form.Item name="memo" label="抵消事由">
            <Input placeholder="如 内部往来抵消 / 内部销售抵消" />
          </Form.Item>
        </Form>
      </Modal>
    </>
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
