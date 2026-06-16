/**
 * MasterDataPage —— 主数据台账（schema 驱动，复用 biz/ 标准壳）
 *
 * 落 UX 律 14：工作台 → 台账(ProTable) → 详情抽屉(不跳页) → 动作按钮。
 *  - 台账：BizTable over /api/query + /api/schema（列由 schema 自动生成；列配置/筛选/密度/批量/冻结列由壳就位）
 *  - 详情：点行 → BizDrawerForm 右滑抽屉看/改（不跳页、不 modal 套 modal）
 *  - 写入：抽屉提交走引擎唯一写入路径 /api/transition（doc_id=null 建档 / 有 id 改档）。
 *
 * ⚠️ 引擎现状（段0a 未铺写路径，前端不绕底座 / 不造端点 —— 守"唯一写入路径")：
 *   主数据表（customer/supplier/material/warehouse_location）当前**未注册 WorkflowDefinition**，
 *   /api/transition 会回"流程不存在"。本页据此把抽屉降级为**只读详情**（writable=false 时不渲染提交器），
 *   并在台账顶部标 TODO，待后端 ➕ 主数据建档状态机（EXT-02-W，必入 engineFlags）后开写。
 *   绝不在前端伪造成功 / 不调非 transition 写端点。
 */

import { useCallback, useMemo, useState } from 'react';
import { Alert, App, Button, Descriptions, Space, Tag } from 'antd';
import { HistoryOutlined } from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import { BizTable, BizDrawerForm } from '../../components/biz';
import { query, getSchema, transition } from '../../api';

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

/**
 * @param {string} table          引擎真实表名（必须在 table_map 内，否则 /api/query 404）
 * @param {string} title          页面中文标题
 * @param {string} docType        引擎 doc_type（用于 /api/transition 与历史下钻）；无则不开写、不开历史
 * @param {boolean} writable      是否允许抽屉建档/改档（默认 false：等后端铺写路径）
 * @param {string[]} primaryCols  优先靠前并左冻结的列（如 code/short_name）
 * @param {string} todoNote       台账顶部 TODO 横幅文案（说明引擎现状/扩展点）
 */
export default function MasterDataPage({
  table,
  title,
  domain = '主数据',
  docType,
  writable = false,
  primaryCols = ['code', 'short_name', 'name', 'sku'],
  todoNote,
}) {
  const navigate = useNavigate();
  const { message } = App.useApp();
  const [schema, setSchema] = useState(null);
  const [detail, setDetail] = useState(null);   // 当前抽屉行
  const [drawerOpen, setDrawerOpen] = useState(false);

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

  const openDetail = useCallback((row) => { setDetail(row); setDrawerOpen(true); }, []);

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
    // 操作列：看详情 +（有 doc_type 时）历史，右冻结
    cols.push({
      title: '操作', dataIndex: '_action', width: docType ? 130 : 80, fixed: 'right',
      search: false, hideInSetting: true,
      render: (_, row) => (
        <Space size={4}>
          <Button type="link" size="small" onClick={(e) => { e.stopPropagation(); openDetail(row); }}>
            详情
          </Button>
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
  }, [schema, primaryCols, docType, navigate, openDetail]);

  // 抽屉提交 → 引擎唯一写入路径 /api/transition（仅 writable 时启用）
  const onFinish = async (values) => {
    if (!writable || !docType) return false;
    try {
      const { data } = await transition({
        doc_type: docType,
        doc_id: detail?.id ?? null,
        field_updates: values,
        comment: detail?.id ? '主数据更新' : '主数据建档',
      });
      if (data?.success === false) {
        message.error(data.error || data.detail || '保存失败（引擎拒绝）');
        return false;
      }
      message.success(detail?.id ? '已更新' : '已建档');
      setDrawerOpen(false);
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
          message="写入路径待后端开通"
          description={todoNote}
        />
      )}

      <BizTable
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
          writable && docType ? (
            <Button key="new" type="primary" onClick={() => { setDetail(null); setDrawerOpen(true); }}>
              新建
            </Button>
          ) : (
            <Button key="new" type="primary" disabled title="建档写路径待后端开通（EXT-02-W）">新建</Button>
          ),
        ]}
        onRow={(row) => ({ onClick: () => openDetail(row), style: { cursor: 'pointer' } })}
        scroll={{ x: 'max-content', y: 'calc(100vh - 360px)' }}
      />

      {/* 详情抽屉（不跳页）：当前为只读详情；writable+docType 时可由 onFinish 走 /api/transition */}
      <BizDrawerForm
        open={drawerOpen}
        onOpenChange={setDrawerOpen}
        title={`${title} · ${detail?.id ? '详情' : '新建'}`}
        width={560}
        onFinish={onFinish}
        submitter={writable && docType ? undefined : false}
      >
        <Descriptions column={1} size="small" bordered
          styles={{ label: { width: 160, color: '#777169' } }}>
          {detailFields.map((f) => (
            <Descriptions.Item key={f.name} label={f.label || f.name}>
              {renderCell(f, detail?.[f.name])}
            </Descriptions.Item>
          ))}
        </Descriptions>
        {(!writable || !docType) && (
          <Alert
            type="info" showIcon style={{ marginTop: 16, borderRadius: 10 }}
            message="只读详情"
            description="该主数据的建档/改档写路径（引擎状态机）尚未在后端注册，当前仅支持查看。开写需后端 ➕ 主数据建档状态机（EXT-02-W）。"
          />
        )}
      </BizDrawerForm>
    </div>
  );
}
