/**
 * MasterDataPage —— 主数据台账（schema 驱动，复用 biz/ 标准壳）
 *
 * 落 UX 律 14：工作台 → 台账(ProTable) → 详情抽屉(不跳页) → 动作按钮。
 *  - 台账：BizTable over /api/query + /api/schema（列由 schema 自动生成；列配置/筛选/密度/批量/冻结列由壳就位）
 *  - 详情/录单：点行 → BizDrawerForm 右滑抽屉看/改（不跳页、不 modal 套 modal）
 *  - 写入：抽屉提交走引擎唯一写入路径 /api/transition（doc_id=null 建档 / 有 id 改档）。
 *    建档/改档表单字段由 schema 自动生成（MasterFormFields），FK→cell 选择器，
 *    客户页内嵌联系人子表（BizEditableTable，对应引擎 customer_contact_line 子表）。
 *
 * ⚠️ 唯一写入路径前置依赖（守"唯一写入路径 Command→Workflow→Domain"，前端不绕底座）：
 *   /api/transition 要求 doc_type 有「活跃的流程定义」(WorkflowDefinition)。
 *   - CUSTOMER / SUPPLIER / MATERIAL / PRODUCT_CODE / PRODUCT_LINE 已挂 __doc_types__ 且段0c
 *     已注册轻量建档状态机（单态 ACTIVE + 自环编辑），本页 writable=true 走建档/改档抽屉；
 *     若状态机未注册引擎返回「没有活跃的流程定义」，本页**如实弹出该错误**、不伪造成功。
 *   - 纯 __queryable__ 字典（warehouse_location / hs_code / unit_of_measure）无 doc_type，
 *     当前无 /api/transition 写路径；本页 writable=false 走只读详情 + TODO 横幅，
 *     待后端 ➕ 建档状态机或 queryable-CRUD 端点（EXT-02-W）后开写。
 *   绝不在前端伪造成功 / 不调非 transition 写端点。
 */

import { useCallback, useMemo, useState } from 'react';
import { Alert, App, Button, Descriptions, Space, Tag } from 'antd';
import { HistoryOutlined } from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import { BizTable, BizDrawerForm, BizEditableTable } from '../../components/biz';
import { query, getSchema, transition } from '../../api';
import MasterFormFields from './MasterFormFields';

// schema field.type → ProTable valueType（仅影响展示/筛选控件）
const TYPE_TO_VALUETYPE = {
  integer: 'digit',
  number: 'digit',
  datetime: 'dateTime',
  date: 'date',
  boolean: 'select',
  json: 'jsonCode',
  text: 'textarea',
  string: 'text',
};

// 状态淡底深字（与 DataExplorer 一致的克制方案）
const STATUS_STYLE = {
  ACTIVE: { bg: '#ebf5ee', color: '#1f8f3a' },
  INACTIVE: { bg: '#f5f5f5', color: '#4e4e4e' },
  DRAFT: { bg: '#f5f2ef', color: '#4e4e4e' },
  PENDING_APPROVAL: { bg: '#fbf5e4', color: '#b8860b' },
  APPROVED: { bg: '#ebf5ee', color: '#1f8f3a' },
  REJECTED: { bg: '#fdecea', color: '#b42318' },
  CANCELLED: { bg: '#fdecea', color: '#b42318' },
};

function StatusPill({ value }) {
  const s = STATUS_STYLE[value] || { bg: '#f5f2ef', color: '#4e4e4e' };
  return (
    <span style={{
      display: 'inline-block', padding: '2px 10px', borderRadius: 4,
      background: s.bg, color: s.color, fontSize: 12, fontWeight: 500, letterSpacing: '0.02em',
    }}>{value}</span>
  );
}

// 系统/审计字段：台账默认隐藏（仍可在抽屉详情看）
const HIDDEN_IN_TABLE = new Set([
  'created_by_id', 'updated_by_id', 'company_id', 'created_at', 'updated_at',
]);
// 布尔列短标签
function boolTag(v) {
  if (v == null) return <span style={{ color: '#bfbbb5' }}>—</span>;
  return v
    ? <Tag style={{ background: '#ebf5ee', color: '#1f8f3a', border: 'none' }}>是</Tag>
    : <Tag style={{ background: '#f5f5f5', color: '#777169', border: 'none' }}>否</Tag>;
}

