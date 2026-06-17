/**
 * QualificationPage —— 客户认证（薄版）与并行会签（PRD 05-客户销售-客户认证与会签 ⭐）
 *
 * 大客户准入审核：富泰提交资料、双方签采购 / 质量协议（协议常埋违约金 / 索赔 / 质保期冲突 等
 *   对我方不利条款须审出来）。薄：系统只管认证状态 + 资料清单勾选 + 协议风险审查项打勾留痕 + 附件，
 *   不写协议正文。审核 = ★并行会签 PA + 财务 + BOSS 三方各签一票，全「同意」才通过、任一「驳回」打回。
 *
 * 状态机（薄）：DRAFT 备资料 → 提交 → UNDER_COSIGN（★PA + 财务 + BOSS 并行会签）→ APPROVED / REJECTED
 *   → 到期 EXPIRED。会签进审批中心。
 *
 * ★并行会签标准件复用（services/cosign.py，段0b·2，不动引擎核心）：
 *   - 子表 cosign_line（polymorphic：doc_type + doc_id + cosign_group 定位，非 parent_fk 子表），
 *     进会签态预生成 PA / FINANCE / BOSS 三行待签（required_role / signed_by / decision / comment）。
 *   - 「我签字」= UNDER_COSIGN 自循环编辑：签票方往自己那行填 AGREE / REJECT + 意见，走
 *     /api/transition 编辑模式 sub_updates 改 cosign_line（当前用户只能编自己那行 → UI 限定）。
 *   - 「通过」= 推进挂校验器（cosign_failures 集齐 AGREE 才放行，任一 REJECT 打回）。
 *
 * ★引擎实况（已勘 /api/transitions + /api/schema/cosign_line 2026-06-17）：
 *   - cosign_line 表已存在（字段 doc_type / doc_id / cosign_group / required_role / decision[AGREE/REJECT/PENDING]
 *     / signed_by_id / comment / signed_at），sign 走 /api/transition 编辑模式（workflow _apply_sub_updates
 *     按 id 更新行）。客户认证会签角色 = PA + FINANCE + BOSS，cosign_group = CERTIFICATION（cosign.py 实例）。
 *   - CUSTOMER_QUALIFICATION doc_type 尚未注册 → /api/schema/customer_qualification 失败时本页显示
 *     「功能已就绪 · 待后端开通」占位（14 律 §8），后端段3c 注册后自动点亮。状态码 / 子表名 / 外键
 *     一律从 /api/schema + /api/transitions 读真值，不写死推进。
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { Alert, App, Button, Descriptions, Empty, Input, Space, Tag } from 'antd';
import { PlusOutlined } from '@ant-design/icons';
import { useAuth } from '../../auth';
import { BizTable, BizDrawerForm, BizEditableTable } from '../../components/biz';
import { query, getSchema, transition, getTransitions } from '../../api';
import MasterFormFields from '../master/MasterFormFields';
import { schemaToColumns, renderCellByField } from '../wms/wmsHelpers';
import { StatusPill } from '../wms/wmsShared';

const DOC_TYPE = 'CUSTOMER_QUALIFICATION';
const TABLE = 'customer_qualification';
const NUMBER_FIELD = 'qualification_number';
const COSIGN_GROUP = 'CERTIFICATION';
const COSIGN_ROLE_LABEL = { PRODUCT_ASSISTANT: '采购助理 PA', FINANCE: '财务 FINANCE', BOSS: '管理层 BOSS' };

// 资料清单子表 qualification_doc_line（对齐真实 seed：doc_item / is_required / is_ready / attachment_ref）
const DOC_LINE = { table: 'qualification_doc_line', fk: 'qualification_id' };
const BOOL_OPTS = [{ label: '是', value: true }, { label: '否', value: false }];
const DOC_LINE_COLUMNS = [
  { title: '资料项', dataIndex: 'doc_item', width: 220,
    formItemProps: { rules: [{ required: true, message: '必填' }] } },
  { title: '是否必备', dataIndex: 'is_required', width: 100, valueType: 'select',
    fieldProps: { options: BOOL_OPTS } },
  { title: '是否齐备', dataIndex: 'is_ready', width: 100, valueType: 'select',
    fieldProps: { options: BOOL_OPTS } },
  { title: '附件引用', dataIndex: 'attachment_ref', width: 220 },
];

// 协议风险审查项子表 qualification_risk_line（风险类型 / 有无 / 说明）
const RISK_LINE = { table: 'qualification_risk_line', fk: 'qualification_id' };
const RISK_TYPE_OPTS = [
  { label: '违约金', value: 'PENALTY' }, { label: '索赔', value: 'CLAIM' },
  { label: '质保期冲突', value: 'WARRANTY_CONFLICT' }, { label: '其他', value: 'OTHER' },
];
const RISK_PRESENCE_OPTS = [
  { label: '有', value: 'YES' }, { label: '无', value: 'NO' }, { label: '待定', value: 'PENDING' },
];
const RISK_LINE_COLUMNS = [
  { title: '风险类型', dataIndex: 'risk_type', width: 160, valueType: 'select',
    fieldProps: { options: RISK_TYPE_OPTS },
    formItemProps: { rules: [{ required: true, message: '必填' }] } },
  { title: '有 / 无', dataIndex: 'presence', width: 120, valueType: 'select',
    fieldProps: { options: RISK_PRESENCE_OPTS } },
  { title: '说明（「有」时建议填）', dataIndex: 'note', width: 280 },
];

// 系统/审计字段：抽屉详情默认隐藏的子表列
const SUB_SKIP = new Set(['id', 'company_id', 'created_at', 'updated_at', 'created_by_id', 'updated_by_id']);

function decisionTag(decision) {
  if (decision === 'AGREE') return <Tag color="green">同意</Tag>;
  if (decision === 'REJECT') return <Tag color="red">驳回</Tag>;
  return <Tag>待签</Tag>;
}

// 子表网格提交：strip `_` 派生列 + 空值，新行 → parent_fk，旧行 → id（同 PurchaseDocPage.buildSubUpdates）
function buildLineUpdates(rows, table, fk) {
  return rows.map((r, i) => {
    const { id, _delete, [fk]: _p, ...rest } = r;
    const isNew = id == null || String(id).startsWith('new_');
    const fields = { ...rest, line_number: rest.line_number || i + 1 };
    Object.keys(fields).forEach((k) => {
      if (k.startsWith('_')) delete fields[k];
      if (fields[k] === '' || fields[k] === undefined) delete fields[k];
    });
    return isNew
      ? { table, parent_fk: fk, fields }
      : { table, id, _delete: _delete || undefined, fields };
  });
}

// 只读子表渲染（详情态）
function ReadonlyLines({ rows = [] }) {
  if (!rows.length) return <span style={{ color: '#bfbbb5' }}>无明细</span>;
  const keys = Object.keys(rows[0]).filter((k) => !SUB_SKIP.has(k) && !k.startsWith('_'));
  return (
    <div style={{ overflowX: 'auto' }}>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
        <thead>
          <tr style={{ background: 'rgba(245,242,239,0.6)' }}>
            {keys.map((k) => (
              <th key={k} style={{ textAlign: 'left', padding: '6px 10px', color: '#777169', fontWeight: 500, whiteSpace: 'nowrap' }}>{k}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.id} style={{ borderBottom: '1px solid rgba(0,0,0,0.05)' }}>
              {keys.map((k) => (
                <td key={k} style={{ padding: '6px 10px', whiteSpace: 'nowrap' }}>
                  {r[k] == null || r[k] === '' ? <span style={{ color: '#bfbbb5' }}>—</span> : String(r[k])}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function QualificationPage() {
  const { message } = App.useApp();
  const { user } = useAuth();
  const [schema, setSchema] = useState(null);
  const [schemaReady, setSchemaReady] = useState(null);   // null=未知 true=就绪 false=后端未注册
  const [allActions, setAllActions] = useState([]);
  const [detail, setDetail] = useState(null);
  const [docLines, setDocLines] = useState([]);
  const [riskLines, setRiskLines] = useState([]);
  const [cosignLines, setCosignLines] = useState([]);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [editMode, setEditMode] = useState(false);
  const [busy, setBusy] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);
  const [signComment, setSignComment] = useState({});   // {lineId: comment}

  const EDITABLE = useMemo(() => new Set(['DRAFT', 'REJECTED']), []);
  const HEAD_HIDDEN = useMemo(() => [NUMBER_FIELD, 'status'], []);

  const STATUS_ENUM = useMemo(() => [
    { text: '草拟 DRAFT', value: 'DRAFT' },
    { text: '★会签中 UNDER_COSIGN', value: 'UNDER_COSIGN' },
    { text: '通过 APPROVED', value: 'APPROVED' },
    { text: '驳回 REJECTED', value: 'REJECTED' },
    { text: '失效 EXPIRED', value: 'EXPIRED' },
  ], []);

  const tableRequest = useCallback(async (params = {}) => {
    let sc = schema;
    if (!sc) {
      try { const { data } = await getSchema(TABLE); sc = data; setSchema(data); setSchemaReady(true); }
      catch { setSchemaReady(false); return { data: [], success: true, total: 0 }; }
    }
    const { current: _c, pageSize, keyword, status, ...rest } = params;
    const filters = {};
    if (status) filters.status = status;
    for (const [k, v] of Object.entries(rest)) {
      if (v == null || v === '' || k === '_timestamp') continue;
      filters[k] = v;
    }
    try {
      const { data } = await query(TABLE, {
        filters, search: keyword || '', order_by: '-id',
        limit: Math.min(pageSize || 20, 100),
      });
      return { data: data.data || [], success: true, total: data.total ?? (data.data || []).length };
    } catch (e) {
      message.error(e.response?.data?.detail || '加载客户认证失败');
      return { data: [], success: false, total: 0 };
    }
  }, [schema, message]);

  useEffect(() => {
    getTransitions().then(({ data }) => {
      setAllActions((data || []).filter((a) => a.doc_type === DOC_TYPE));
    }).catch(() => setAllActions([]));
  }, []);

  const loadLines = useCallback(async (headId) => {
    if (!headId) { setDocLines([]); setRiskLines([]); setCosignLines([]); return; }
    try {
      const [docs, risks, cos] = await Promise.all([
        query(DOC_LINE.table, { filters: { [DOC_LINE.fk]: headId }, limit: 200 }).catch(() => ({ data: { data: [] } })),
        query(RISK_LINE.table, { filters: { [RISK_LINE.fk]: headId }, limit: 200 }).catch(() => ({ data: { data: [] } })),
        // cosign_line 是 polymorphic：按 doc_type + doc_id + cosign_group 过滤
        query('cosign_line', { filters: { doc_type: DOC_TYPE, doc_id: headId, cosign_group: COSIGN_GROUP }, limit: 50 }).catch(() => ({ data: { data: [] } })),
      ]);
      setDocLines((docs.data?.data || []).map((r) => ({ ...r })));
      setRiskLines((risks.data?.data || []).map((r) => ({ ...r })));
      setCosignLines((cos.data?.data || []).map((r) => ({ ...r })));
    } catch { setDocLines([]); setRiskLines([]); setCosignLines([]); }
  }, []);

  const openDetail = useCallback((row, edit = false) => {
    setDetail(row);
    setEditMode(edit && (!row || EDITABLE.has(row.status)));
    setSignComment({});
    loadLines(row?.id);
    setDrawerOpen(true);
  }, [loadLines, EDITABLE]);

  const openNew = useCallback(() => {
    setDetail(null); setEditMode(true);
    setDocLines([]); setRiskLines([]); setCosignLines([]); setSignComment({});
    setDrawerOpen(true);
  }, []);

  const docActions = useMemo(() => {
    if (!detail?.status) return [];
    return allActions.filter((a) => a.from_state === detail.status);
  }, [allActions, detail]);

  const onSave = useCallback(async (values) => {
    const field_updates = {};
    for (const [k, v] of Object.entries(values)) {
      if (v === undefined || v === '') continue;
      field_updates[k] = v;
    }
    const sub_updates = [
      ...buildLineUpdates(docLines, DOC_LINE.table, DOC_LINE.fk),
      ...buildLineUpdates(riskLines, RISK_LINE.table, RISK_LINE.fk),
    ];
    try {
      const { data } = await transition({
        doc_type: DOC_TYPE, doc_id: detail?.id ?? null,
        field_updates, sub_updates,
        comment: detail?.id ? '客户认证更新' : '客户认证录入',
      });
      if (data?.success === false) {
        message.error(data.error || data.detail || '保存失败（引擎拒绝）');
        if (Array.isArray(data.rule_failures)) data.rule_failures.forEach((f) => message.warning(f));
        return false;
      }
      message.success(detail?.id ? '已保存' : '已建单');
      setDrawerOpen(false);
      setReloadKey((k) => k + 1);
      return true;
    } catch (e) {
      message.error(e.response?.data?.detail || '保存失败（引擎写路径未就绪）');
      return false;
    }
  }, [detail, docLines, riskLines, message]);

  // 推进动作（提交 / 通过 / 驳回 / 失效）：走 /api/transitions 真实边 → /api/transition
  const runAction = useCallback(async (action) => {
    if (!detail?.id) { message.warning('请先保存单据再推进'); return; }
    setBusy(true);
    try {
      const { data } = await transition({
        doc_type: DOC_TYPE, doc_id: detail.id,
        to_state: action.to_state, action_label: action.action_label,
        field_updates: {}, sub_updates: [],
        comment: action.action_label,
      });
      if (data?.success === false) {
        if (Array.isArray(data.rule_failures) && data.rule_failures.length) {
          message.error('校验未通过（会签未集齐 / 被驳回）');
          data.rule_failures.forEach((f) => message.warning(f));
        } else {
          message.error(data.error || data.detail || '推进失败');
        }
        return;
      }
      message.success(`${action.action_label} 成功`);
      setDrawerOpen(false);
      setReloadKey((k) => k + 1);
    } catch (e) {
      message.error(e.response?.data?.detail || '推进失败');
    } finally {
      setBusy(false);
    }
  }, [detail, message]);

  // 「我签字」= UNDER_COSIGN 自循环编辑 cosign_line（当前用户只能编自己那行）
  const signMyRow = useCallback(async (line, decision) => {
    if (!detail?.id) return;
    setBusy(true);
    try {
      const { data } = await transition({
        doc_type: DOC_TYPE, doc_id: detail.id,
        // to_state 不传 = 编辑模式（自循环，不切状态）
        field_updates: {},
        sub_updates: [{
          table: 'cosign_line', id: line.id,
          fields: { decision, comment: signComment[line.id] || '' },
        }],
        comment: `会签${decision === 'AGREE' ? '同意' : '驳回'}`,
      });
      if (data?.success === false) {
        message.error(data.error || data.detail || '签字失败');
        if (Array.isArray(data.rule_failures)) data.rule_failures.forEach((f) => message.warning(f));
        return;
      }
      message.success(decision === 'AGREE' ? '已同意' : '已驳回');
      loadLines(detail.id);   // 就地刷新会签子表
    } catch (e) {
      message.error(e.response?.data?.detail || '签字失败（引擎写路径未就绪）');
    } finally {
      setBusy(false);
    }
  }, [detail, signComment, loadLines, message]);

  const columns = useMemo(() => schemaToColumns(schema?.fields || [], {
    frozen: [NUMBER_FIELD, 'status'].filter(Boolean),
    statusFilter: ['status'],
    statusEnum: { status: STATUS_ENUM },
    actionCol: {
      title: '操作', dataIndex: '_action', width: 130, fixed: 'right', search: false, hideInSetting: true,
      render: (_, row) => (
        <Space size={4}>
          <Button type="link" size="small"
            onClick={(e) => { e.stopPropagation(); openDetail(row, false); }}>详情</Button>
          {EDITABLE.has(row.status) && (
            <Button type="link" size="small"
              onClick={(e) => { e.stopPropagation(); openDetail(row, true); }}>编辑</Button>
          )}
        </Space>
      ),
    },
  }), [schema, STATUS_ENUM, openDetail, EDITABLE]);

  const headFields = useMemo(() => schema?.fields || [], [schema]);
  const detailFields = useMemo(() => headFields.filter((f) => f.name !== 'id'), [headFields]);

  const Header = () => (
    <div style={{ marginBottom: 16 }}>
      <h2 style={{ fontSize: 26, fontWeight: 300, letterSpacing: '-0.01em', color: '#000', margin: 0, lineHeight: 1.2 }}>
        客户认证 / 标书
      </h2>
      <span style={{ color: '#777169', fontSize: 13 }}>
        客户 / 销售 · 引擎单据 <code>{DOC_TYPE}</code> · 薄版认证 + ★并行会签（PA + 财务 + BOSS 全签才过）
      </span>
    </div>
  );

  // 会签面板（详情态 UNDER_COSIGN 显示）
  const renderCosignPanel = () => {
    if (!cosignLines.length) return null;
    return (
      <div style={{ marginTop: 16 }}>
        <div style={{ fontWeight: 500, color: '#4e4e4e', marginBottom: 8 }}>
          ★ 会签签字（并行 · PA + 财务 + BOSS 全「同意」才通过，任一「驳回」打回）
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {cosignLines.map((line) => {
            const isMyRow = user && (line.required_role === user.role || user.role === 'ADMIN' || user.role === 'BOSS');
            const canSignNow = isMyRow && line.decision === 'PENDING' && detail?.status === 'UNDER_COSIGN';
            return (
              <div key={line.id} style={{
                border: '1px solid rgba(0,0,0,0.08)', borderRadius: 8, padding: '10px 12px',
              }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
                  <Tag style={{ background: '#f5f2ef', color: '#4e4e4e', border: 'none' }}>
                    {COSIGN_ROLE_LABEL[line.required_role] || line.required_role}
                  </Tag>
                  {decisionTag(line.decision)}
                  {line.signed_at && (
                    <span style={{ color: '#bfbbb5', fontSize: 12 }}>
                      {String(line.signed_at).slice(0, 19).replace('T', ' ')}
                    </span>
                  )}
                  {line.comment && <span style={{ color: '#777169', fontSize: 13 }}>意见：{line.comment}</span>}
                </div>
                {canSignNow && (
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 8 }}>
                    <Input
                      size="small" placeholder="签字意见（可选）"
                      value={signComment[line.id] || ''}
                      onChange={(e) => setSignComment((s) => ({ ...s, [line.id]: e.target.value }))}
                      style={{ maxWidth: 280 }}
                    />
                    <Button size="small" type="primary" loading={busy}
                      onClick={() => signMyRow(line, 'AGREE')}>同意</Button>
                    <Button size="small" danger loading={busy}
                      onClick={() => signMyRow(line, 'REJECT')}>驳回</Button>
                  </div>
                )}
                {isMyRow && line.decision === 'PENDING' && detail?.status !== 'UNDER_COSIGN' && (
                  <div style={{ color: '#bfbbb5', fontSize: 12, marginTop: 6 }}>非会签态，暂不可签</div>
                )}
                {!isMyRow && line.decision === 'PENDING' && (
                  <div style={{ color: '#bfbbb5', fontSize: 12, marginTop: 6 }}>等待该角色签字（你只能签自己那行）</div>
                )}
              </div>
            );
          })}
        </div>
      </div>
    );
  };

  if (schemaReady === false) {
    return (
      <div>
        <Header />
        <Alert
          type="warning" showIcon style={{ marginBottom: 16, borderRadius: 12 }}
          title="功能已就绪 · 待后端开通"
          description="客户认证（薄版）为新增 doc_type CUSTOMER_QUALIFICATION。需后端段3c：① 新增 customer_qualification 头表（qualification_number 月度连号 QUAL{YYMM}-{seq} + customer_id / cert_type / valid_until 等）+ 资料清单子表 qualification_doc_line（FK qualification_id）+ 协议风险审查子表 qualification_risk_line（FK qualification_id）；② WorkflowDefinition（DRAFT→UNDER_COSIGN→APPROVED / REJECTED→EXPIRED，REJECTED→UNDER_COSIGN 重提；提交进 UNDER_COSIGN 的 effect 调 generate_cosign_lines 预生成 PA+FINANCE+BOSS 三行待签，cosign_group=CERTIFICATION）；③ 复用 services/cosign.py 并行会签标准件（register_cosign_checkpoint 已为 cosign_group=CERTIFICATION 声明集齐校验器，doc_type 由 CUSTOMER 改 / 增 CUSTOMER_QUALIFICATION，进 APPROVED 前集齐 AGREE 才放行、任一 REJECT 打回 REJECTED）；④ APPROVED 回写客户认证码 effect。会签子表 cosign_line 表已存在。注册后本页自动点亮（schema / transitions 驱动，会签面板按 cosign_line 真实行渲染）。"
        />
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="客户认证写路径待后端开通" />
      </div>
    );
  }

  return (
    <div>
      <Header />
      <Alert
        type="info" showIcon style={{ marginBottom: 16, borderRadius: 12 }}
        title="客户认证（薄版）= 客户 / 认证类型 / 有效期 + 资料清单子表（资料项 / 是否齐备）+ 协议风险审查子表（违约金 / 索赔 / 质保期冲突 有 / 无）+ ★会签签字子表（PA + 财务 + BOSS 并行）"
        description="审核 = 并行会签标准件（services/cosign.py，不动引擎核心）：提交进入会签态预生成 PA + 财务 + BOSS 三行待签，各签票方往自己那行填同意 / 驳回 + 意见（并行任意顺序，当前用户只能编自己那行）；集齐三方「同意」才能「通过」（APPROVED），任一「驳回」打回（REJECTED）整改。会签进审批中心 / 待办收件箱。薄实现：系统只管认证状态 + 资料清单勾选 + 风险审查打勾留痕 + 附件，不写协议正文。本单不推金蝶。动作按钮一律由引擎流程边生成 → /api/transition 唯一写入路径，不写死状态码。"
      />

      <BizTable
        key={reloadKey}
        headerTitle="客户认证台账"
        rowKey="id"
        columns={columns}
        request={tableRequest}
        rowSelection={false}
        toolBarRender={() => [
          <Button key="new" type="primary" icon={<PlusOutlined />} onClick={openNew}>新建认证单</Button>,
        ]}
        onRow={(row) => ({ onClick: () => openDetail(row, false), style: { cursor: 'pointer' } })}
        scroll={{ x: 'max-content', y: 'calc(100vh - 420px)' }}
      />

      <BizDrawerForm
        open={drawerOpen}
        onOpenChange={setDrawerOpen}
        title={`客户认证 · ${editMode ? (detail?.id ? '编辑' : '新建') : '详情'}${detail?.[NUMBER_FIELD] ? ` · ${detail[NUMBER_FIELD]}` : ''}`}
        width={1040}
        onFinish={editMode ? onSave : undefined}
        initialValues={editMode ? (detail || {}) : undefined}
        submitter={editMode ? { searchConfig: { submitText: '保存认证单' } } : false}
      >
        {detail?.id && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12, flexWrap: 'wrap' }}>
            <StatusPill value={detail.status} />
            {docActions.length === 0 ? (
              <span style={{ color: '#bfbbb5', fontSize: 12 }}>当前状态无可执行推进动作（或非本角色权限）</span>
            ) : docActions.map((a) => {
              const danger = a.to_state === 'REJECTED' || a.to_state === 'CANCELLED' || a.to_state === 'EXPIRED';
              const primary = a.to_state === 'UNDER_COSIGN' || a.to_state === 'APPROVED';
              return (
                <Button
                  key={`${a.action_label}-${a.to_state}`}
                  size="small"
                  type={primary ? 'primary' : 'default'}
                  danger={danger}
                  loading={busy}
                  onClick={() => runAction(a)}
                >
                  {a.action_label}
                </Button>
              );
            })}
          </div>
        )}

        {editMode ? (
          <>
            <div style={{ fontWeight: 500, color: '#4e4e4e', margin: '4px 0 8px' }}>认证单头</div>
            <MasterFormFields fields={headFields} hidden={HEAD_HIDDEN} />

            <div style={{ fontWeight: 500, color: '#4e4e4e', margin: '12px 0 8px' }}>
              资料清单（必备项须齐 · 网格录入）
            </div>
            <BizEditableTable
              value={docLines} onChange={setDocLines}
              rowKey="id" columns={DOC_LINE_COLUMNS}
              recordCreatorProps={{ record: () => ({ id: `new_${Date.now()}` }) }}
            />

            <div style={{ fontWeight: 500, color: '#4e4e4e', margin: '16px 0 8px' }}>
              协议风险审查项（违约金 / 索赔 / 质保期冲突 · 三项均须判 · 网格录入）
            </div>
            <BizEditableTable
              value={riskLines} onChange={setRiskLines}
              rowKey="id" columns={RISK_LINE_COLUMNS}
              recordCreatorProps={{ record: () => ({ id: `new_${Date.now()}`, presence: 'PENDING' }) }}
            />
          </>
        ) : (
          <>
            <Descriptions column={2} size="small" bordered
              styles={{ label: { width: 130, color: '#777169' } }}>
              {detailFields.map((f) => (
                <Descriptions.Item key={f.name} label={f.label || f.name}>
                  {f.name === 'status'
                    ? <StatusPill value={detail?.[f.name]} />
                    : renderCellByField(f, detail?.[f.name])}
                </Descriptions.Item>
              ))}
            </Descriptions>

            <div style={{ fontWeight: 500, color: '#4e4e4e', margin: '16px 0 8px' }}>资料清单 · {docLines.length} 行</div>
            <ReadonlyLines rows={docLines} />

            <div style={{ fontWeight: 500, color: '#4e4e4e', margin: '16px 0 8px' }}>协议风险审查项 · {riskLines.length} 行</div>
            <ReadonlyLines rows={riskLines} />

            {renderCosignPanel()}
          </>
        )}
      </BizDrawerForm>
    </div>
  );
}
