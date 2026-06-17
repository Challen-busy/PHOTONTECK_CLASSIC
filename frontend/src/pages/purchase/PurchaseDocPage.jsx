/**
 * PurchaseDocPage —— 采购域单据通用页（台账 → 详情抽屉 → 动作按钮）
 *
 * 落 UX 律 14 骨架四件套：
 *   - 台账：BizTable over /api/query（saved-views/查询条由 ProTable search 提供；状态药丸；冻结单号/状态）
 *   - 抽屉：BizDrawerForm（头 schema 驱动 MasterFormFields + 明细 PurchaseLineGrid 子表网格），不跳页
 *   - 动作：顶部按钮由 /api/transitions 按 doc_type + 当前状态过滤生成，一律走引擎唯一写入路径 /api/transition
 *
 * 单据差异（doc_type/表/子表/状态枚举/冻结列/头隐藏列/导语/扫码序列）全部参数化，
 * 三张采购询价/通知页只是不同参数的薄包装。
 *
 * ★引擎实况：supplier_inquiry 等 doc_type / 表 / 轻量流程由后端段2b 注册。后端未注册时
 *   /api/schema 失败 → 显示「功能已就绪 · 待后端开通」占位（14 律 §8），注册后自动点亮，
 *   不写死状态码（动作一律从 /api/transitions 读真实边）。
 *
 * ★段1b 教训：子表派生 _ 列提交前必须 strip——buildSubUpdates 统一删除 `_` 前缀键 + 空值键。
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { Alert, App, Button, Descriptions, Empty, Space } from 'antd';
import { PlusOutlined } from '@ant-design/icons';
import { BizTable, BizDrawerForm } from '../../components/biz';
import { query, getSchema, transition, getTransitions } from '../../api';
import MasterFormFields from '../master/MasterFormFields';
import PurchaseLineGrid from './PurchaseLineGrid';
import { schemaToColumns, renderCellByField } from '../wms/wmsHelpers';
import { StatusPill } from '../wms/wmsShared';

export default function PurchaseDocPage({
  docType,           // 'SALES_INQUIRY'
  table,             // 'sales_inquiry'
  lineTable,         // 'sales_inquiry_line'
  lineFk,            // 'inquiry_id'
  title,             // '内部询价'
  subtitle,          // 导语副标题
  numberField,       // 'inquiry_number'（台账首列冻结 + 头表单隐藏）
  statusEnum = [],   // [{text,value}] 状态筛选候选（仅筛选提示；真实边以 /api/transitions 为准）
  editableStates = ['DRAFT'],   // 哪些状态可改头/明细
  headHidden = [],   // 头表单额外隐藏列（编号/状态已默认隐藏）
  lineTitle = '明细（网格录入）',
  scanSequence,      // 子表扫码顺序锁（可选）
  intro,             // {title, description} 顶部说明 Alert
  newLabel,          // 新建按钮文案
  todoNote,          // 待后端开通时占位说明
  primaryToStates = [],   // 哪些 to_state 用 primary 按钮高亮
  noLines = false,   // 无子表单据（如付款申请 ADVANCE_PAYMENT）：跳过明细加载/网格，仅头 + 动作
  derivedColumns = [],  // ➕ 前端派生只读列（引擎无原生计算列，如样品超期天数 = 今天-基准日），插在操作列前
}) {
  const { message } = App.useApp();
  const [schema, setSchema] = useState(null);
  const [schemaReady, setSchemaReady] = useState(null);  // null=未知 true=就绪 false=后端未注册
  const [allActions, setAllActions] = useState([]);
  const [detail, setDetail] = useState(null);
  const [lineRows, setLineRows] = useState([]);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [editMode, setEditMode] = useState(false);
  const [busy, setBusy] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);

  const EDITABLE = useMemo(() => new Set(editableStates), [editableStates]);
  const HEAD_FORM_HIDDEN = useMemo(
    () => [numberField, 'status', ...headHidden].filter(Boolean),
    [numberField, headHidden]
  );

  const tableRequest = useCallback(async (params = {}) => {
    let sc = schema;
    if (!sc) {
      try { const { data } = await getSchema(table); sc = data; setSchema(data); setSchemaReady(true); }
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
      const { data } = await query(table, {
        filters, search: keyword || '', order_by: '-id',
        limit: Math.min(pageSize || 20, 100),
      });
      return { data: data.data || [], success: true, total: data.total ?? (data.data || []).length };
    } catch (e) {
      message.error(e.response?.data?.detail || `加载${title}失败`);
      return { data: [], success: false, total: 0 };
    }
  }, [schema, table, title, message]);

  useEffect(() => {
    getTransitions().then(({ data }) => {
      setAllActions((data || []).filter((a) => a.doc_type === docType));
    }).catch(() => setAllActions([]));
  }, [docType]);

  const loadLines = useCallback(async (headId) => {
    if (noLines || !headId) { setLineRows([]); return; }
    try {
      const { data } = await query(lineTable, { filters: { [lineFk]: headId }, limit: 200 });
      setLineRows((data?.data || []).map((r) => ({ ...r })));
    } catch { setLineRows([]); }
  }, [noLines, lineTable, lineFk]);

  const openDetail = useCallback((row, edit = false) => {
    setDetail(row);
    setEditMode(edit && (!row || EDITABLE.has(row.status)));
    loadLines(row?.id);
    setDrawerOpen(true);
  }, [loadLines, EDITABLE]);

  const openNew = useCallback(() => {
    setDetail(null); setEditMode(true); setLineRows([]); setDrawerOpen(true);
  }, []);

  const docActions = useMemo(() => {
    if (!detail?.status) return [];
    return allActions.filter((a) => a.from_state === detail.status);
  }, [allActions, detail]);

  // ★段1b 教训：strip `_` 前缀派生展示列 + 空值键，防 buildSubUpdates 剥键丢真值。
  // noLines 单据（无子表）：恒返回空 sub_updates。
  const buildSubUpdates = useCallback(() => (noLines ? [] : lineRows.map((r, i) => {
    const { id, _delete, [lineFk]: _p, ...rest } = r;
    const isNew = id == null || String(id).startsWith('new_');
    const fields = { ...rest, line_number: rest.line_number || i + 1 };
    Object.keys(fields).forEach((k) => {
      if (k.startsWith('_')) delete fields[k];
      if (fields[k] === '' || fields[k] === undefined) delete fields[k];
    });
    return isNew
      ? { table: lineTable, parent_fk: lineFk, fields }
      : { table: lineTable, id, _delete: _delete || undefined, fields };
  })), [noLines, lineRows, lineTable, lineFk]);

  const onSave = useCallback(async (values) => {
    const field_updates = {};
    for (const [k, v] of Object.entries(values)) {
      if (v === undefined || v === '') continue;
      field_updates[k] = v;
    }
    try {
      const { data } = await transition({
        doc_type: docType, doc_id: detail?.id ?? null,
        field_updates, sub_updates: buildSubUpdates(),
        comment: detail?.id ? `${title}更新` : `${title}录入`,
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
  }, [detail, docType, title, buildSubUpdates, message]);

  const runAction = useCallback(async (action) => {
    if (!detail?.id) { message.warning('请先保存单据再推进'); return; }
    setBusy(true);
    try {
      const sub_updates = EDITABLE.has(detail.status) ? buildSubUpdates() : [];
      const { data } = await transition({
        doc_type: docType, doc_id: detail.id,
        to_state: action.to_state, action_label: action.action_label,
        field_updates: {}, sub_updates,
        comment: action.action_label,
      });
      if (data?.success === false) {
        if (Array.isArray(data.rule_failures) && data.rule_failures.length) {
          message.error('校验未通过');
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
  }, [detail, docType, EDITABLE, buildSubUpdates, message]);

  const baseColumns = useMemo(() => schemaToColumns(schema?.fields || [], {
    frozen: [numberField, 'status'].filter(Boolean),
    statusFilter: ['status'],
    statusEnum: { status: statusEnum },
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
  }), [schema, numberField, statusEnum, openDetail, EDITABLE]);

  // 派生只读列插在「操作」列前（操作列恒为最后一项），保持冻结操作列在最右
  const columns = useMemo(() => {
    if (!derivedColumns.length) return baseColumns;
    const action = baseColumns[baseColumns.length - 1];
    return [...baseColumns.slice(0, -1), ...derivedColumns, action];
  }, [baseColumns, derivedColumns]);

  const headFields = useMemo(() => schema?.fields || [], [schema]);
  const detailFields = useMemo(() => headFields.filter((f) => f.name !== 'id'), [headFields]);

  const PageHeader = () => (
    <div style={{ marginBottom: 16 }}>
      <h2 style={{ fontSize: 26, fontWeight: 300, letterSpacing: '-0.01em', color: '#000', margin: 0, lineHeight: 1.2 }}>
        {title}
      </h2>
      <span style={{ color: '#777169', fontSize: 13 }}>
        采购 / 供应链 · 引擎单据 <code>{docType}</code>{subtitle ? ` · ${subtitle}` : ''}
      </span>
    </div>
  );

  if (schemaReady === false) {
    return (
      <div>
        <PageHeader />
        <Alert
          type="warning" showIcon style={{ marginBottom: 16, borderRadius: 12 }}
          title="功能已就绪 · 待后端开通"
          description={todoNote || `单据 ${docType} 的模型 / 流程定义尚未在后端注册。后端段2b 注册后本页自动点亮（schema/transitions 驱动，不写死状态码）。`}
        />
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={`${title} 写路径待后端开通`} />
      </div>
    );
  }

  return (
    <div>
      <PageHeader />
      {intro && (
        <Alert
          type="info" showIcon style={{ marginBottom: 16, borderRadius: 12 }}
          title={intro.title}
          description={intro.description}
        />
      )}

      <BizTable
        key={reloadKey}
        headerTitle={`${title}台账`}
        rowKey="id"
        columns={columns}
        request={tableRequest}
        rowSelection={false}
        toolBarRender={() => [
          <Button key="new" type="primary" icon={<PlusOutlined />} onClick={openNew}>
            {newLabel || `新建${title}`}
          </Button>,
        ]}
        onRow={(row) => ({ onClick: () => openDetail(row, false), style: { cursor: 'pointer' } })}
        scroll={{ x: 'max-content', y: 'calc(100vh - 420px)' }}
      />

      <BizDrawerForm
        open={drawerOpen}
        onOpenChange={setDrawerOpen}
        title={`${title} · ${editMode ? (detail?.id ? '编辑' : '新建') : '详情'}${detail?.[numberField] ? ` · ${detail[numberField]}` : ''}`}
        width={1040}
        onFinish={editMode ? onSave : undefined}
        initialValues={editMode ? (detail || {}) : undefined}
        submitter={editMode ? { searchConfig: { submitText: `保存${title}` } } : false}
      >
        {detail?.id && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12, flexWrap: 'wrap' }}>
            <StatusPill value={detail.status} />
            {docActions.length === 0 ? (
              <span style={{ color: '#bfbbb5', fontSize: 12 }}>当前状态无可执行动作（或非本角色权限）</span>
            ) : docActions.map((a) => {
              const danger = a.to_state === 'CANCELLED' || a.to_state === 'CLOSED';
              return (
                <Button
                  key={`${a.action_label}-${a.to_state}`}
                  size="small"
                  type={primaryToStates.includes(a.to_state) ? 'primary' : 'default'}
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
            <div style={{ fontWeight: 500, color: '#4e4e4e', margin: '4px 0 8px' }}>单据头</div>
            <MasterFormFields fields={headFields} hidden={HEAD_FORM_HIDDEN} />

            {!noLines && (
              <>
                <div style={{ fontWeight: 500, color: '#4e4e4e', margin: '12px 0 8px' }}>{lineTitle}</div>
                <PurchaseLineGrid
                  value={lineRows} onChange={setLineRows}
                  lineTable={lineTable} lineFk={lineFk}
                  scanSequence={scanSequence}
                />
              </>
            )}
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
            {!noLines && (
              <>
                <div style={{ fontWeight: 500, color: '#4e4e4e', margin: '16px 0 8px' }}>
                  {lineTitle.replace('（网格录入）', '')} · {lineRows.length} 行
                </div>
                <PurchaseLineReadonly rows={lineRows} fields={lineFields(lineRows)} />
              </>
            )}
          </>
        )}
      </BizDrawerForm>
    </div>
  );
}

// 只读子表列：从行对象推断可显示键（隐藏系统/FK 父键），不写死价格列
function lineFields(rows) {
  if (!rows.length) return [];
  const SKIP = new Set(['id', 'company_id', 'created_at', 'updated_at', 'created_by_id', 'updated_by_id']);
  return Object.keys(rows[0]).filter((k) => !SKIP.has(k) && !k.startsWith('_'));
}

function PurchaseLineReadonly({ rows = [], fields = [] }) {
  if (!rows.length) return <span style={{ color: '#bfbbb5' }}>无明细</span>;
  return (
    <div style={{ overflowX: 'auto' }}>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
        <thead>
          <tr style={{ background: 'rgba(245,242,239,0.6)' }}>
            {fields.map((k) => (
              <th key={k} style={{ textAlign: 'left', padding: '6px 10px', color: '#777169', fontWeight: 500, whiteSpace: 'nowrap' }}>{k}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.id} style={{ borderBottom: '1px solid rgba(0,0,0,0.05)' }}>
              {fields.map((k) => (
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
