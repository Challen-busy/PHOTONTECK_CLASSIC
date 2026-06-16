/**
 * StockAdjustmentPage —— 库存调整单（STOCK_ADJUSTMENT，盘点差异→推金蝶，PRD 03b 页面 7）
 *
 * 落 UX 律 14：台账(BizTable) → 详情抽屉(BizDrawerForm，不跳页) → 动作按钮(走 /api/transition)。
 *   - 台账：BizTable over /api/query stock_adjustment（冻结 调整单号/状态；status 药丸）
 *   - 抽屉：头 BizDrawerForm（schema 驱动：关联盘点单 fk + 备注）
 *           + 调整明细 BatchLineGrid（入仓编号 + 调整差异 + 差异原因 cell 选择器[必填]）
 *   - 动作：顶部按钮由 /api/transitions 按 doc_type=STOCK_ADJUSTMENT + 当前状态 + 本角色过滤生成
 *           （提交/财务确认/过账 由引擎边定义生成）— 一律走引擎唯一写入路径 execute_transition，失败如实弹错。
 *
 * ⚠️ 引擎实况：STOCK_ADJUSTMENT doc_type / stock_adjustment 表 / 差异原因必填 hard_rule / posted 推金蝶 effect
 *    由后端段1b-2(disjoint) 注册。本页 schema/transitions 驱动：后端未注册时显示「功能已就绪·待后端开通」
 *    占位(14 律 §8)，注册后自动点亮、不写死状态码。
 *
 * 注：盘点差异可由盘点单 review→adjusting EXPLICIT effect 派生调整单草稿（PRD 页面 6→7）；本页也支持手工建单。
 *    盘点页(InventoryCountPage)的「生成调整单」按现有 WMS counts API(adjustWmsCount) 直接调整库存（已存在路径），
 *    本调整单页是通用 STOCK_ADJUSTMENT 单据台账/录入入口，二者并存不冲突。
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
import { BatchLineReadonly } from './StockTransferPage';
import { schemaToColumns, renderCellByField } from './wmsHelpers';
import { StatusPill } from './wmsShared';

const DOC_TYPE = 'STOCK_ADJUSTMENT';
const TABLE = 'stock_adjustment';
const LINE_TABLE = 'stock_adjustment_line';
const LINE_FK = 'stock_adjustment_id';

// 状态过滤候选（轻量调整流程：草稿→财务确认→过账；引擎真实 code 以 /api/transitions 为准）
const STATUS_ENUM = [
  { text: 'DRAFT 草稿', value: 'DRAFT' },
  { text: 'CONFIRM 待财务确认', value: 'CONFIRM' },
  { text: 'POSTED 已过账', value: 'POSTED' },
  { text: 'CANCELLED 已取消', value: 'CANCELLED' },
];

// 差异原因取值集（PRD 页面 7：出库录错/入库录错/实物损/实物溢/其他）
const DIFF_REASONS = [
  { label: '出库录错', value: '出库录错' },
  { label: '入库录错', value: '入库录错' },
  { label: '实物损', value: '实物损' },
  { label: '实物溢', value: '实物溢' },
  { label: '其他', value: '其他' },
];

const EDITABLE_STATES = new Set(['DRAFT']);
const HEAD_FORM_HIDDEN = ['adjustment_number', 'status'];

export default function StockAdjustmentPage() {
  const navigate = useNavigate();
  const { message } = App.useApp();
  const [schema, setSchema] = useState(null);
  const [schemaReady, setSchemaReady] = useState(null);
  const [allActions, setAllActions] = useState([]);
  const [detail, setDetail] = useState(null);
  const [lineRows, setLineRows] = useState([]);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [editMode, setEditMode] = useState(false);
  const [busy, setBusy] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);
  const [countOptions, setCountOptions] = useState([]);

  // 关联盘点单候选（本公司盘点任务；走 WMS counts 已有路径）
  useEffect(() => {
    query('inventory_count', { order_by: '-id', limit: 200 }).then(({ data }) => {
      setCountOptions((data?.data || []).map((c) => ({
        label: `${c.count_number || `#${c.id}`}${c.status ? ` · ${c.status}` : ''}`, value: c.id,
      })));
    }).catch(() => setCountOptions([]));
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
      message.error(e.response?.data?.detail || '加载库存调整单失败');
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

  // 差异原因缺失行（前端提示；后端 hard_rule 终判）
  const missingReasonRows = useMemo(
    () => lineRows.filter((r) => r.inbound_number && !r.reason),
    [lineRows]
  );

  const buildSubUpdates = useCallback(() => lineRows.map((r, i) => {
    const { id, _delete, [LINE_FK]: _p, ...rest } = r;
    const isNew = id == null || String(id).startsWith('new_');
    const fields = { ...rest, line_number: rest.line_number || i + 1 };
    // 调整子表真列映射：格内填 difference(调整差异)；系统量取批次结存 _avail，
    // actual_quantity = system + difference（stock_adjustment_line.actual_quantity NOT NULL，
    // 否则手工建单会 NotNullViolation；reason 必填走 reasonColumn dataIndex='reason'）。
    const sysQty = Number(r._avail ?? r.system_quantity ?? 0);
    const diff = Number(r.difference ?? 0);
    fields.system_quantity = sysQty;
    fields.actual_quantity = sysQty + diff;
    fields.difference = diff;
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
        comment: detail?.id ? '库存调整单更新' : '库存调整单录入',
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
    // 财务确认前提示缺差异原因（后端 hard_rule 终判）
    if ((action.to_state === 'CONFIRM' || action.to_state === 'POSTED') && missingReasonRows.length) {
      message.warning(`有 ${missingReasonRows.length} 行缺差异原因，确认时后端会阻断，请先补齐`);
    }
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
  }, [detail, buildSubUpdates, missingReasonRows, message]);

  const columns = useMemo(() => schemaToColumns(schema?.fields || [], {
    frozen: ['adjustment_number', 'status'],
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
  const hasCountField = useMemo(
    () => headFields.some((f) => f.name === 'inventory_count_id'),
    [headFields]
  );

  // 差异原因 cell 选择器（必填）——注入 BatchLineGrid 的 extraColumns
  const reasonColumn = useMemo(() => ({
    title: '差异原因', dataIndex: 'reason', width: 140, valueType: 'select',
    formItemProps: { rules: [{ required: true, message: '差异原因必填' }] },
    fieldProps: { options: DIFF_REASONS, placeholder: '选差异原因' },
    render: (_, row) => (row.reason
      ? row.reason
      : <span style={{ color: '#b8860b' }}>待填</span>),
  }), []);

  if (schemaReady === false) {
    return (
      <div>
        <PageHeader />
        <Alert
          type="warning" showIcon style={{ marginBottom: 16, borderRadius: 12 }}
          title="功能已就绪 · 待后端开通"
          description="库存调整单 STOCK_ADJUSTMENT 的模型 / 流程定义（盘点差异落账、差异原因必填、过账推金蝶）尚未在后端注册。后端段1b-2 注册 stock_adjustment 表 + 轻量流程后，本页自动点亮（schema/transitions 驱动，不写死状态码）。盘点差异调整也可走盘点页「生成调整单」(WMS counts API) 即时落库。"
        />
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="库存调整单写路径待后端开通" />
      </div>
    );
  }

  return (
    <div>
      <PageHeader />
      <Alert
        type="info" showIcon style={{ marginBottom: 16, borderRadius: 12 }}
        title="一张库存调整单 = 一次盘点差异落账；每行差异原因必填，过账后推金蝶做存货调整入账"
        description="DRAFT 态可改头/明细；提交后经财务确认→过账，过账时引擎调整批次结存+写流水+推金蝶。可关联盘点单带入差异行，亦可手工建单。差异原因未填行在网格标黄，财务确认时后端 hard_rule 终判阻断。"
      />

      <BizTable
        key={reloadKey}
        headerTitle="库存调整单台账"
        rowKey="id"
        columns={columns}
        request={tableRequest}
        rowSelection={false}
        toolBarRender={() => [
          <Button key="new" type="primary" icon={<PlusOutlined />} onClick={openNew}>新建调整单</Button>,
        ]}
        onRow={(row) => ({ onClick: () => openDetail(row, false), style: { cursor: 'pointer' } })}
        scroll={{ x: 'max-content', y: 'calc(100vh - 420px)' }}
      />

      <BizDrawerForm
        open={drawerOpen}
        onOpenChange={setDrawerOpen}
        title={`库存调整单 · ${editMode ? (detail?.id ? '编辑' : '新建') : '详情'}${detail?.adjustment_number ? ` · ${detail.adjustment_number}` : ''}`}
        width={1080}
        onFinish={editMode ? onSave : undefined}
        initialValues={editMode ? (detail || {}) : undefined}
        submitter={editMode ? { searchConfig: { submitText: '保存调整单' } } : false}
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
                  type={a.to_state === 'POSTED' || a.to_state === 'CONFIRM' ? 'primary' : 'default'}
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
            <div style={{ fontWeight: 500, color: '#4e4e4e', margin: '4px 0 8px' }}>单据头（关联盘点单）</div>
            {!hasCountField && (
              <ProFormSelect
                name="inventory_count_id" label="关联盘点单" options={countOptions} showSearch
                fieldProps={{ optionFilterProp: 'label' }}
                tooltip="选关联盘点单后，可由盘点差异行带入调整明细（盘点页亦可一键生成调整）"
              />
            )}
            <MasterFormFields fields={headFields} hidden={HEAD_FORM_HIDDEN} />

            <div style={{ fontWeight: 500, color: '#4e4e4e', margin: '12px 0 8px' }}>
              调整明细（入仓编号 · 调整差异 · 差异原因必填）
            </div>
            {missingReasonRows.length > 0 && (
              <Alert
                type="warning" showIcon style={{ marginBottom: 8, borderRadius: 8 }}
                title={`待补差异原因 ${missingReasonRows.length} 行`}
                description="差异原因未填行已标黄；财务确认时后端 hard_rule 会阻断，请先补齐。"
              />
            )}
            <BatchLineGrid
              value={lineRows} onChange={setLineRows}
              quantityField="difference" quantityLabel="调整差异"
              enforceRemain={false}
              extraColumns={[reasonColumn]}
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
              调整明细 · {lineRows.length} 行
            </div>
            <BatchLineReadonly
              rows={lineRows} qtyKey="difference" qtyLabel="调整差异"
              extraKeys={[['reason', '差异原因']]}
            />
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
        库存调整单
      </h2>
      <span style={{ color: '#777169', fontSize: 13 }}>
        仓储 WMS · 引擎单据 <code>{DOC_TYPE}</code> · 盘点差异 → 推金蝶
      </span>
    </div>
  );
}
