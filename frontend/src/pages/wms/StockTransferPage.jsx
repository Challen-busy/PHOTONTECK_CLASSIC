/**
 * StockTransferPage —— 调拨单（STOCK_TRANSFER，仅同公司内仓间，PRD 03b 页面 5）
 *
 * 落 UX 律 14：台账(BizTable) → 详情抽屉(BizDrawerForm，不跳页) → 动作按钮(走 /api/transition)。
 *   - 台账：BizTable over /api/query stock_transfer（冻结 调拨单号/状态；status 药丸）
 *   - 抽屉：头 BizDrawerForm（schema 驱动：源/目标库位 cell 选择器[本公司] + 备注）
 *           + 批次明细 BatchLineGrid（入仓编号选择器[本公司+结存>0] + 调拨数量≤结存）
 *   - 动作：顶部按钮由 /api/transitions 按 doc_type=STOCK_TRANSFER + 当前状态 + 本角色过滤生成
 *           （提交/复核/完成 由引擎边定义生成）— 一律走引擎唯一写入路径 execute_transition，失败如实弹错。
 *
 * ⚠️ 引擎实况：STOCK_TRANSFER doc_type / stock_transfer 表 / 同公司校验 hard_rule 由后端段1b-2(disjoint)
 *    注册（照段0c 轻量流程套路新建模型 + WorkflowDefinition states JSONB）。本页 schema/transitions 驱动：
 *    后端未注册时 /api/schema 失败 → 显示「功能已就绪·待后端开通」占位(14 律 §8)，注册后自动点亮、不写死状态码。
 *    源/目标库位「同 company_id」由后端 hard_rule + 行级隔离双保险终判，本页只列本公司库位候选。
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { Alert, App, Button, Descriptions, Empty, Space } from 'antd';
import { HistoryOutlined, PlusOutlined } from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import { ProFormSelect } from '@ant-design/pro-components';
import { BizTable, BizDrawerForm } from '../../components/biz';
import { query, getSchema, transition, getTransitions } from '../../api';
import MasterFormFields from '../master/MasterFormFields';
import BatchLineGrid from './BatchLineGrid';
import { schemaToColumns, renderCellByField } from './wmsHelpers';
import { StatusPill } from './wmsShared';
import { displayName } from '../master/fkOptions';

const DOC_TYPE = 'STOCK_TRANSFER';
const TABLE = 'stock_transfer';
const LINE_TABLE = 'stock_transfer_line';
const LINE_FK = 'stock_transfer_id';

// 状态过滤候选（轻量调拨流程：草稿→复核→完成；引擎真实 code 以 /api/transitions 为准，此处仅筛选提示）
const STATUS_ENUM = [
  { text: 'DRAFT 草稿', value: 'DRAFT' },
  { text: 'REVIEW 待复核', value: 'REVIEW' },
  { text: 'DONE 已完成', value: 'DONE' },
  { text: 'CANCELLED 已取消', value: 'CANCELLED' },
];

// 仅 DRAFT 态可改头/明细
const EDITABLE_STATES = new Set(['DRAFT']);
// 头部表单不录入的系统/自动列
const HEAD_FORM_HIDDEN = ['transfer_number', 'status'];

export default function StockTransferPage() {
  const navigate = useNavigate();
  const { message } = App.useApp();
  const [schema, setSchema] = useState(null);
  const [schemaReady, setSchemaReady] = useState(null);   // null=未知 true=就绪 false=后端未注册
  const [allActions, setAllActions] = useState([]);
  const [detail, setDetail] = useState(null);
  const [lineRows, setLineRows] = useState([]);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [editMode, setEditMode] = useState(false);
  const [busy, setBusy] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);
  const [locOptions, setLocOptions] = useState([]);

  // 本公司库位候选（源/目标；/api/query 已按 active_company 行级隔离 → 只列本公司）
  useEffect(() => {
    query('warehouse_location', { limit: 300 }).then(({ data }) => {
      setLocOptions((data?.data || []).map((l) => ({ label: displayName(l), value: l.id })));
    }).catch(() => setLocOptions([]));
  }, []);

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
      message.error(e.response?.data?.detail || '加载调拨单失败');
      return { data: [], success: false, total: 0 };
    }
  }, [schema, message]);

  useEffect(() => {
    getTransitions().then(({ data }) => {
      setAllActions((data || []).filter((a) => a.doc_type === DOC_TYPE));
    }).catch(() => setAllActions([]));
  }, []);

  const loadLines = useCallback(async (headId) => {
    if (!headId) { setLineRows([]); return; }
    try {
      const { data } = await query(LINE_TABLE, { filters: { [LINE_FK]: headId }, limit: 200 });
      setLineRows((data?.data || []).map((r) => ({ ...r })));
    } catch { setLineRows([]); }
  }, []);

  const openDetail = useCallback((row, edit = false) => {
    setDetail(row);
    setEditMode(edit && (!row || EDITABLE_STATES.has(row.status)));
    loadLines(row?.id);
    setDrawerOpen(true);
  }, [loadLines]);

  const openNew = useCallback(() => {
    setDetail(null); setEditMode(true); setLineRows([]); setDrawerOpen(true);
  }, []);

  const docActions = useMemo(() => {
    if (!detail?.status) return [];
    return allActions.filter((a) => a.from_state === detail.status);
  }, [allActions, detail]);

  const buildSubUpdates = useCallback(() => lineRows.map((r, i) => {
    const { id, _delete, [LINE_FK]: _p, ...rest } = r;
    const isNew = id == null || String(id).startsWith('new_');
    const fields = { ...rest, line_number: rest.line_number || i + 1 };
    Object.keys(fields).forEach((k) => {
      if (k.startsWith('_')) delete fields[k];
      if (fields[k] === '' || fields[k] === undefined) delete fields[k];
    });
    return isNew
      ? { table: LINE_TABLE, parent_fk: LINE_FK, fields }
      : { table: LINE_TABLE, id, _delete: _delete || undefined, fields };
  }), [lineRows]);

  const onSave = useCallback(async (values) => {
    const field_updates = {};
    for (const [k, v] of Object.entries(values)) {
      if (v === undefined || v === '') continue;
      field_updates[k] = v;
    }
    try {
      const { data } = await transition({
        doc_type: DOC_TYPE, doc_id: detail?.id ?? null,
        field_updates, sub_updates: buildSubUpdates(),
        comment: detail?.id ? '调拨单更新' : '调拨单录入',
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
  }, [detail, buildSubUpdates, message]);

  const runAction = useCallback(async (action) => {
    if (!detail?.id) { message.warning('请先保存单据再推进'); return; }
    setBusy(true);
    try {
      const sub_updates = EDITABLE_STATES.has(detail.status) ? buildSubUpdates() : [];
      const { data } = await transition({
        doc_type: DOC_TYPE, doc_id: detail.id,
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
  }, [detail, buildSubUpdates, message]);

  const columns = useMemo(() => schemaToColumns(schema?.fields || [], {
    frozen: ['transfer_number', 'status'],
    statusFilter: ['status'],
    statusEnum: { status: STATUS_ENUM },
    actionCol: {
      title: '操作', dataIndex: '_action', width: 150, fixed: 'right', search: false, hideInSetting: true,
      render: (_, row) => (
        <Space size={4}>
          <Button type="link" size="small"
            onClick={(e) => { e.stopPropagation(); openDetail(row, false); }}>详情</Button>
          {EDITABLE_STATES.has(row.status) && (
            <Button type="link" size="small"
              onClick={(e) => { e.stopPropagation(); openDetail(row, true); }}>编辑</Button>
          )}
          <Button type="link" size="small" icon={<HistoryOutlined />}
            onClick={(e) => { e.stopPropagation(); navigate(`/history/${DOC_TYPE}/${row.id}`); }}>历史</Button>
        </Space>
      ),
    },
  }), [schema, navigate, openDetail]);

  const headFields = useMemo(() => schema?.fields || [], [schema]);
  const detailFields = useMemo(() => headFields.filter((f) => f.name !== 'id'), [headFields]);
  // 源/目标库位若 schema 已含 FK 列，交给 MasterFormFields cell 选择器；这里仅作显式兜底标签
  const hasLocFields = useMemo(
    () => headFields.some((f) => f.name === 'source_location_id' || f.name === 'target_location_id'),
    [headFields]
  );

  if (schemaReady === false) {
    return (
      <div>
        <PageHeader />
        <Alert
          type="warning" showIcon style={{ marginBottom: 16, borderRadius: 12 }}
          title="功能已就绪 · 待后端开通"
          description="调拨单 STOCK_TRANSFER 的模型 / 流程定义（同公司内仓间移库，源/目标库位同 company_id 校验）尚未在后端注册。后端段1b-2 注册 stock_transfer 表 + 轻量流程后，本页自动点亮（schema/transitions 驱动，不写死状态码）。"
        />
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="调拨单写路径待后端开通" />
      </div>
    );
  }

  return (
    <div>
      <PageHeader />
      <Alert
        type="info" showIcon style={{ marginBottom: 16, borderRadius: 12 }}
        title="一张调拨单 = 一次同公司内仓间移库；绝不跨公司（源/目标库位同 company_id 校验）"
        description="DRAFT 态可改头/明细；提交后经复核→完成，完成时引擎写两条库存流水（源库位减、目标库位加）。源/目标库位选择器只列本公司库位（行级隔离）。不改批次 SN/LOT/原厂报备客户，仅改库位。"
      />

      <BizTable
        key={reloadKey}
        headerTitle="调拨单台账"
        rowKey="id"
        columns={columns}
        request={tableRequest}
        rowSelection={false}
        toolBarRender={() => [
          <Button key="new" type="primary" icon={<PlusOutlined />} onClick={openNew}>新建调拨单</Button>,
        ]}
        onRow={(row) => ({ onClick: () => openDetail(row, false), style: { cursor: 'pointer' } })}
        scroll={{ x: 'max-content', y: 'calc(100vh - 420px)' }}
      />

      <BizDrawerForm
        open={drawerOpen}
        onOpenChange={setDrawerOpen}
        title={`调拨单 · ${editMode ? (detail?.id ? '编辑' : '新建') : '详情'}${detail?.transfer_number ? ` · ${detail.transfer_number}` : ''}`}
        width={1040}
        onFinish={editMode ? onSave : undefined}
        initialValues={editMode ? (detail || {}) : undefined}
        submitter={editMode ? { searchConfig: { submitText: '保存调拨单' } } : false}
      >
        {detail?.id && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12, flexWrap: 'wrap' }}>
            <StatusPill value={detail.status} />
            {docActions.length === 0 ? (
              <span style={{ color: '#bfbbb5', fontSize: 12 }}>当前状态无可执行动作（或非本角色权限）</span>
            ) : docActions.map((a) => {
              const danger = a.to_state === 'CANCELLED';
              return (
                <Button
                  key={`${a.action_label}-${a.to_state}`}
                  size="small"
                  type={a.to_state === 'DONE' || a.to_state === 'REVIEW' ? 'primary' : 'default'}
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
            <div style={{ fontWeight: 500, color: '#4e4e4e', margin: '4px 0 8px' }}>单据头（源 / 目标库位 · 本公司）</div>
            {!hasLocFields && (
              <Space size={12} style={{ width: '100%', marginBottom: 8 }}>
                <ProFormSelect
                  name="source_location_id" label="源库位" options={locOptions} showSearch
                  fieldProps={{ optionFilterProp: 'label', style: { minWidth: 220 } }}
                  rules={[{ required: true, message: '请选源库位' }]}
                />
                <ProFormSelect
                  name="target_location_id" label="目标库位（同公司）" options={locOptions} showSearch
                  fieldProps={{ optionFilterProp: 'label', style: { minWidth: 220 } }}
                  rules={[{ required: true, message: '请选目标库位' }]}
                  tooltip="目标库位必须与源库位同 company_id（后端 hard_rule 终判）"
                />
              </Space>
            )}
            <MasterFormFields fields={headFields} hidden={HEAD_FORM_HIDDEN} />

            <div style={{ fontWeight: 500, color: '#4e4e4e', margin: '12px 0 8px' }}>
              调拨明细（按入仓编号 · 网格录入 · 数量≤结存）
            </div>
            <BatchLineGrid
              value={lineRows} onChange={setLineRows}
              quantityField="quantity" quantityLabel="调拨数量"
              enforceRemain
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
            <div style={{ fontWeight: 500, color: '#4e4e4e', margin: '16px 0 8px' }}>
              调拨明细 · {lineRows.length} 行
            </div>
            <BatchLineReadonly rows={lineRows} qtyKey="quantity" qtyLabel="调拨数量" />
          </>
        )}
      </BizDrawerForm>
    </div>
  );
}

function PageHeader() {
  return (
    <div style={{ marginBottom: 16 }}>
      <h2 style={{ fontSize: 26, fontWeight: 300, letterSpacing: '-0.01em', color: '#000', margin: 0, lineHeight: 1.2 }}>
        调拨单
      </h2>
      <span style={{ color: '#777169', fontSize: 13 }}>
        仓储 WMS · 引擎单据 <code>{DOC_TYPE}</code> · 仅同公司内仓间移库
      </span>
    </div>
  );
}

/** 批次明细只读简表（调拨/调整共用） */
export function BatchLineReadonly({ rows = [], qtyKey = 'quantity', qtyLabel = '数量', extraKeys = [] }) {
  if (!rows.length) return <span style={{ color: '#bfbbb5' }}>无明细</span>;
  const KEYS = [
    ['inbound_number', '入仓编号'], ['serial_lot_number', 'SN/LOT'], ['goods_nature', '性质'],
    [qtyKey, qtyLabel], ...extraKeys,
  ];
  return (
    <div style={{ overflowX: 'auto' }}>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
        <thead>
          <tr style={{ background: 'rgba(245,242,239,0.6)' }}>
            {KEYS.map(([, label]) => (
              <th key={label} style={{ textAlign: 'left', padding: '6px 10px', color: '#777169', fontWeight: 500, whiteSpace: 'nowrap' }}>{label}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.id} style={{ borderBottom: '1px solid rgba(0,0,0,0.05)' }}>
              {KEYS.map(([k]) => (
                <td key={k} style={{
                  padding: '6px 10px', whiteSpace: 'nowrap',
                  textAlign: k === qtyKey ? 'right' : 'left',
                  fontFamily: k === qtyKey ? 'ui-monospace, monospace' : undefined,
                }}>
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
