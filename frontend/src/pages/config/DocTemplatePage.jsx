/**
 * DocTemplatePage —— 单据模板配置（PRD 09 §9.2 单据可配模板子系统）
 *
 * 落 UX 律 14：台账(ProTable) → 编辑抽屉(不跳页) → 动作；字段集走 BizEditableTable 网格。
 *  - 台账：BizTable over /api/query doc_template（PL/INV/送货单，按客户×公司，customer 空=公司通用）
 *  - 编辑：BizDrawerForm 头部存抬头/区域/盖章·回签标志，字段子表 doc_template_field_line
 *    （字段标题→来源字段 + 本地/出口切换 variant + 渲条码）。
 *  - 写入走引擎唯一路径 /api/transition（doc_type=DOC_TEMPLATE，子表 sub_updates）。
 *
 * ⚠️ 守"唯一写入路径"：render_html 由后端 render_doc_template 命令按白名单服务端拼装
 *   （custom_html 逃生舱 + 转义，PRD §9.2 XSS 约束），前端只配模板结构，不在前端拼 HTML。
 *   DOC_TEMPLATE 状态机未注册时引擎如实报错，不伪造成功。
 */
import { useCallback, useMemo, useState } from 'react';
import { Alert, App, Button, Tag } from 'antd';
import {
  ProFormText, ProFormSelect, ProFormSwitch, ProFormTextArea,
} from '@ant-design/pro-components';
import { BizTable, BizDrawerForm, BizEditableTable } from '../../components/biz';
import { query, transition } from '../../api';
import { loadFkOptions } from '../master/fkOptions';

const DOC_KIND = [
  { label: 'PL 装箱单', value: 'PL' }, { label: 'INV 商业发票', value: 'INV' },
  { label: '客户送货单', value: 'DN_CUST' }, { label: '货代托运单', value: 'DN_FWD' },
];
const REGION = [{ label: 'HK', value: 'HK' }, { label: '内地', value: 'CN' }];

function docKindName(v) {
  return DOC_KIND.find((o) => o.value === v)?.label || v || '—';
}

