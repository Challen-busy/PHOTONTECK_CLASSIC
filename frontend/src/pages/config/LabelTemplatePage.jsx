/**
 * LabelTemplatePage —— 标签模板配置（PRD 09 §9.1 标签可配模板子系统）
 *
 * 落 UX 律 14：工作台 → 台账(ProTable) → 编辑抽屉(不跳页) → 动作按钮；录单走 BizEditableTable 网格。
 *  - 台账：BizTable over /api/query label_template（按 客户×公司×标签类型 一条）
 *  - 编辑：BizDrawerForm 右滑，头部存尺寸 + 二维码拼接规则（分隔符 + 进二维码字段序），
 *    字段映射子表 BizEditableTable（label_field_line：标签字段→来源字段 + 顺序 + 渲条码/进二维码）。
 *  - 写入走引擎唯一路径 /api/transition（doc_type=LABEL_TEMPLATE，子表 sub_updates）。
 *
 * ⚠️ 守"唯一写入路径"：模板头/子表写一律经 execute_transition；二维码拼装/条码渲染是后端
 *   build_label_payload 命令的事（custom_html 逃生舱 + 服务端转义，PRD §9.1 XSS 约束），
 *   前端只配规则、不在前端拼 HTML。LABEL_TEMPLATE 状态机未注册时引擎如实报错，不伪造成功。
 *
 * 标签打印：14 律「留口子前端占位」——"功能已就绪·待真实打印机对接"可见占位，不假装能打。
 */
import { useCallback, useMemo, useState } from 'react';
import { Alert, App, Button, Space, Tag, Tooltip } from 'antd';
import { PrinterOutlined } from '@ant-design/icons';
import {
  ProFormText, ProFormSelect, ProFormSwitch,
} from '@ant-design/pro-components';
import { BizTable, BizDrawerForm, BizEditableTable } from '../../components/biz';
import { query, transition } from '../../api';
import { loadFkOptions } from '../master/fkOptions';

const LABEL_TYPE = [
  { label: '包装1', value: 'PKG1' }, { label: '包装2', value: 'PKG2' },
  { label: '外箱', value: 'OUTER' }, { label: '公司外箱', value: 'COMPANY_OUTER' },
];
const QR_SEP = [
  { label: '无', value: '' }, { label: '& 与', value: '&' }, { label: '; 分号', value: ';' },
  { label: '+ 加号', value: '+' }, { label: ', 逗号', value: ',' }, { label: '_ 下划线', value: '_' },
];
const SOURCE_TYPE = [
  { label: '出库登记', value: 'OUTBOUND' }, { label: '入库批次', value: 'INBOUND' },
  { label: '邮件附件手填', value: 'EMAIL' }, { label: '客户系统', value: 'CUSTOMER_SYS' },
  { label: '派生公式', value: 'DERIVED' }, { label: '常量', value: 'CONST' },
];
// 出库表字段候选（PRD §9.1 数据来源参考，出库表字段参考 sheet）
const SOURCE_FIELD = [
  '入倉編號', '出庫單號', '出庫日期', '型號', 'SN/LOT#', '供應商', '性質', '數量',
  '貨物數量單位', '客戶', '運單號', '送貨形式', 'INV#', '箱號', '原產地', 'HS#',
  '報關費', '運費', '出庫重量(Kgs)',
].map((v) => ({ label: v, value: v }));

function labelTypeName(v) {
  return LABEL_TYPE.find((o) => o.value === v)?.label || v || '—';
}

