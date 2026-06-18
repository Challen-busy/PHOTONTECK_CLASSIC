/**
 * AuxDimensionPage —— 辅助核算维度 + 维度数据维护（finance-gl wave-3 配账基础资料）
 *
 * 主从两区（同页不跳页）：
 *  ┌ 上区：辅助核算维度类别 auxiliary_dimension（source_type=CUSTOMER/SUPPLIER/EMPLOYEE/DEPT/PROJECT）
 *  │      —— 直接复用主数据通用壳 MasterDataPage（schema 驱动台账 → 抽屉 → /api/transition，doc_type=AUX_DIMENSION）
 *  └ 下区：选中维度下的「维度数据」auxiliary_dimension_value（该维度的具体值，如各部门 / 各项目；parent_id 自引用树）
 *         —— 复用同一套 biz 壳（BizTable + BizDrawerForm + MasterFormFields），按选中维度 dimension_id 过滤其值
 *            （query 带 filter: { dimension_id }），建档时把 dimension_id 钉死为选中维度；
 *            写入同样走引擎唯一写入路径 /api/transition，doc_type=AUX_DIMENSION_VALUE。
 *
 * ★ 为何下区不直接再套一个 MasterDataPage：MasterDataPage 不提供「按固定外键过滤 + 建档预置外键」入口，
 *    而本页要求“按选中维度过滤其值并在该维度下建档”。故下区用 MasterDataPage 同款 biz 积木（BizTable/
 *    BizDrawerForm/MasterFormFields/transition）组合，零改动复用壳与唯一写入范式，符合主数据 CRUD 范式。
 *
 * ⚠️ AUX_DIMENSION / AUX_DIMENSION_VALUE 须各有「活跃 WorkflowDefinition」（seed 单态 ACTIVE + 自环编辑）才可写；
 *    缺活跃流程时引擎如实返回「没有活跃的流程定义」，本页不伪造成功。
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { Alert, App, Button, Descriptions, Empty, Select, Space, Tag } from 'antd';
import { HistoryOutlined } from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import MasterDataPage from '../../master/MasterDataPage';
import { BizTable, BizDrawerForm } from '../../../components/biz';
import MasterFormFields from '../../master/MasterFormFields';
import { query, getSchema, transition } from '../../../api';

const VALUE_TABLE = 'auxiliary_dimension_value';
const VALUE_DOC_TYPE = 'AUX_DIMENSION_VALUE';

// 维度类别来源类型枚举（对齐 models.AuxiliaryDimension.source_type）
const SOURCE_TYPE_LABEL = {
  CUSTOMER: '客户', SUPPLIER: '供应商', EMPLOYEE: '职员', DEPT: '部门', PROJECT: '项目',
};

// 下区台账隐藏的系统/审计字段（与 MasterDataPage 一致）
const HIDDEN_IN_TABLE = new Set([
  'created_by_id', 'updated_by_id', 'company_id', 'created_at', 'updated_at', 'dimension_id',
]);
const VALUE_PRIMARY_COLS = ['code', 'name'];

function boolTag(v) {
  if (v == null) return <span style={{ color: '#bfbbb5' }}>—</span>;
  return v
    ? <Tag style={{ background: '#ebf5ee', color: '#1f8f3a', border: 'none' }}>是</Tag>
    : <Tag style={{ background: '#f5f5f5', color: '#777169', border: 'none' }}>否</Tag>;
}

function renderCell(field, v) {
  if (v == null || v === '') return <span style={{ color: '#bfbbb5' }}>—</span>;
  if (field.type === 'boolean') return boolTag(v);
  if (field.type === 'number' || field.type === 'integer') {
    return <span style={{ fontFamily: 'ui-monospace, monospace' }}>{Number(v).toLocaleString()}</span>;
  }
  return String(v);
}

/** 下区：选中维度的「维度数据」(auxiliary_dimension_value)，按 dimension_id 过滤 + 在该维度下建档 */
function DimensionValuePanel({ dimension }) {
  const navigate = useNavigate();
  const { message } = App.useApp();
  const [schema, setSchema] = useState(null);
  const [detail, setDetail] = useState(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [editMode, setEditMode] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);

  const dimensionId = dimension?.id ?? null;
  const canWrite = !!dimensionId;

  const tableRequest = useCallback(async (params = {}) => {
    if (!dimensionId) return { data: [], success: true, total: 0 };
    let sc = schema;
    if (!sc) {
      try { const { data } = await getSchema(VALUE_TABLE); sc = data; setSchema(data); }
      catch { sc = { fields: [] }; }
    }
    const { current: _c, pageSize, keyword, ...rest } = params;
    const filters = { dimension_id: dimensionId };  // ★ 按选中维度过滤其值
    for (const [k, v] of Object.entries(rest)) {
      if (v == null || v === '' || k === '_timestamp') continue;
      filters[k] = v;
    }
    try {
      const { data } = await query(VALUE_TABLE, {
        filters, search: keyword || '', order_by: 'code',
        limit: Math.min(pageSize || 20, 100),
      });
      return { data: data.data || [], success: true, total: data.total ?? (data.data || []).length };
    } catch (e) {
      message.error(e.response?.data?.detail || '加载维度数据失败');
      return { data: [], success: false, total: 0 };
    }
  }, [dimensionId, schema, message]);

  const openDetail = useCallback((row, edit) => {
    setDetail(row);
    setEditMode(edit && canWrite);
    setDrawerOpen(true);
  }, [canWrite]);

  const openNew = useCallback(() => { setDetail(null); setEditMode(true); setDrawerOpen(true); }, []);

  const columns = useMemo(() => {
    const fields = (schema?.fields || []).filter(
      (f) => !f.primary_key && !HIDDEN_IN_TABLE.has(f.name)
    );
    const ordered = [
      ...VALUE_PRIMARY_COLS.map((n) => fields.find((f) => f.name === n)).filter(Boolean),
      ...fields.filter((f) => !VALUE_PRIMARY_COLS.includes(f.name)),
    ];
    const cols = ordered.map((f, idx) => ({
      title: f.label || f.name,
      dataIndex: f.name,
      width: VALUE_PRIMARY_COLS.includes(f.name) ? 180 : 150,
      fixed: idx === 0 ? 'left' : undefined,
      ellipsis: f.type === 'text' || f.type === 'string',
      render: (_, row) => renderCell(f, row[f.name]),
    }));
    cols.push({
      title: '操作', dataIndex: '_action', width: 180, fixed: 'right',
      search: false, hideInSetting: true,
      render: (_, row) => (
        <Space size={4}>
          <Button type="link" size="small" onClick={(e) => { e.stopPropagation(); openDetail(row, false); }}>详情</Button>
          <Button type="link" size="small" onClick={(e) => { e.stopPropagation(); openDetail(row, true); }}>编辑</Button>
          <Button type="link" size="small" icon={<HistoryOutlined />}
            onClick={(e) => { e.stopPropagation(); navigate(`/history/${VALUE_DOC_TYPE}/${row.id}`); }}>历史</Button>
        </Space>
      ),
    });
    return cols;
  }, [schema, navigate, openDetail]);

  // 建档时把 dimension_id 钉死为当前选中维度（不让用户改成别的维度）
  const formHidden = useMemo(() => ['dimension_id'], []);
  const formInitial = useMemo(
    () => (detail?.id ? detail : { dimension_id: dimensionId }),
    [detail, dimensionId]
  );

  const onFinish = async (values) => {
    if (!canWrite) return false;
    const field_updates = { dimension_id: dimensionId };  // 钉死归属维度
    for (const [k, v] of Object.entries(values)) {
      if (v === undefined || v === '') continue;
      field_updates[k] = v;
    }
    try {
      const { data } = await transition({
        doc_type: VALUE_DOC_TYPE,
        doc_id: detail?.id ?? null,
        field_updates,
        sub_updates: [],
        comment: detail?.id ? '维度数据更新' : '维度数据建档',
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

  const detailFields = useMemo(
    () => (schema?.fields || []).filter((f) => f.name !== 'id'),
    [schema]
  );

  if (!dimension) {
    return (
      <Empty
        style={{ marginTop: 48 }}
        description="先在上区选择一个核算维度，再维护其下的维度数据"
      />
    );
  }

  return (
    <div>
      <div style={{ marginBottom: 12, color: '#777169', fontSize: 13 }}>
        当前维度：<b style={{ color: '#000' }}>{dimension.code} {dimension.name}</b>
        {dimension.source_type && (
          <Tag style={{ marginLeft: 8, background: '#f5f2ef', color: '#777169', border: 'none' }}>
            {SOURCE_TYPE_LABEL[dimension.source_type] || dimension.source_type}
          </Tag>
        )}
        <span> · 引擎表 <code>{VALUE_TABLE}</code></span>
      </div>

      <BizTable
        key={`${dimensionId}-${reloadKey}`}
        headerTitle="维度数据（该维度下具体值）"
        rowKey="id"
        columns={columns}
        request={tableRequest}
        search={false}
        toolBarRender={() => [
          <Button key="new" type="primary" onClick={openNew}>新建</Button>,
        ]}
        onRow={(row) => ({ onClick: () => openDetail(row, false), style: { cursor: 'pointer' } })}
        scroll={{ x: 'max-content', y: 360 }}
      />

      <BizDrawerForm
        open={drawerOpen}
        onOpenChange={setDrawerOpen}
        title={`维度数据 · ${editMode ? (detail?.id ? '编辑' : '新建') : '详情'}`}
        width={520}
        onFinish={editMode ? onFinish : undefined}
        initialValues={editMode ? formInitial : undefined}
        submitter={editMode ? undefined : false}
      >
        {editMode ? (
          <MasterFormFields fields={schema?.fields || []} hidden={formHidden} />
        ) : (
          <>
            <Descriptions column={1} size="small" bordered styles={{ label: { width: 160, color: '#777169' } }}>
              {detailFields.map((f) => (
                <Descriptions.Item key={f.name} label={f.label || f.name}>
                  {renderCell(f, detail?.[f.name])}
                </Descriptions.Item>
              ))}
            </Descriptions>
            <Button type="primary" style={{ marginTop: 16 }} onClick={() => setEditMode(true)}>编辑</Button>
          </>
        )}
      </BizDrawerForm>
    </div>
  );
}

export default function AuxDimensionPage() {
  const { message } = App.useApp();
  const [dimensions, setDimensions] = useState([]);
  const [selectedId, setSelectedId] = useState(null);

  // 拉维度类别供下区选择器（上区 MasterDataPage 管增删改；这里只读取作为下区过滤入口）。
  // 直接在 effect 内异步取数 + alive 守卫（对齐 VoucherEntryPage 范式）；默认选中第一项用函数式更新读旧值。
  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const { data } = await query('auxiliary_dimension', { order_by: 'code', limit: 200 });
        if (!alive) return;
        const rows = data?.data || [];
        setDimensions(rows);
        setSelectedId((cur) => (cur == null && rows.length ? rows[0].id : cur));
      } catch (e) {
        if (alive) message.error(e.response?.data?.detail || '加载核算维度失败');
      }
    })();
    return () => { alive = false; };
  }, [message]);

  const selectedDimension = useMemo(
    () => dimensions.find((d) => d.id === selectedId) || null,
    [dimensions, selectedId]
  );

  return (
    <div>
      <div style={{ marginBottom: 16 }}>
        <h2 style={{ fontSize: 26, fontWeight: 300, letterSpacing: '-0.01em', color: '#000', margin: 0, lineHeight: 1.2 }}>
          辅助核算维度
        </h2>
        <span style={{ color: '#777169', fontSize: 13 }}>
          财务 / 总账 · 基础资料 · 维度类别 + 维度数据（主从两区）
        </span>
      </div>

      {/* 上区：维度类别 —— 直接复用主数据通用壳 MasterDataPage（schema 驱动 + /api/transition 唯一写入） */}
      <MasterDataPage
        table="auxiliary_dimension"
        title="核算维度类别"
        domain="财务 / 总账 · 基础资料"
        docType="AUX_DIMENSION"
        writable
        primaryCols={['code', 'name']}
        todoNote="辅助核算维度类别（source_type=客户 / 供应商 / 职员 / 部门 / 项目）建档 / 改档走 /api/transition（AUX_DIMENSION 状态机，单态 ACTIVE + 自环编辑）；其下具体值在下区「维度数据」(auxiliary_dimension_value) 维护。若引擎报「没有活跃的流程定义」，需后端为 AUX_DIMENSION 种最小 WorkflowDefinition（参照 CUSTOMER/SUPPLIER）。"
      />

      {/* 下区：维度数据（按选中维度过滤 + 在该维度下建档），复用 biz 壳 + /api/transition 唯一写入 */}
      <div style={{ marginTop: 28, paddingTop: 20, borderTop: '1px solid #efece8' }}>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 12, marginBottom: 12 }}>
          <h3 style={{ fontSize: 18, fontWeight: 400, color: '#000', margin: 0 }}>维度数据</h3>
          <Select
            style={{ minWidth: 280 }}
            placeholder="选择核算维度"
            value={selectedId ?? undefined}
            onChange={setSelectedId}
            showSearch
            optionFilterProp="label"
            options={dimensions.map((d) => ({
              value: d.id,
              label: `${d.code} ${d.name}${d.source_type ? `（${SOURCE_TYPE_LABEL[d.source_type] || d.source_type}）` : ''}`,
            }))}
            notFoundContent={
              <Alert
                type="info" showIcon
                title="还没有核算维度"
                description="先在上区新建核算维度类别，再来此维护其下具体值。"
              />
            }
          />
        </div>
        <DimensionValuePanel dimension={selectedDimension} />
      </div>
    </div>
  );
}
