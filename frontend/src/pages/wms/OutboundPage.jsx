/**
 * OutboundPage —— 出库发货（SHIPMENT 单据，PRD 03b 页面 1·2·4·8）⭐
 *
 * 落 UX 律 14：工作台 → 台账(BizTable) → 详情抽屉(BizDrawerForm，不跳页) → 动作按钮(走 /api/transition)。
 *   - 台账：BizTable over /api/query shipment_request（冻结 出库单号/客户?/状态；status 药丸 10 态）
 *   - 抽屉：头 BizDrawerForm（schema 驱动：SO/客户/INV#/送货形式/运单…）+ 拣货明细 ShipmentLineGrid
 *           （入仓编号 cell 选择器[本公司+可售+结存>0+串货匹配]→带出 型号/SN/供应商/性质/原厂报备客户/结存）
 *   - 动作：顶部按钮由 /api/transitions 按 doc_type=SHIPMENT + 当前状态 + 本角色过滤生成
 *           （提交财务审批 / 财务放行 / 完成制标并拣货复检 / 确认出库 / 退回… 由引擎边定义生成）
 *           — 一律走引擎唯一写入路径 execute_transition，失败如实弹错、不伪造成功。
 *   - 出库异常标记（页面 8「只记不判」）：异常类型/描述/发现阶段，落 notes 结构化前缀（引擎无独立异常列，
 *     不另造重单据/不改核心模型；后端补异常列后改读 schema）。
 *
 * ⚠️ 引擎实况对齐（已勘 seed phase1_workflows）：SHIPMENT 状态码 =
 *    DRAFT / FINANCE_APPROVAL / EXCEPTION_APPROVAL / PACKING_LABELING / PICKING_RECHECK /
 *    SALES_OUTBOUND / CUSTOMER_RECEIVED / RETURN_REQUESTED / CANCELLED。
 *    业务序（seed 已对齐 PRD）：DRAFT→分箱拣货 PACKING_LABELING→互检 PICKING_RECHECK（LOGISTICS）→
 *    财务放行 FINANCE_APPROVAL（FINANCE）→出库 SALES_OUTBOUND；两关均在出库前。出库扣库存/写流水/推票
 *    effect 挂在 →SALES_OUTBOUND 边（apply_shipment_costs/stock_out），命名 effect 在财务放行边。
 *    串货校验由后端 validate_shipment(to_state=SALES_OUTBOUND) 终判；本页前端先提示。本页用引擎真实 code，不写死。
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { Alert, App, Button, Descriptions, Space, Tabs } from 'antd';
import { HistoryOutlined, PlusOutlined, WarningOutlined } from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import {
  ProFormSelect, ProFormTextArea,
} from '@ant-design/pro-components';
import { BizTable, BizDrawerForm } from '../../components/biz';
import { query, getSchema, transition, getTransitions } from '../../api';
import MasterFormFields from '../master/MasterFormFields';
import ShipmentLineGrid from './ShipmentLineGrid';
import OutboundSummary from './OutboundSummary';
import { schemaToColumns, renderCellByField } from './wmsHelpers';
import { StatusPill } from './wmsShared';
import { displayName } from '../master/fkOptions';

const DOC_TYPE = 'SHIPMENT';
const TABLE = 'shipment_request';
const LINE_TABLE = 'shipment_line';

// 出库单状态过滤候选（引擎真实 code，10 态）
const STATUS_ENUM = [
  { text: 'DRAFT 发货通知', value: 'DRAFT' },
  { text: 'FINANCE_APPROVAL 财务审批', value: 'FINANCE_APPROVAL' },
  { text: 'EXCEPTION_APPROVAL 例外审批', value: 'EXCEPTION_APPROVAL' },
  { text: 'PACKING_LABELING 包装制标', value: 'PACKING_LABELING' },
  { text: 'PICKING_RECHECK 拣货复检（互检）', value: 'PICKING_RECHECK' },
  { text: 'SALES_OUTBOUND 销售出库', value: 'SALES_OUTBOUND' },
  { text: 'CUSTOMER_RECEIVED 客户已收', value: 'CUSTOMER_RECEIVED' },
  { text: 'RETURN_REQUESTED 客户退货', value: 'RETURN_REQUESTED' },
  { text: 'CANCELLED 已取消', value: 'CANCELLED' },
];

// 仅 DRAFT 态可改头/明细（其余态字段由各边 editable_fields 控制，经审批中心推进）
const EDITABLE_STATES = new Set(['DRAFT']);

// 头部表单不录入的系统/自动列
const HEAD_FORM_HIDDEN = ['shipment_number', 'status', 'requested_by_id', 'approved_by_id'];

// 出库异常类型（页面 8「只记不判」标记，落 notes 前缀）
const EXCEPTION_TYPES = [
  { label: '扫码漏扫', value: '扫码漏扫' },
  { label: 'SN缺位', value: 'SN缺位' },
  { label: '日期录错', value: '日期录错' },
  { label: '一包多PO', value: '一包多PO' },
  { label: '标签错', value: '标签错' },
  { label: '数量不符', value: '数量不符' },
];
const EXCEPTION_STAGES = [
  { label: '入库收尾', value: '入库收尾' },
  { label: '出库互检', value: '出库互检' },
  { label: '盘点', value: '盘点' },
];

export default function OutboundPage() {
  const navigate = useNavigate();
  const { message } = App.useApp();
  const [schema, setSchema] = useState(null);
  const [allActions, setAllActions] = useState([]);
  const [detail, setDetail] = useState(null);
  const [lineRows, setLineRows] = useState([]);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [editMode, setEditMode] = useState(false);
  const [busy, setBusy] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);
  const [drawerTab, setDrawerTab] = useState('lines');
  const [exception, setException] = useState({ type: undefined, stage: undefined, desc: '' });
  const [custOptions, setCustOptions] = useState([]);
  const [headCustomerId, setHeadCustomerId] = useState(undefined);

  // 客户候选（串货隔离要本单客户 → 经 SO 带出，亦提供直选兜底）
  useEffect(() => {
    query('customer', { limit: 200 }).then(({ data }) => {
      setCustOptions((data?.data || []).map((c) => ({ label: displayName(c), value: c.id })));
    }).catch(() => setCustOptions([]));
  }, []);

  // 台账：/api/query + /api/schema
  const tableRequest = useCallback(async (params = {}) => {
    let sc = schema;
    if (!sc) {
      try { const { data } = await getSchema(TABLE); sc = data; setSchema(data); }
      catch { sc = { fields: [] }; }
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
      message.error(e.response?.data?.detail || '加载出库单失败');
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
      const { data } = await query(LINE_TABLE, { filters: { shipment_id: headId }, limit: 200 });
      // 载入：后端 photo_refs(JSONB 数组) → UI 照片槽 _photo（首张），保证编辑不丢已挂照片
      setLineRows((data?.data || []).map((r) => ({
        ...r,
        _photo: Array.isArray(r.photo_refs) && r.photo_refs.length ? r.photo_refs[0] : (r._photo || undefined),
      })));
    } catch { setLineRows([]); }
  }, []);

  const openDetail = useCallback((row, edit = false) => {
    setDetail(row);
    setEditMode(edit && (!row || EDITABLE_STATES.has(row.status)));
    setHeadCustomerId(undefined);
    setException({ type: undefined, stage: undefined, desc: '' });
    setDrawerTab('lines');
    loadLines(row?.id);
    setDrawerOpen(true);
  }, [loadLines]);

  const openNew = useCallback(() => {
    setDetail(null); setEditMode(true); setLineRows([]);
    setHeadCustomerId(undefined);
    setException({ type: undefined, stage: undefined, desc: '' });
    setDrawerTab('lines');
    setDrawerOpen(true);
  }, []);

  // 当前单据在当前状态下可执行的动作（按 from_state；角色已在 /api/transitions 服务端过滤）
  const docActions = useMemo(() => {
    if (!detail?.status) return [];
    return allActions.filter((a) => a.from_state === detail.status);
  }, [allActions, detail]);

  // 串货命中行（前端提示，后端 validate_shipment 终判）
  const crossoverRows = useMemo(() => lineRows.filter((r) => {
    const rc = r._reported_customer_id;
    return headCustomerId && rc != null && Number(rc) !== Number(headCustomerId);
  }), [lineRows, headCustomerId]);

  // 超结存行
  const overRows = useMemo(() => lineRows.filter((r) => (
    r._avail != null && Number(r.quantity || 0) > Number(r._avail)
  )), [lineRows]);

  // 缺照片行（互检前提示）
  const missingPhotoRows = useMemo(
    () => lineRows.filter((r) => r.inbound_number && !r._photo),
    [lineRows]
  );

  // 子表行 → sub_updates（剥展示派生 _ 列；新行 new_* 视为新增）
  const buildSubUpdates = useCallback(() => lineRows.map((r, i) => {
    const { id, _delete, shipment_id: _s, ...rest } = r;
    const isNew = id == null || String(id).startsWith('new_');
    const fields = { ...rest, line_number: rest.line_number || i + 1 };
    // 照片引用：UI 槽 _photo → 落库列 photo_refs(JSONB 数组)；须在剥下划线键之前固化，
    // 否则照片永不落库、经 UI 出库到互检会被后端 hard_rule all(line.photo_refs) 拦死。
    fields.photo_refs = r._photo ? [r._photo] : [];
    Object.keys(fields).forEach((k) => {
      if (k.startsWith('_')) delete fields[k];
      if (fields[k] === '' || fields[k] === undefined) delete fields[k];
    });
    return isNew
      ? { table: LINE_TABLE, parent_fk: 'shipment_id', fields }
      : { table: LINE_TABLE, id, _delete: _delete || undefined, fields };
  }), [lineRows]);

  // 异常标记 → notes 结构化前缀（只记不判；不另造重单据）
  const mergeExceptionToNotes = useCallback((baseNotes) => {
    if (!exception.type) return baseNotes;
    const tag = `【出库异常·只记不判】类型:${exception.type}`
      + (exception.stage ? ` 阶段:${exception.stage}` : '')
      + (exception.desc ? ` 描述:${exception.desc}` : '');
    return baseNotes ? `${tag}\n${baseNotes}` : tag;
  }, [exception]);

  // 保存头+明细（建档/改档；不切状态）
  const onSave = useCallback(async (values) => {
    const field_updates = {};
    for (const [k, v] of Object.entries(values)) {
      if (v === undefined || v === '') continue;
      field_updates[k] = v;
    }
    if (exception.type) field_updates.notes = mergeExceptionToNotes(values.notes || '');
    try {
      const { data } = await transition({
        doc_type: DOC_TYPE, doc_id: detail?.id ?? null,
        field_updates, sub_updates: buildSubUpdates(),
        comment: detail?.id ? '出库单更新' : '出库单录入',
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
  }, [detail, buildSubUpdates, exception, mergeExceptionToNotes, message]);

  // 推进状态（顶部动作按钮，走引擎唯一写入路径）
  const runAction = useCallback(async (action) => {
    if (!detail?.id) { message.warning('请先保存单据再推进'); return; }
    // 互检（推进到 PICKING_RECHECK）前提示缺照片（拍照留证，不硬拦，前端提示）
    if (action.to_state === 'PICKING_RECHECK' && missingPhotoRows.length) {
      message.warning(`有 ${missingPhotoRows.length} 行缺每包照片引用，建议互检前补齐（拍照留证）`);
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
  }, [detail, buildSubUpdates, missingPhotoRows, message]);

  // 台账列（schema 驱动；冻结 出库单号/状态）
  const columns = useMemo(() => schemaToColumns(schema?.fields || [], {
    frozen: ['shipment_number', 'status'],
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

  // 出库单关键动作主按钮高亮（财务放行 / 确认出库 / 互检推进）
  const primaryStates = new Set(['PACKING_LABELING', 'PICKING_RECHECK', 'SALES_OUTBOUND']);

  return (
    <div>
      <div style={{ marginBottom: 16 }}>
        <h2 style={{ fontSize: 26, fontWeight: 300, letterSpacing: '-0.01em', color: '#000', margin: 0, lineHeight: 1.2 }}>
          出库发货
        </h2>
        <span style={{ color: '#777169', fontSize: 13 }}>仓储 WMS · 引擎单据 <code>{DOC_TYPE}</code> · 出库单 PD 号 + 拣货批次子表 + 两道关</span>
      </div>

      <Alert
        type="info" showIcon style={{ marginBottom: 16, borderRadius: 12 }}
        title="一张出库单 = 一次发货；拣货批次明细（按入仓编号出货）为真相源，互检★与财务放行★两道关"
        description="DRAFT 态可改头/明细；提交后经 财务审批→包装制标→拣货复检(互检)→确认出库，出库扣库存/写流水/推金蝶已挂在确认出库一步。入仓编号选择器只列「本公司·可售·结存>0·串货匹配」批次，选中自动带出型号/SN/性质/原厂报备客户/结存。两道关在工作台「我的审批」收件箱可批。"
      />

      <BizTable
        key={reloadKey}
        headerTitle="出库单台账"
        rowKey="id"
        columns={columns}
        request={tableRequest}
        rowSelection={false}
        toolBarRender={() => [
          <Button key="new" type="primary" icon={<PlusOutlined />} onClick={openNew}>新建出库单</Button>,
        ]}
        onRow={(row) => ({ onClick: () => openDetail(row, false), style: { cursor: 'pointer' } })}
        scroll={{ x: 'max-content', y: 'calc(100vh - 420px)' }}
      />

      {/* 详情/录单抽屉（不跳页） */}
      <BizDrawerForm
        open={drawerOpen}
        onOpenChange={setDrawerOpen}
        title={`出库单 · ${editMode ? (detail?.id ? '编辑' : '新建') : '详情'}${detail?.shipment_number ? ` · ${detail.shipment_number}` : ''}`}
        width={1120}
        onFinish={editMode ? onSave : undefined}
        initialValues={editMode ? (detail || {}) : undefined}
        submitter={editMode ? { searchConfig: { submitText: '保存出库单' } } : false}
        onValuesChange={(changed) => {
          if ('customer_id' in changed) setHeadCustomerId(changed.customer_id);
        }}
      >
        {/* 顶部动作按钮（走 /api/transition）+ 状态药丸 */}
        {detail?.id && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12, flexWrap: 'wrap' }}>
            <StatusPill value={detail.status} />
            {docActions.length === 0 ? (
              <span style={{ color: '#bfbbb5', fontSize: 12 }}>当前状态无可执行动作（或非本角色权限）</span>
            ) : docActions.map((a) => {
              const danger = a.to_state === 'CANCELLED' || a.to_state === 'EXCEPTION_APPROVAL'
                || a.to_state === 'RETURN_REQUESTED';
              return (
                <Button
                  key={`${a.action_label}-${a.to_state}`}
                  size="small"
                  type={primaryStates.has(a.to_state) ? 'primary' : 'default'}
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
            {/* 客户直选（串货隔离过滤源；schema 头无 customer_id 时由此显式提供本单客户） */}
            <ProFormSelect
              name="_head_customer_id" label="本单客户（串货隔离过滤源）"
              options={custOptions} showSearch
              fieldProps={{
                optionFilterProp: 'label',
                onChange: (v) => setHeadCustomerId(v),
              }}
              tooltip="选客户后，拣货明细入仓编号候选只列原厂报备客户=本单客户(或为空)的批次"
            />
            <MasterFormFields fields={headFields} hidden={HEAD_FORM_HIDDEN} />

            <div style={{ fontWeight: 500, color: '#4e4e4e', margin: '12px 0 8px' }}>
              拣货明细（按入仓编号出货 · 网格录入）
            </div>
            {(crossoverRows.length > 0 || overRows.length > 0) && (
              <Alert
                type="warning" showIcon style={{ marginBottom: 8, borderRadius: 8 }}
                title={`待修正：串货命中 ${crossoverRows.length} 行 · 超结存 ${overRows.length} 行`}
                description="串货行/超结存行已在网格标红；确认出库时后端 validate_shipment 会终判阻断，请先修正。"
              />
            )}
            <ShipmentLineGrid value={lineRows} onChange={setLineRows} customerId={headCustomerId} />

            {/* 出库异常登记（页面 8「只记不判」标记 → notes 前缀） */}
            <div style={{ fontWeight: 500, color: '#4e4e4e', margin: '16px 0 8px' }}>
              <WarningOutlined style={{ color: '#b8860b', marginInlineEnd: 6 }} />
              出库异常标记（只记不判 · 不另开重单据）
            </div>
            <Space wrap size={12} style={{ width: '100%' }}>
              <ProFormSelect
                name="_ex_type" label="异常类型" options={EXCEPTION_TYPES}
                fieldProps={{ style: { minWidth: 160 }, onChange: (v) => setException((s) => ({ ...s, type: v })) }}
              />
              <ProFormSelect
                name="_ex_stage" label="发现阶段" options={EXCEPTION_STAGES}
                fieldProps={{ style: { minWidth: 140 }, onChange: (v) => setException((s) => ({ ...s, stage: v })) }}
              />
            </Space>
            <ProFormTextArea
              name="_ex_desc" label="异常描述"
              fieldProps={{
                autoSize: { minRows: 1, maxRows: 3 },
                onChange: (e) => setException((s) => ({ ...s, desc: e.target.value })),
              }}
              tooltip="保存时作为结构化前缀写入单据 notes，留痕可查；不阻断流程"
            />
          </>
        ) : (
          <Tabs
            activeKey={drawerTab}
            onChange={setDrawerTab}
            items={[
              {
                key: 'lines',
                label: '出库明细',
                children: (
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
                      拣货明细 · {lineRows.length} 行
                    </div>
                    <ShipmentLineReadonly rows={lineRows} />
                  </>
                ),
              },
              {
                key: 'summary',
                label: '基本出库（按型号/性质汇总）',
                children: <OutboundSummary rows={lineRows} mode="model" />,
              },
              {
                key: 'pivot',
                label: '入仓编号·出库总数量（透视）',
                children: <OutboundSummary rows={lineRows} mode="inbound" />,
              },
            ]}
          />
        )}
      </BizDrawerForm>
    </div>
  );
}

/** 拣货明细只读简表（详情态展示，关键列） */
function ShipmentLineReadonly({ rows = [] }) {
  if (!rows.length) return <span style={{ color: '#bfbbb5' }}>无明细</span>;
  const KEYS = [
    ['inbound_number', '入仓编号'], ['serial_lot_number', 'SN/LOT'], ['goods_nature', '性质'],
    ['quantity', '出库数量'], ['uom', '单位'], ['carton_number', '箱号'],
    ['invoice_number', 'INV#'], ['delivery_method', '送货形式'],
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
                  textAlign: k === 'quantity' ? 'right' : 'left',
                  fontFamily: k === 'quantity' ? 'ui-monospace, monospace' : undefined,
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