function renderCell(field, v) {
  if (v == null || v === '') return <span style={{ color: '#bfbbb5' }}>—</span>;
  if (field.name === 'status') return <StatusPill value={v} />;
  if (field.type === 'boolean') return boolTag(v);
  if (field.type === 'number' || field.type === 'integer') {
    return <span style={{ fontFamily: 'ui-monospace, monospace' }}>{Number(v).toLocaleString()}</span>;
  }
  if ((field.type === 'datetime' || field.type === 'date') && typeof v === 'string') {
    return v.slice(0, field.type === 'date' ? 10 : 19).replace('T', ' ');
  }
  if (typeof v === 'object') {
    return <span style={{ color: '#777169' }}>{JSON.stringify(v).slice(0, 60)}</span>;
  }
  return String(v);
}

// 改档时锁定（不可改）的字段：编号列 + 复合唯一锚点（建档后不改外键归属）
const LOCK_ON_EDIT = new Set([
  'customer_number', 'supplier_number', 'product_id', 'supplier_id',
]);

/**
 * @param {string} table          引擎真实表名（必须在 table_map 内，否则 /api/query 404）
 * @param {string} title          页面中文标题
 * @param {string} domain         面包屑域名
 * @param {string} docType        引擎 doc_type（用于 /api/transition 与历史下钻）；无则不开写、不开历史
 * @param {boolean} writable      是否允许抽屉建档/改档（需后端已注册该 doc_type 的状态机）
 * @param {string[]} primaryCols  优先靠前并左冻结的列（如 code/short_name）
 * @param {object} subTable       内嵌子表配置 {table, parentFk, title, columns}（如客户联系人）
 * @param {string} todoNote       台账顶部 TODO 横幅文案（说明引擎现状/扩展点）
 */