export default function DocTemplatePage() {
  const { message } = App.useApp();
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [fieldRows, setFieldRows] = useState([]);
  const [custOptions, setCustOptions] = useState([]);
  const [reloadKey, setReloadKey] = useState(0);

  const tableRequest = useCallback(async (params = {}) => {
    const { keyword } = params;
    try {
      const { data } = await query('doc_template', { search: keyword || '', limit: 100 });
      return { data: data.data || [], success: true, total: data.total ?? (data.data || []).length };
    } catch (e) {
      message.error(e.response?.data?.detail || '加载单据模板失败');
      return { data: [], success: false, total: 0 };
    }
  }, [message]);

  const loadFieldRows = useCallback(async (tpl) => {
    if (!tpl?.id) { setFieldRows([]); return; }
    try {
      const { data } = await query('doc_template_field_line', {
        filters: { doc_template_id: tpl.id }, limit: 100,
      });
      setFieldRows((data?.data || []).map((r) => ({ ...r })));
    } catch { setFieldRows([]); }
  }, []);

  const openEdit = useCallback(async (tpl) => {
    setEditing(tpl);
    setCustOptions(await loadFkOptions('customer', 'customer_id'));
    await loadFieldRows(tpl);
    setOpen(true);
  }, [loadFieldRows]);

  const openNew = useCallback(async () => {
    setEditing(null);
    setCustOptions(await loadFkOptions('customer', 'customer_id'));
    setFieldRows([]);
    setOpen(true);
  }, []);

  const columns = useMemo(() => [
    { title: '模板名', dataIndex: 'name', fixed: 'left', width: 200,
      render: (v) => <span style={{ fontWeight: 500 }}>{v || '—'}</span> },
    { title: '单据类型', dataIndex: 'doc_kind', width: 130, search: false,
      render: (v) => <Tag style={{ background: '#f5f2ef', color: '#4e4e4e', border: 'none' }}>{docKindName(v)}</Tag> },
    { title: '区域', dataIndex: 'region', width: 90, search: false,
      render: (v) => v === 'CN' ? '内地' : v || '—' },
    { title: '盖章版', dataIndex: 'needs_stamp', width: 90, search: false,
      render: (v) => v ? <Tag color="default">需盖章</Tag> : <span style={{ color: '#bfbbb5' }}>—</span> },
    { title: '回签', dataIndex: 'needs_countersign', width: 90, search: false,
      render: (v) => v ? <Tag color="default">需回签</Tag> : <span style={{ color: '#bfbbb5' }}>—</span> },
    { title: '状态', dataIndex: 'is_active', width: 90, search: false,
      render: (v) => v === false
        ? <Tag style={{ background: '#f5f5f5', color: '#777169', border: 'none' }}>停用</Tag>
        : <Tag style={{ background: '#ebf5ee', color: '#1f8f3a', border: 'none' }}>启用</Tag> },
    { title: '操作', dataIndex: '_action', width: 90, fixed: 'right', search: false, hideInSetting: true,
      render: (_, row) => (
        <Button type="link" size="small" onClick={(e) => { e.stopPropagation(); openEdit(row); }}>编辑</Button>
      ) },
  ], [openEdit]);

  const fieldColumns = useMemo(() => [
    { title: '字段标题', dataIndex: 'doc_field_title', width: 180,
      formItemProps: { rules: [{ required: true, message: '必填' }] },
      tooltip: '单据上字段显示名，如 DESCRIPTION OF GOODS / QUANTITY' },
    { title: '来源字段', dataIndex: 'source_field', width: 160,
      tooltip: '出库/发票/合同字段' },
    { title: '本地/出口切换', dataIndex: 'is_variant_field', width: 130, valueType: 'switch',
      tooltip: '如发票号↔报关单号、单价↔净重，按区域切换' },
    { title: '本地取值', dataIndex: 'variant_local', width: 140 },
    { title: '出口取值', dataIndex: 'variant_export', width: 140 },
    { title: '渲条码', dataIndex: 'render_as_barcode', width: 90, valueType: 'switch' },
  ], []);

  const onFinish = async (values) => {
    const sub_updates = fieldRows.map((r, i) => {
      const { id, _tempId, ...rest } = r;
      const isNew = id == null || String(id).startsWith('new_');
      const fields = { ...rest, line_number: rest.line_number || i + 1 };
      return isNew
        ? { table: 'doc_template_field_line', parent_fk: 'doc_template_id', fields }
        : { table: 'doc_template_field_line', id, fields };
    });
    try {
      const { data } = await transition({
        doc_type: 'DOC_TEMPLATE',
        doc_id: editing?.id ?? null,
        field_updates: values,
        sub_updates,
        comment: editing?.id ? '单据模板更新' : '单据模板建档',
      });
      if (data?.success === false) {
        message.error(data.error || data.detail || '保存失败（引擎拒绝）');
        return false;
      }
      message.success(editing?.id ? '已更新' : '已新建');
      setOpen(false);
      setReloadKey((k) => k + 1);
      return true;
    } catch (e) {
      message.error(e.response?.data?.detail || '保存失败（DOC_TEMPLATE 写路径未就绪）');
      return false;
    }
  };

  return (
    <div>
      <div style={{ marginBottom: 16 }}>
        <h2 style={{ fontSize: 26, fontWeight: 300, letterSpacing: '-0.01em', color: '#000', margin: 0, lineHeight: 1.2 }}>
          单据模板
        </h2>
        <span style={{ color: '#777169', fontSize: 13 }}>配置 / 模板 · PL / INV / 送货单（按客户×公司，盖章/回签）</span>
      </div>

      <Alert
        type="info" showIcon style={{ marginBottom: 16, borderRadius: 12 }}
        title="单据渲染：按客户/区域灌数据，盖章版导出占位"
        description="本页配置单据骨架（字段集 / 本地↔出口字段切换 / 盖章·回签标志）；渲染产物 render_html 由后端 render_doc_template 命令服务端按白名单拼装（XSS 约束，PRD 09 §9.2）。盖章版导出 Word/PDF→打印盖章→扫描回传为占位。写入走引擎唯一路径 /api/transition（DOC_TEMPLATE）。"
      />

      <BizTable
        key={reloadKey}
        headerTitle="单据模板"
        rowKey="id"
        columns={columns}
        request={tableRequest}
        rowSelection={false}
        toolBarRender={() => [
          <Button key="new" type="primary" onClick={openNew}>新建单据模板</Button>,
        ]}
        onRow={(row) => ({ onClick: () => openEdit(row), style: { cursor: 'pointer' } })}
        scroll={{ x: 'max-content', y: 'calc(100vh - 400px)' }}
      />

      <BizDrawerForm
        open={open}
        onOpenChange={setOpen}
        title={`单据模板 · ${editing?.id ? '编辑' : '新建'}`}
        width={920}
        onFinish={onFinish}
        initialValues={editing || { doc_kind: 'PL', region: 'HK', needs_stamp: false, needs_countersign: false, is_active: true }}
      >
        <ProFormText name="name" label="模板名" rules={[{ required: true, message: '请填写模板名' }]} />
        <ProFormSelect name="doc_kind" label="单据类型" options={DOC_KIND} rules={[{ required: true }]} />
        <ProFormSelect
          name="customer_id" label="客户（空=公司通用）" options={custOptions} showSearch allowClear
          fieldProps={{ optionFilterProp: 'label' }}
        />
        <ProFormSelect name="region" label="区域" options={REGION} />
        <ProFormText name="header_title" label="发货抬头" />
        <ProFormTextArea name="bank_block" label="银行块" fieldProps={{ autoSize: { minRows: 2, maxRows: 4 } }}
          tooltip="保理/OSA 账户块（如 Innolight/Eoptolink）" />
        <ProFormSwitch name="needs_stamp" label="盖章版" />
        <ProFormSwitch name="needs_countersign" label="回签流转" />
        <ProFormSwitch name="is_active" label="启用" />

        <div style={{ fontWeight: 500, color: '#4e4e4e', margin: '12px 0 8px' }}>
          字段集（字段标题 → 来源字段；本地/出口可切换）
        </div>
        <BizEditableTable
          value={fieldRows}
          onChange={setFieldRows}
          rowKey="id"
          columns={fieldColumns}
          recordCreatorProps={{ record: () => ({ id: `new_${Date.now()}`, is_variant_field: false, render_as_barcode: false }) }}
        />
      </BizDrawerForm>
    </div>
  );
}
