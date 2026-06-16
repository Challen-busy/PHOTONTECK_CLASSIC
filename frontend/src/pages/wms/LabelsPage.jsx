/**
 * LabelsPage —— 标签打印（入仓编号 62×29mm 条码，PRD 03a-6）
 *
 * 入库页/库存页可批量选中 N 个入仓编号直接打印；本页是独立入口：
 *   - 按入仓编号/型号在库存里查批次 → 选中 → 一键预览 62×29mm 标签
 *   - "功能已就绪·待打印机对接"占位（14 律留口子；真实条码由后端标签命令渲染）
 *
 * ⚠️ 内部入仓编号标签；客户出货标签（各客户二维码拼接规则）属出库 + 配置/模板模块（标签模板页），本页不展开。
 */
import { useCallback, useMemo, useState } from 'react';
import { Alert, App, Button, Space } from 'antd';
import { PrinterOutlined } from '@ant-design/icons';
import { BizTable } from '../../components/biz';
import { query, getSchema } from '../../api';
import { schemaToColumns } from './wmsHelpers';
import { LabelPrintModal } from './wmsShared';

const TABLE = 'inventory';

export default function LabelsPage() {
  const { message } = App.useApp();
  const [schema, setSchema] = useState(null);
  const [labelModal, setLabelModal] = useState({ open: false, codes: [] });

  const tableRequest = useCallback(async (params = {}) => {
    let sc = schema;
    if (!sc) {
      try { const { data } = await getSchema(TABLE); sc = data; setSchema(data); }
      catch { sc = { fields: [] }; }
    }
    const { current: _c, pageSize, keyword, ...rest } = params;
    const filters = {};
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
      message.error(e.response?.data?.detail || '加载库存失败');
      return { data: [], success: false, total: 0 };
    }
  }, [schema, message]);

  // 只展示与标签相关的几列（入仓编号/型号/SN/数量/库位），其余 schema 列由列设置可开
  const columns = useMemo(() => {
    const wanted = new Set(['inbound_number', 'material_id', 'serial_lot_number', 'quantity', 'uom', 'location_code']);
    const fields = (schema?.fields || []).filter((f) => wanted.has(f.name));
    return schemaToColumns(fields, { frozen: ['inbound_number'] });
  }, [schema]);

  return (
    <div>
      <div style={{ marginBottom: 16 }}>
        <h2 style={{ fontSize: 26, fontWeight: 300, letterSpacing: '-0.01em', color: '#000', margin: 0, lineHeight: 1.2 }}>
          标签打印
        </h2>
        <span style={{ color: '#777169', fontSize: 13 }}>仓储 WMS · 入仓编号 62×29mm 条码标签</span>
      </div>

      <Alert
        type="warning" showIcon style={{ marginBottom: 16, borderRadius: 12 }}
        title="功能已就绪 · 待打印机对接"
        description="选中 N 个入仓编号一键生成 62×29mm 标签（文本 + 一维条码），支持单张补打。条码渲染与打印机驱动（ZPL/EPL）由后端标签命令 + 现场打印机对接（PRD E8）。客户出货标签属出库/配置模块。"
      />

      <BizTable
        headerTitle="按入仓编号选标签"
        rowKey="id"
        columns={columns}
        request={tableRequest}
        rowSelection={{}}
        tableAlertOptionRender={({ selectedRows }) => (
          <Space size={12}>
            <span style={{ color: '#777169' }}>已选 {selectedRows.length} 个入仓编号</span>
            <Button type="primary" size="small" icon={<PrinterOutlined />}
              onClick={() => setLabelModal({
                open: true,
                codes: selectedRows.map((r) => r.inbound_number).filter(Boolean),
              })}>打印标签</Button>
          </Space>
        )}
        scroll={{ x: 'max-content', y: 'calc(100vh - 420px)' }}
      />

      <LabelPrintModal
        open={labelModal.open}
        onClose={() => setLabelModal({ open: false, codes: [] })}
        codes={labelModal.codes}
      />
    </div>
  );
}