export default function MasterDataPage({
  table,
  title,
  domain = '主数据',
  docType,
  writable = false,
  primaryCols = ['code', 'short_name', 'name', 'sku', 'internal_code', 'hs_number', 'uom_code', 'line_name'],
  subTable,
  todoNote,
}) {
  const navigate = useNavigate();
  const { message } = App.useApp();
  const [schema, setSchema] = useState(null);
  const [detail, setDetail] = useState(null);   // 当前抽屉行
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [editMode, setEditMode] = useState(false);  // 抽屉是看(false)还是改/建(true)
  const [subRows, setSubRows] = useState([]);        // 子表行（联系人等）
  const [reloadKey, setReloadKey] = useState(0);     // 提交后刷新台账

  const canWrite = writable && !!docType;

  // /api/query + /api/schema：ProTable request（壳负责查询条/分页/列配置/密度/批量）
  const tableRequest = useCallback(async (params = {}) => {
    // 懒加载 schema（仅首次）
    let sc = schema;
    if (!sc) {
      try {
        const { data } = await getSchema(table);
        sc = data;
        setSchema(data);
      } catch {
        sc = { fields: [] };
      }
    }
    // ProTable 把搜索条字段拍进 params；这里只取通用 search/keyword 与精确 filters
    const { current: _current, pageSize, keyword, ...rest } = params;
    const filters = {};
    const search = keyword || '';
    for (const [k, v] of Object.entries(rest)) {
      if (v == null || v === '') continue;
      if (k === '_timestamp') continue;
      filters[k] = v;
    }
    try {
      const { data } = await query(table, {
        filters,
        search,
        limit: Math.min(pageSize || 20, 100),
      });
      return { data: data.data || [], success: true, total: data.total ?? (data.data || []).length };
    } catch (e) {
      message.error(e.response?.data?.detail || `加载 ${title} 失败`);
      return { data: [], success: false, total: 0 };
    }
  }, [schema, table, title, message]);

  // 打开子表行：建档=空，改档=拉已有子表行
  const loadSubRows = useCallback(async (row) => {
    if (!subTable || !row?.id) { setSubRows([]); return; }
    try {
      const { data } = await query(subTable.table, {
        filters: { [subTable.parentFk]: row.id }, limit: 100,
      });
      setSubRows((data?.data || []).map((r) => ({ ...r })));
    } catch {
      setSubRows([]);
    }
  }, [subTable]);

  const openDetail = useCallback((row, edit = false) => {
    setDetail(row);
    setEditMode(edit && canWrite);
    if (subTable) loadSubRows(row);
    setDrawerOpen(true);
  }, [canWrite, subTable, loadSubRows]);

  const openNew = useCallback(() => {
    setDetail(null);
    setEditMode(true);
    setSubRows([]);
    setDrawerOpen(true);
  }, []);

  // schema → ProTable columns（自动列；主键/系统字段隐藏，code/名称左冻结，操作右冻结）
  const columns = useMemo(() => {
    const fields = (schema?.fields || []).filter(
      (f) => !f.primary_key && !HIDDEN_IN_TABLE.has(f.name)
    );
    // 主列排前 + 左冻结
    const ordered = [
      ...primaryCols.map((n) => fields.find((f) => f.name === n)).filter(Boolean),
      ...fields.filter((f) => !primaryCols.includes(f.name)),
    ];
    const cols = ordered.map((f, idx) => {
      const isPrimary = primaryCols.includes(f.name);
      const isNum = f.type === 'number' || f.type === 'integer';
      return {
        title: f.label || f.name,
        dataIndex: f.name,
        valueType: TYPE_TO_VALUETYPE[f.type] || 'text',
        width: f.name === 'id' ? 70 : isPrimary ? 160 : 150,
        fixed: idx === 0 ? 'left' : undefined,
        ellipsis: f.type === 'text' || f.type === 'string',
        align: isNum ? 'right' : undefined,
        sorter: isNum
          ? (a, b) => (a[f.name] ?? 0) - (b[f.name] ?? 0)
          : (a, b) => String(a[f.name] ?? '').localeCompare(String(b[f.name] ?? '')),
        render: (_, row) => renderCell(f, row[f.name]),
      };
    });
    // 操作列：看详情 / 编辑 +（有 doc_type 时）历史，右冻结
    cols.push({
      title: '操作', dataIndex: '_action', width: canWrite ? 180 : docType ? 130 : 80, fixed: 'right',
      search: false, hideInSetting: true,
      render: (_, row) => (
        <Space size={4}>
          <Button type="link" size="small" onClick={(e) => { e.stopPropagation(); openDetail(row, false); }}>
            详情
          </Button>
          {canWrite && (
            <Button type="link" size="small" onClick={(e) => { e.stopPropagation(); openDetail(row, true); }}>
              编辑
            </Button>
          )}
          {docType && (
            <Button type="link" size="small" icon={<HistoryOutlined />}
              onClick={(e) => { e.stopPropagation(); navigate(`/history/${docType}/${row.id}`); }}>
              历史
            </Button>
          )}
        </Space>
      ),
    });
    return cols;
  }, [schema, primaryCols, docType, canWrite, navigate, openDetail]);

  // 抽屉提交 → 引擎唯一写入路径 /api/transition（仅 canWrite 时启用）
  const onFinish = async (values) => {
    if (!canWrite) return false;
    // 清洗：去掉空字符串（让引擎用默认）、保留 0/false
    const field_updates = {};
    for (const [k, v] of Object.entries(values)) {
      if (v === undefined || v === '') continue;
      field_updates[k] = v;
    }
    // 子表（联系人）→ sub_updates：引擎 _apply_sub_updates 每行一条
    //   { table, id?, fields, parent_fk, _delete? }（新行 id 形如 new_*，视为新增）
    const sub_updates = [];
    if (subTable && subRows.length) {
      subRows.forEach((r, i) => {
        const { id, _tempId, _delete, [subTable.parentFk]: _pfk, ...rest } = r;
        const isNew = id == null || String(id).startsWith('new_');
        const fields = { ...rest, line_number: rest.line_number || i + 1 };
        sub_updates.push(
          isNew
            ? { table: subTable.table, parent_fk: subTable.parentFk, fields }
            : { table: subTable.table, id, _delete: _delete || undefined, fields }
        );
      });
    }
    try {
      const { data } = await transition({
        doc_type: docType,
        doc_id: detail?.id ?? null,
        field_updates,
        sub_updates,
        comment: detail?.id ? '主数据更新' : '主数据建档',
      });
      if (data?.success === false) {
        message.error(data.error || data.detail || '保存失败（引擎拒绝）');
        return false;
      }
      message.success(detail?.id ? '已更新' : '已建档');
      setDrawerOpen(false);
      setReloadKey((k) => k + 1);
      return true;
    } catch (e) {
      message.error(e.response?.data?.detail || '保存失败（引擎写路径未就绪）');
      return false;
    }
  };

  // 抽屉详情字段（schema 全字段，含系统字段，只读展示）
  const detailFields = useMemo(
    () => (schema?.fields || []).filter((f) => f.name !== 'id'),
    [schema]
  );
  // 表单字段（建档/改档）：改档时锁定编号 + 复合唯一锚点
  const formHidden = useMemo(
    () => (detail?.id ? [...LOCK_ON_EDIT] : []),
    [detail]
  );
  // 表单初值（改档时回填已有值）
  const formInitial = useMemo(() => detail || {}, [detail]);

  return (
    <div>
      <div style={{ marginBottom: 16 }}>
        <h2 style={{ fontSize: 26, fontWeight: 300, letterSpacing: '-0.01em', color: '#000', margin: 0, lineHeight: 1.2 }}>
          {title}
        </h2>
        <span style={{ color: '#777169', fontSize: 13 }}>{domain} · 引擎表 <code>{table}</code></span>
      </div>

      {todoNote && (
        <Alert
          type="warning" showIcon style={{ marginBottom: 16, borderRadius: 12 }}
          title={canWrite ? '写入走引擎唯一路径 /api/transition' : '写入路径待后端开通'}
          description={todoNote}
        />
      )}

      <BizTable
        key={reloadKey}
        headerTitle={title}
        rowKey="id"
        columns={columns}
        request={tableRequest}
        rowSelection={{}}
        tableAlertOptionRender={({ selectedRowKeys }) => (
          <Space size={16}>
            <span style={{ color: '#777169' }}>已选 {selectedRowKeys.length} 项</span>
            <Button type="link" size="small" disabled title="批量停用待写路径开通（EXT-02-W）">批量停用</Button>
            <Button type="link" size="small" disabled title="批量导出待 P 段">导出</Button>
          </Space>
        )}
        toolBarRender={() => [
          canWrite ? (
            <Button key="new" type="primary" onClick={openNew}>新建</Button>
          ) : (
            <Button key="new" type="primary" disabled title="建档写路径待后端开通（EXT-02-W）">新建</Button>
          ),
        ]}
        onRow={(row) => ({ onClick: () => openDetail(row, false), style: { cursor: 'pointer' } })}
        scroll={{ x: 'max-content', y: 'calc(100vh - 360px)' }}
      />

      {/* 详情/录单抽屉（不跳页）：editMode 走 /api/transition 建档/改档；否则只读详情 */}
      <BizDrawerForm
        open={drawerOpen}
        onOpenChange={setDrawerOpen}
        title={`${title} · ${editMode ? (detail?.id ? '编辑' : '新建') : '详情'}`}
        width={subTable ? 720 : 560}
        onFinish={editMode ? onFinish : undefined}
        initialValues={editMode ? formInitial : undefined}
        submitter={editMode ? undefined : false}
      >
        {editMode ? (
          <>
            <MasterFormFields fields={schema?.fields || []} hidden={formHidden} />
            {subTable && (
              <div style={{ marginTop: 8 }}>
                <div style={{ fontWeight: 500, color: '#4e4e4e', margin: '8px 0' }}>{subTable.title}</div>
                <BizEditableTable
                  value={subRows}
                  onChange={setSubRows}
                  rowKey="id"
                  columns={subTable.columns}
                  recordCreatorProps={{ record: () => ({ id: `new_${Date.now()}` }) }}
                />
              </div>
            )}
          </>
        ) : (
          <>
            <Descriptions column={1} size="small" bordered
              styles={{ label: { width: 160, color: '#777169' } }}>
              {detailFields.map((f) => (
                <Descriptions.Item key={f.name} label={f.label || f.name}>
                  {renderCell(f, detail?.[f.name])}
                </Descriptions.Item>
              ))}
            </Descriptions>
            {subTable && subRows.length > 0 && (
              <div style={{ marginTop: 16 }}>
                <div style={{ fontWeight: 500, color: '#4e4e4e', marginBottom: 8 }}>{subTable.title}</div>
                <BizEditableTable
                  value={subRows} onChange={() => {}}
                  rowKey="id" columns={subTable.columns}
                  recordCreatorProps={false}
                  editable={{ editableKeys: [], type: 'multiple' }}
                />
              </div>
            )}
            {!canWrite && (
              <Alert
                type="info" showIcon style={{ marginTop: 16, borderRadius: 10 }}
                title="只读详情"
                description="该主数据的建档/改档写路径（引擎状态机）尚未在后端注册，当前仅支持查看。开写需后端 ➕ 主数据建档状态机（EXT-02-W）。"
              />
            )}
            {canWrite && (
              <Button type="primary" style={{ marginTop: 16 }} onClick={() => setEditMode(true)}>
                编辑
              </Button>
            )}
          </>
        )}
      </BizDrawerForm>
    </div>
  );
}
