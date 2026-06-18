/**
 * AuxAccountingModal —— 分录辅助核算 + 现金流量指定弹层（owns by C·前端 PM）
 *
 * 对齐录音/蓝图：辅助核算科目级 1~2 维（往来对象 / 部门 / 项目），现金流量做凭证时指定。
 * 编辑单条分录的 aux_party_type / aux_party_id / aux_dept_id / aux_project_id / cashflow_item_id
 * （字段名对齐 models.VoucherEntry）。往来对象类型枚举对齐 AuxiliaryDimension.source_type。
 *
 * 数据源：现金流量项目走可查表 cashflow_item（后端按 _company_filter 隔离）。往来对象主键（客户/供应商/职员）
 * 当前以纯数字输入承载（弱引用、跨表多态，models 注释明确不建 FK）——后端补对象选择端点前不写死跳转。
 */
import { useEffect, useState } from 'react';
import { Modal, Form, Select, InputNumber, Input, Divider } from 'antd';
import { query } from '../../api';

const PARTY_TYPES = [
  { value: 'CUSTOMER', label: '客户' },
  { value: 'SUPPLIER', label: '供应商' },
  { value: 'EMPLOYEE', label: '职员' },
];

export default function AuxAccountingModal({ open, entry, onOk, onCancel }) {
  const [form] = Form.useForm();
  const [cashflowItems, setCashflowItems] = useState([]);

  useEffect(() => {
    if (!open) return;
    query('cashflow_item', { filters: { is_active: true }, order_by: 'code', limit: 500 })
      .then(({ data }) => setCashflowItems(data?.data || []))
      .catch(() => setCashflowItems([]));
  }, [open]);

  useEffect(() => {
    if (open && entry) {
      form.setFieldsValue({
        aux_party_type: entry.aux_party_type || undefined,
        aux_party_id: entry.aux_party_id ?? undefined,
        aux_dept_id: entry.aux_dept_id ?? undefined,
        aux_project_id: entry.aux_project_id ?? undefined,
        cashflow_item_id: entry.cashflow_item_id ?? undefined,
        settlement_method: entry.settlement_method || undefined,
        settlement_no: entry.settlement_no || undefined,
      });
    }
  }, [open, entry, form]);

  const submit = async () => {
    const v = await form.validateFields();
    onOk?.(v);
  };

  return (
    <Modal
      open={open}
      onOk={submit}
      onCancel={onCancel}
      title="辅助核算 / 现金流量 / 结算"
      width={520}
      okText="确定"
      cancelText="取消"
      destroyOnClose
    >
      <Form form={form} layout="vertical" size="small">
        <Divider orientation="left" plain style={{ margin: '4px 0 12px' }}>辅助核算（科目级 1~2 维）</Divider>
        <div style={{ display: 'flex', gap: 8 }}>
          <Form.Item name="aux_party_type" label="往来对象类型" style={{ flex: 1 }}>
            <Select allowClear options={PARTY_TYPES} placeholder="客户/供应商/职员" />
          </Form.Item>
          <Form.Item name="aux_party_id" label="往来对象 ID" style={{ flex: 1 }}
            tooltip="弱引用业务主键（客户/供应商/职员）；后端补对象选择端点前以 ID 承载">
            <InputNumber style={{ width: '100%' }} placeholder="对象主键" />
          </Form.Item>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <Form.Item name="aux_dept_id" label="部门 ID" style={{ flex: 1 }}>
            <InputNumber style={{ width: '100%' }} placeholder="部门主键" />
          </Form.Item>
          <Form.Item name="aux_project_id" label="项目 ID" style={{ flex: 1 }}>
            <InputNumber style={{ width: '100%' }} placeholder="项目主键" />
          </Form.Item>
        </div>

        <Divider orientation="left" plain style={{ margin: '4px 0 12px' }}>现金流量项目</Divider>
        <Form.Item name="cashflow_item_id" label="现金流量项目">
          <Select
            allowClear
            showSearch
            optionFilterProp="label"
            placeholder="做凭证时指定（资金类必填，由后续波校验）"
            options={cashflowItems.map((c) => ({
              value: c.id,
              label: `${c.code} ${c.name}（${c.direction === 'IN' ? '流入' : '流出'}）`,
            }))}
          />
        </Form.Item>

        <Divider orientation="left" plain style={{ margin: '4px 0 12px' }}>结算（资金类）</Divider>
        <div style={{ display: 'flex', gap: 8 }}>
          <Form.Item name="settlement_method" label="结算方式" style={{ flex: 1 }}>
            <Select allowClear placeholder="现金/转账/票据" options={[
              { value: '现金', label: '现金' },
              { value: '转账', label: '转账' },
              { value: '票据', label: '票据' },
              { value: '其他', label: '其他' },
            ]} />
          </Form.Item>
          <Form.Item name="settlement_no" label="结算号" style={{ flex: 1 }}>
            <Input placeholder="票号 / 流水号" />
          </Form.Item>
        </div>
      </Form>
    </Modal>
  );
}