export default function LabelTemplatePage() {
  const { message } = App.useApp();
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState(null);   // 当前编辑模板（null=新建）
  const [fieldRows, setFieldRows] = useState([]);  // 字段映射子表行
  const [custOptions, setCustOptions] = useState([]);
  const [reloadKey, setReloadKey] = useState(0);

  const tableRequest = useCallback(async (params = {}) => {
    const { keyword } = params;
    try {
      const { data } = await query('label_template', { search: keyword || '', limit: 100 });
      return { data: data.data || [], success: true, total: data.total ?? (data.data || []).length };
    } catch (e) {
      message.error(e.response?.data?.detail || '加载标签模板失败');
      return { data: [], success: false, total: 0 };
    }
  }, [message]);

  const loadFieldRows = useCallback(async (tpl) => {
    if (!tpl?.id) { setFieldRows([]); return; }
    try {
      const { data } = await query('label_field_line', {
        filters: { label_template_id: tpl.id }, limit: 100,
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
    { title: '标签类型', dataIndex: 'label_type', width: 120, search: false,
      render: (v) => <Tag style={{ background: '#f5f2ef', color: '#4e4e4e', border: 'none' }}>{labelTypeName(v)}</Tag> },
    { title: '尺寸(mm)', dataIndex: 'size_mm', width: 110, search: false,
      render: (v) => v || <span style={{ color: '#bfbbb5' }}>—</span> },
    { title: '二维码分隔符', dataIndex: 'qr_separator', width: 120, search: false,
      render: (v) => v ? <code>{v}</code> : <span style={{ color: '#bfbbb5' }}>无</span> },
    { title: '进二维码字段', dataIndex: 'qr_field_order', width: 220, search: false,
      render: (v) => Array.isArray(v) && v.length
        ? <span style={{ color: '#777169', fontSize: 12 }}>{v.join(' · ')}</span>
        : <span style={{ color: '#bfbbb5' }}>—</span> },
    { title: '状态', dataIndex: 'is_active', width: 90, search: false,
      render: (v) => v === false
        ? <Tag style={{ background: '#f5f5f5', color: '#777169', border: 'none' }}>停用</Tag>
        : <Tag style={{ background: '#ebf5ee', color: '#1f8f3a', border: 'none' }}>启用</Tag> },
    { title: '操作', dataIndex: '_action', width: 170, fixed: 'right', search: false, hideInSetting: true,
      render: (_, row) => (
        <Space size={4}>
          <Button type="link" size="small" onClick={(e) => { e.stopPropagation(); openEdit(row); }}>编辑</Button>
          <Tooltip title="标签渲染/打印：功能已就绪，待真实打印机（BarTender 类）对接">
            <Button type="link" size="small" icon={<PrinterOutlined />} disabled>打印</Button>
          </Tooltip>
        </Space>
      ) },
  ], [openEdit]);

  // 字段映射子表列（网格录入，BizEditableTable）
  const fieldColumns = useMemo(() => [
    { title: '标签字段名', dataIndex: 'label_field_title', width: 150,
      formItemProps: { rules: [{ required: true, message: '必填' }] } },
    { title: '来源类型', dataIndex: 'source_type', width: 130, valueType: 'select',
      fieldProps: { options: SOURCE_TYPE } },
    { title: '来源字段', dataIndex: 'source_field', width: 160, valueType: 'select',
      fieldProps: { options: SOURCE_FIELD, showSearch: true, mode: 'tags' } },
    { title: '派生公式', dataIndex: 'derive_expr', width: 150,
      tooltip: '来源类型=派生公式时填，如「合同号前5位」' },
    { title: '常量值', dataIndex: 'const_value', width: 130 },
    { title: '进二维码', dataIndex: 'in_qr', width: 90, valueType: 'switch' },
    { title: '二维码顺序', dataIndex: 'qr_order', width: 100, valueType: 'digit' },
    { title: '渲条码', dataIndex: 'render_as_barcode', width: 90, valueType: 'switch' },
  ], []);

  const onFinish = async (values) => {
    // 进二维码字段序：由子表里 in_qr=true 的行按 qr_order 排出，写回模板头 qr_field_order
    const qrFields = fieldRows
      .filter((r) => r.in_qr)
      .sort((a, b) => (a.qr_order ?? 99) - (b.qr_order ?? 99))
      .map((r) => r.label_field_title)
      .filter(Boolean);
    const barcodeFields = fieldRows
      .filter((r) => r.render_as_barcode)
      .map((r) => r.label_field_title)
      .filter(Boolean);

    const field_updates = {
      ...values,
      qr_field_order: qrFields,
      barcode_fields: barcodeFields,
    };
    // 字段映射子表 → sub_updates（每行一条）
    const sub_updates = fieldRows.map((r, i) => {
      const { id, _tempId, ...rest } = r;
      const isNew = id == null || String(id).startsWith('new_');
      const fields = {
        ...rest,
        source_field: Array.isArray(rest.source_field) ? (rest.source_field[0] || '') : (rest.source_field || ''),
        line_number: rest.line_number || i + 1,
      };
      return isNew
        ? { table: 'label_field_line', parent_fk: 'label_template_id', fields }
        : { table: 'label_field_line', id, fields };
    });

    try {
      const { data } = await transition({
        doc_type: 'LABEL_TEMPLATE',
        doc_id: editing?.id ?? null,
        field_updates,
        sub_updates,
        comment: editing?.id ? '标签模板更新' : '标签模板建档',
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
      message.error(e.response?.data?.detail || '保存失败（LABEL_TEMPLATE 写路径未就绪）');
      return false;
    }
  };

  return (
    <div>
      <div style={{ marginBottom: 16 }}>
        <h2 style={{ fontSize: 26, fontWeight: 300, letterSpacing: '-0.01em', color: '#000', margin: 0, lineHeight: 1.2 }}>
          标签模板
        </h2>
        <span style={{ color: '#777169', fontSize: 13 }}>配置 / 模板 · 客户×标签类型 字段映射 + 二维码拼接规则</span>
      </div>

      <Alert
        type="info" showIcon style={{ marginBottom: 16, borderRadius: 12 }}
        title="标签打印：功能已就绪，待真实打印机对接"
        description="本页负责把标签按客户规则配置正确（字段映射 / 二维码分隔符与字段序 / 条码开关）；物理打印走仓库本地打印机（BarTender 类），打印驱动集成待甲方确认（PRD 09 §9.1 占位）。模板写入走引擎唯一路径 /api/transition（LABEL_TEMPLATE）。"
      />

      <BizTable
        key={reloadKey}
        headerTitle="标签模板"
        rowKey="id"
        columns={columns}
        request={tableRequest}
        rowSelection={false}
        toolBarRender={() => [
          <Button key="new" type="primary" onClick={openNew}>新建标签模板</Button>,
        ]}
        onRow={(row) => ({ onClick: () => openEdit(row), style: { cursor: 'pointer' } })}
        scroll={{ x: 'max-content', y: 'calc(100vh - 400px)' }}
      />

      <BizDrawerForm
        open={open}
        onOpenChange={setOpen}
        title={`标签模板 · ${editing?.id ? '编辑' : '新建'}`}
        width={920}
        onFinish={onFinish}
        initialValues={editing || { label_type: 'PKG1', qr_separator: '', is_active: true }}
      >
        <ProFormSelect
          name="customer_id" label="客户" options={custOptions} showSearch
          rules={[{ required: true, message: '请选择客户' }]}
          fieldProps={{ optionFilterProp: 'label' }}
        />
        <ProFormText name="name" label="模板名" rules={[{ required: true, message: '请填写模板名' }]} />
        <ProFormSelect name="label_type" label="标签类型" options={LABEL_TYPE} rules={[{ required: true }]} />
        <ProFormText name="size_mm" label="尺寸(mm)" placeholder="如 62x29" />
        <ProFormSelect
          name="qr_separator" label="二维码分隔符" options={QR_SEP}
          tooltip="各客户不同：& ; + , _ 或无（进二维码字段序由下方字段映射的「进二维码」+「二维码顺序」决定）"
        />
        <ProFormSwitch name="is_active" label="启用" />

        <div style={{ fontWeight: 500, color: '#4e4e4e', margin: '12px 0 8px' }}>
          字段映射（标签字段 → 数据来源；勾「进二维码」并填顺序即进二维码拼接）
        </div>
        <BizEditableTable
          value={fieldRows}
          onChange={setFieldRows}
          rowKey="id"
          columns={fieldColumns}
          recordCreatorProps={{ record: () => ({ id: `new_${Date.now()}`, source_type: 'OUTBOUND', in_qr: false, render_as_barcode: false }) }}
        />
        <div style={{ color: '#bfbbb5', fontSize: 12, marginTop: 8 }}>
          注：二维码字段序与条码开关由本子表汇总写回模板头（qr_field_order / barcode_fields）。条码/二维码图由后端 build_label_payload 命令服务端渲染（PRD §9.1 XSS 约束：不接受前端写 HTML）。
        </div>
      </BizDrawerForm>
    </div>
  );
}
