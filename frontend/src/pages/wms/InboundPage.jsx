/**
 * InboundPage —— 入库收货（GOODS_RECEIPT 单据，PRD 03a-1 / 03a-2）
 *
 * 落 UX 律 14：工作台 → 台账(BizTable) → 详情抽屉(BizDrawerForm，不跳页) → 动作按钮(走 /api/transition)。
 *   - 台账：BizTable over /api/query goods_receipt（冻结 入库单号/状态 列；status 药丸 PENDING/PA_REVIEW/STOCKED_IN/CANCELLED）
 *   - 抽屉：头 BizDrawerForm（schema 驱动表单） + 明细 InboundLineGrid（goods_receipt_line 网格，扫码/复制/拆行/粘贴）
 *   - 动作：顶部按钮由 /api/transitions 按 doc_type+当前状态过滤生成（提交PA审核 / 审核通过入库 / 退回 / 取消）
 *           — 一律走引擎唯一写入路径 execute_transition，失败如实弹错、不伪造成功。
 *   - 批量：选中 N 行 → 打印入仓编号标签（62×29mm 预览 + 待打印机对接占位）
 *
 * ⚠️ 引擎实况对齐：seed 的 GOODS_RECEIPT 状态码 = PENDING / PA_REVIEW / STOCKED_IN / CANCELLED
 *    （非 PRD 文案的 DRAFT/PENDING_REVIEW），本页用引擎真实 code。头部 inbound_type/supplier_id/
 *    customer_id/reviewer_id 等 PRD ➕ 列后端补齐后会经 /api/schema 自动出现在表单（不写死）。
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Alert, App, Button, Descriptions, Space,
} from 'antd';
import { HistoryOutlined, PrinterOutlined, PlusOutlined } from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import { BizTable, BizDrawerForm } from '../../components/biz';
import { query, getSchema, transition, getTransitions } from '../../api';
import MasterFormFields from '../master/MasterFormFields';
import InboundLineGrid from './InboundLineGrid';
import { schemaToColumns, renderCellByField } from './wmsHelpers';
import { StatusPill, LabelPrintModal } from './wmsShared';

const DOC_TYPE = 'GOODS_RECEIPT';
const TABLE = 'goods_receipt';
const LINE_TABLE = 'goods_receipt_line';

// 入库单状态过滤候选（引擎真实 code）
const STATUS_ENUM = [
  { text: 'PENDING 仓库收货录入', value: 'PENDING' },
  { text: 'PA_REVIEW 待 PA 审核', value: 'PA_REVIEW' },
  { text: 'STOCKED_IN 已入库', value: 'STOCKED_IN' },
  { text: 'CANCELLED 已取消', value: 'CANCELLED' },
];

// 头部表单不录入的列（引擎自动填/系统列）
const HEAD_FORM_HIDDEN = ['receipt_number', 'status'];

export default function InboundPage() {
  const navigate = useNavigate();
  const { message } = App.useApp();
  const [schema, setSchema] = useState(null);
  const [allActions, setAllActions] = useState([]);   // /api/transitions（全量）
  const [detail, setDetail] = useState(null);         // 当前抽屉单据头
  const [lineRows, setLineRows] = useState([]);       // 明细子表行
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [editMode, setEditMode] = useState(false);    // 抽屉是看(false)还是建/改(true)
  const [busy, setBusy] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);
  const [labelModal, setLabelModal] = useState({ open: false, codes: [] });

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
      message.error(e.response?.data?.detail || '加载入库单失败');
      return { data: [], success: false, total: 0 };
    }
  }, [schema, message]);

  // 加载可用动作（按 doc_type）
  useEffect(() => {
    getTransitions().then(({ data }) => {
      setAllActions((data || []).filter((a) => a.doc_type === DOC_TYPE));
    }).catch(() => setAllActions([]));
  }, []);

  // 打开详情：拉明细子表
  const loadLines = useCallback(async (headId) => {
    if (!headId) { setLineRows([]); return; }
    try {
      const { data } = await query(LINE_TABLE, { filters: { goods_receipt_id: headId }, limit: 200 });
      setLineRows((data?.data || []).map((r) => ({ ...r })));
    } catch { setLineRows([]); }
  }, []);

  const openDetail = useCallback((row, edit = false) => {
    setDetail(row);
    // 仅 PENDING 态可改头/明细；其余只读（PA_REVIEW 由审批中心动作推进）
    setEditMode(edit && (!row || row.status === 'PENDING'));
    loadLines(row?.id);
    setDrawerOpen(true);
  }, [loadLines]);

  const openNew = useCallback(() => {
    setDetail(null); setEditMode(true); setLineRows([]); setDrawerOpen(true);
  }, []);

  // 当前单据在当前状态下可执行的动作
  const docActions = useMemo(() => {
    if (!detail?.status) return [];
    return allActions.filter((a) => a.from_state === detail.status);
  }, [allActions, detail]);

  // 子表行 → sub_updates（新行 id=new_* 视为新增；已删行 _delete）
  const buildSubUpdates = useCallback(() => {
    return lineRows.map((r, i) => {
      const { id, _delete, goods_receipt_id: _g, ...rest } = r;
      const isNew = id == null || String(id).startsWith('new_');
      const fields = { ...rest, line_number: rest.line_number || i + 1 };
      // 去掉空字符串与展示派生字段
      Object.keys(fields).forEach((k) => {
        if (fields[k] === '' || fields[k] === undefined) delete fields[k];
        if (k.startsWith('_')) delete fields[k];
      });
      return isNew
        ? { table: LINE_TABLE, parent_fk: 'goods_receipt_id', fields }
        : { table: LINE_TABLE, id, _delete: _delete || undefined, fields };
    });
  }, [lineRows]);

  // 保存头+明细（建档/改档；不切状态）
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
        comment: detail?.id ? '入库单更新' : '入库单录入',
      });
      if (data?.success === false) {
        message.error(data.error || data.detail || '保存失败（引擎拒绝）');
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

  // 推进状态（提交PA审核 / 审核通过 / 退回 / 取消）— 顶部动作按钮
  const runAction = useCallback(async (action) => {
    if (!detail?.id) { message.warning('请先保存单据再推进'); return; }
    setBusy(true);
    try {
      // 推进前先把明细当前编辑落库（PENDING 态可改）
      const sub_updates = detail.status === 'PENDING' ? buildSubUpdates() : [];
      const { data } = await transition({
        doc_type: DOC_TYPE, doc_id: detail.id,
        to_state: action.to_state, action_label: action.action_label,
        field_updates: {}, sub_updates,
        comment: action.action_label,
      });
      if (data?.success === false) {
        if (data.rule_failures) {
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

  // 台账列（schema 驱动；冻结 单号/状态）
  const columns = useMemo(() => schemaToColumns(schema?.fields || [], {
    frozen: ['receipt_number'],
    statusFilter: ['status'],
    statusEnum: { status: STATUS_ENUM },
    actionCol: {
      title: '操作', dataIndex: '_action', width: 150, fixed: 'right', search: false, hideInSetting: true,
      render: (_, row) => (
        <Space size={4}>
          <Button type="link" size="small"
            onClick={(e) => { e.stopPropagation(); openDetail(row, false); }}>详情</Button>
          {row.status === 'PENDING' && (
            <Button type="link" size="small"
              onClick={(e) => { e.stopPropagation(); openDetail(row, true); }}>编辑</Button>
          )}
          <Button type="link" size="small" icon={<HistoryOutlined />}
            onClick={(e) => { e.stopPropagation(); navigate(`/history/${DOC_TYPE}/${row.id}`); }}>历史</Button>
        </Space>
      ),
    },
  }), [schema, navigate, openDetail]);

  // 头部表单字段（schema 驱动；隐藏自动列）
  const headFields = useMemo(() => schema?.fields || [], [schema]);
  // 详情只读字段
  const detailFields = useMemo(
    () => headFields.filter((f) => f.name !== 'id'),
    [headFields]
  );

  return (
    <div>
      <div style={{ marginBottom: 16 }}>
        <h2 style={{ fontSize: 26, fontWeight: 300, letterSpacing: '-0.01em', color: '#000', margin: 0, lineHeight: 1.2 }}>
          入库收货
        </h2>
        <span style={{ color: '#777169', fontSize: 13 }}>仓储 WMS · 引擎单据 <code>{DOC_TYPE}</code></span>
      </div>

      <Alert
        type="info" showIcon style={{ marginBottom: 16, borderRadius: 12 }}
        title="一张入库单 = 一次同运单送达的收货；明细子表（進庫詳細資料）为真相源"
        description="录入态 PENDING 可改头/明细；提交后转 PA_REVIEW 由 PA 在审批中心审核，通过 STOCKED_IN 自动生成库存批次+流水。头部入库类型/供应商/审核 PA 等扩展列由后端补齐后经 schema 自动出现（PRD E4）。"
      />

      <BizTable
        key={reloadKey}
        headerTitle="入库单台账"
        rowKey="id"
        columns={columns}
        request={tableRequest}
        rowSelection={{}}
        tableAlertOptionRender={({ selectedRows }) => (
          <Space size={12}>
            <span style={{ color: '#777169' }}>已选 {selectedRows.length} 单</span>
            <Button type="link" size="small" icon={<PrinterOutlined />}
              onClick={async () => {
                // 取选中单据的明细入仓编号
                const ids = selectedRows.map((r) => r.id);
                const all = [];
                for (const id of ids) {
                  const { data } = await query(LINE_TABLE, { filters: { goods_receipt_id: id }, limit: 200 });
                  (data?.data || []).forEach((l) => { if (l.inbound_number) all.push(l.inbound_number); });
                }
                setLabelModal({ open: true, codes: all });
              }}>
              打印标签
            </Button>
          </Space>
        )}
        toolBarRender={() => [
          <Button key="new" type="primary" icon={<PlusOutlined />} onClick={openNew}>新建入库单</Button>,
        ]}
        onRow={(row) => ({ onClick: () => openDetail(row, false), style: { cursor: 'pointer' } })}
        scroll={{ x: 'max-content', y: 'calc(100vh - 420px)' }}
      />

      {/* 详情/录单抽屉（不跳页） */}
      <BizDrawerForm
        open={drawerOpen}
        onOpenChange={setDrawerOpen}
        title={`入库单 · ${editMode ? (detail?.id ? '编辑' : '新建') : '详情'}${detail?.receipt_number ? ` · ${detail.receipt_number}` : ''}`}
        width={1080}
        onFinish={editMode ? onSave : undefined}
        initialValues={editMode ? (detail || {}) : undefined}
        submitter={editMode ? { searchConfig: { submitText: '保存入库单' } } : false}
      >
        {/* 顶部动作按钮（走 /api/transition） */}
        {detail?.id && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12, flexWrap: 'wrap' }}>
            <StatusPill value={detail.status} />
            {docActions.length === 0 ? (
              <span style={{ color: '#bfbbb5', fontSize: 12 }}>当前状态无可执行动作（或非本角色权限）</span>
            ) : docActions.map((a) => {
              const danger = a.to_state === 'CANCELLED' || a.to_state === 'PENDING';
              return (
                <Button
                  key={`${a.action_label}-${a.to_state}`}
                  size="small"
                  type={a.to_state === 'STOCKED_IN' || a.to_state === 'PA_REVIEW' ? 'primary' : 'default'}
                  danger={danger}
                  loading={busy}
                  onClick={() => runAction(a)}
                >
                  {a.action_label}
                </Button>
              );
            })}
            <span style={{ flex: 1 }} />
            <Button size="small" icon={<PrinterOutlined />}
              onClick={() => setLabelModal({
                open: true,
                codes: lineRows.map((l) => l.inbound_number).filter(Boolean),
              })}>打印本单标签</Button>
          </div>
        )}

        {editMode ? (
          <>
            <div style={{ fontWeight: 500, color: '#4e4e4e', margin: '4px 0 8px' }}>单据头</div>
            <MasterFormFields fields={headFields} hidden={detail?.id ? HEAD_FORM_HIDDEN : HEAD_FORM_HIDDEN} />
            <div style={{ fontWeight: 500, color: '#4e4e4e', margin: '12px 0 8px' }}>
              進庫詳細資料（明细子表 · 网格录入）
            </div>
            <InboundLineGrid value={lineRows} onChange={setLineRows} />
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
              進庫詳細資料 · {lineRows.length} 行
            </div>
            <InboundLineReadonly rows={lineRows} />
          </>
        )}
      </BizDrawerForm>

      <LabelPrintModal
        open={labelModal.open}
        onClose={() => setLabelModal({ open: false, codes: [] })}
        codes={labelModal.codes}
      />
    </div>
  );
}

/** 明细只读简表（详情态展示，关键列） */
function InboundLineReadonly({ rows = [] }) {
  if (!rows.length) return <span style={{ color: '#bfbbb5' }}>无明细</span>;
  const KEYS = [
    ['inbound_number', '入仓编号'], ['material_id', '型号'], ['serial_lot_number', 'SN/LOT'],
    ['actual_quantity', '数量'], ['uom', '单位'], ['production_date', '生产日期'],
    ['location_code', '库位'], ['remark', 'REMARK'],
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
              {KEYS.map(([k]) => {
                const isUnified = k === 'remark' && typeof r[k] === 'string' && r[k].includes('統一包裝');
                return (
                  <td key={k} style={{
                    padding: '6px 10px', whiteSpace: 'nowrap',
                    textAlign: k === 'actual_quantity' ? 'right' : 'left',
                    fontFamily: k === 'actual_quantity' ? 'ui-monospace, monospace' : undefined,
                    color: isUnified ? '#b42318' : '#000', fontWeight: isUnified ? 500 : 400,
                  }}>
                    {r[k] == null || r[k] === '' ? <span style={{ color: '#bfbbb5' }}>—</span> : String(r[k])}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
