/**
 * BatchLineGrid —— 通用「入仓编号批次明细网格」（PRD 03b 页面 5 调拨 / 页面 7 库存调整子表）
 *
 * 复用 ShipmentLineGrid 的批次选择器/扫码/带出/结存校验套路，做成可配置的轻量通用网格：
 *   - 入仓编号 cell 选择器：候选只来自「本公司 + 结存>0」的 inventory 批次（/api/query 已按 active_company 行级隔离）。
 *     选中即自动带出 型号(_material)/SN/性质(goods_nature)/可用结存(_avail)/inventory_id（PRD E8）。
 *   - 入仓编号可扫标签条码入格（访谈 05 L666）。
 *   - 数量列 ≤ 该批次可用结存：超出就地标红 + Tag 提示（不静默；红线⑦ 禁 magic）。
 *   - extraColumns：父页注入业务列（调拨数量 / 调整差异原因 等），列由父页给 valueType/必填/选择器。
 *
 * 子表 schema 由父页传 lineTable（如 stock_transfer_line / stock_adjustment_line）；
 * 后端若尚未注册该表则 schema 拉空，网格只出「入仓编号 + 通用列 + extraColumns」，父页据此降级提示。
 * 乐观 UI：改即写本地 value，父页提交时落 /api/transition sub_updates 走引擎唯一路径；失败父页标红、不静默。
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { App, Button, Input, Tag, Tooltip } from 'antd';
import { ScanOutlined } from '@ant-design/icons';
import { BizEditableTable } from '../../components/biz';
import { query } from '../../api';

// 选中入仓编号后带出的批次字段 → 子表列
const CARRY_OVER = {
  serial_lot_number: 'serial_lot_number',
  goods_nature: 'goods_nature',
  uom: 'uom',
};

/**
 * @param {Array}    value           受控行数据
 * @param {Function} onChange        受控回写
 * @param {string}   quantityField   数量列字段名（调拨=quantity / 调整=quantity；父页决定）
 * @param {string}   quantityLabel   数量列标题
 * @param {Array}    extraColumns    父页注入的额外列（差异原因选择器等）
 * @param {boolean}  enforceRemain   数量是否受结存约束（调拨=true；调整=false，差异可正可负）
 */
export default function BatchLineGrid({
  value = [], onChange,
  quantityField = 'quantity', quantityLabel = '数量',
  extraColumns = [], enforceRemain = true,
}) {
  const { message } = App.useApp();
  const [batches, setBatches] = useState([]);
  const [scanMode, setScanMode] = useState(false);
  const [scanText, setScanText] = useState('');

  // 拉本公司可用批次（结存>0）；/api/query 已按 active_company 行级隔离
  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const { data } = await query('inventory', { order_by: '-id', limit: 300 });
        if (!alive) return;
        const rows = (data?.data || []).filter((r) => (
          Number(r.quantity || 0) - Number(r.reserved_quantity || 0) > 0
        ));
        setBatches(rows);
      } catch { if (alive) setBatches([]); }
    })();
    return () => { alive = false; };
  }, []);

  const batchByInbound = useMemo(() => {
    const map = {};
    for (const b of batches) if (b.inbound_number) map[b.inbound_number] = b;
    return map;
  }, [batches]);

  const remainOf = useCallback((inbound) => {
    const b = batchByInbound[inbound];
    if (!b) return null;
    return Number(b.quantity || 0) - Number(b.reserved_quantity || 0);
  }, [batchByInbound]);

  const batchOptions = useMemo(() => batches
    .filter((b) => b.inbound_number)
    .map((b) => {
      const remain = Number(b.quantity || 0) - Number(b.reserved_quantity || 0);
      return {
        value: b.inbound_number,
        label: `${b.inbound_number} · 结存${remain} · ${b.goods_nature || '—'}`,
      };
    }), [batches]);

  // 选中/扫到入仓编号 → 带出批次信息
  const applyBatch = useCallback((rows, rowId, inbound) => {
    const b = batchByInbound[inbound];
    return rows.map((r) => {
      if (r.id !== rowId) return r;
      const merged = { ...r, inbound_number: inbound };
      if (b) {
        merged.inventory_id = b.id;
        for (const [src, dst] of Object.entries(CARRY_OVER)) {
          if (b[src] != null && b[src] !== '') merged[dst] = b[src];
        }
        merged._material = b.material_id;
        merged._avail = Number(b.quantity || 0) - Number(b.reserved_quantity || 0);
        merged.system_quantity = merged._avail;
      }
      return merged;
    });
  }, [batchByInbound]);

  const onInboundChange = useCallback((rowId, inbound) => {
    onChange(applyBatch(value, rowId, inbound));
  }, [value, onChange, applyBatch]);

  const onScan = useCallback((raw) => {
    const inbound = (raw || '').trim();
    if (!inbound) return;
    setScanText('');
    if (!batchByInbound[inbound]) {
      message.warning(`入仓编号「${inbound}」不在本公司可用批次中（非本公司/结存为0）`);
      return;
    }
    const newId = `new_${Date.now()}`;
    const rows = [...value, { id: newId, inbound_number: inbound, [quantityField]: 0 }];
    onChange(applyBatch(rows, newId, inbound));
    message.success(`已扫入 ${inbound}，已带出批次信息`);
  }, [value, onChange, applyBatch, batchByInbound, quantityField, message]);

  const columns = useMemo(() => {
    const cols = [
      {
        title: '入仓编号', dataIndex: 'inbound_number', width: 200,
        valueType: 'select',
        formItemProps: { rules: [{ required: true, message: '必填' }] },
        fieldProps: (_, { rowKey }) => ({
          options: batchOptions, showSearch: true, optionFilterProp: 'label',
          placeholder: '选/扫入仓编号（本公司·结存>0）',
          onChange: (v) => onInboundChange(rowKey, v),
        }),
        render: (_, row) => (row.inbound_number
          ? <span style={{ fontFamily: 'ui-monospace, monospace' }}>{row.inbound_number}</span>
          : <span style={{ color: '#bfbbb5' }}>—</span>),
      },
      {
        title: '型号', dataIndex: '_material', width: 90, editable: false, search: false,
        render: (_, row) => (row._material != null
          ? <span style={{ color: '#777169' }}>#{row._material}</span>
          : <span style={{ color: '#bfbbb5' }}>—</span>),
      },
      {
        title: '性质', dataIndex: 'goods_nature', width: 100, editable: false, search: false,
        render: (_, row) => row.goods_nature || <span style={{ color: '#bfbbb5' }}>—</span>,
      },
      {
        title: quantityLabel, dataIndex: quantityField, width: 130, valueType: 'digit',
        fieldProps: { precision: 2 },
        render: (_, row) => {
          const remain = remainOf(row.inbound_number);
          const over = enforceRemain && remain != null
            && Number(row[quantityField] || 0) > remain;
          return (
            <span style={{
              fontFamily: 'ui-monospace, monospace',
              color: over ? '#b42318' : '#000', fontWeight: over ? 600 : 400,
            }}>
              {row[quantityField] ?? <span style={{ color: '#bfbbb5' }}>—</span>}
              {over && <Tag color="error" style={{ marginInlineStart: 6 }}>超结存{remain}</Tag>}
            </span>
          );
        },
      },
      {
        title: '可用结存', dataIndex: '_avail', width: 100, editable: false, search: false,
        render: (_, row) => {
          const remain = row._avail != null ? row._avail : remainOf(row.inbound_number);
          return remain == null
            ? <span style={{ color: '#bfbbb5' }}>—</span>
            : <span style={{ fontFamily: 'ui-monospace, monospace' }}>{remain}</span>;
        },
      },
      ...extraColumns,
    ];
    return cols;
  }, [batchOptions, onInboundChange, remainOf, enforceRemain, quantityField, quantityLabel, extraColumns]);

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8, flexWrap: 'wrap' }}>
        <Button
          size="small" type={scanMode ? 'primary' : 'default'} icon={<ScanOutlined />}
          onClick={() => setScanMode((s) => !s)}
        >
          {scanMode ? '扫码模式·开' : '扫码枪录入入仓编号'}
        </Button>
        {scanMode && (
          <Input
            size="small" style={{ width: 240 }} autoFocus allowClear
            value={scanText}
            placeholder="扫入仓编号标签条码 → 回车入行"
            prefix={<ScanOutlined />}
            onChange={(e) => setScanText(e.target.value)}
            onPressEnter={(e) => onScan(e.target.value)}
          />
        )}
        <Tooltip title="候选批次 = 本公司（行级隔离）+ 结存>0">
          <Tag color="processing">可用批次 {batchOptions.length} 个</Tag>
        </Tooltip>
        <span style={{ flex: 1 }} />
        <span style={{ color: '#777169', fontSize: 12 }}>{value.length} 行</span>
      </div>

      <BizEditableTable
        value={value}
        onChange={onChange}
        rowKey="id"
        columns={columns}
        scroll={{ x: 'max-content', y: 320 }}
        recordCreatorProps={{ record: () => ({ id: `new_${Date.now()}`, [quantityField]: 0 }) }}
        editable={{
          type: 'multiple',
          editableKeys: value.map((r) => r.id),
          onValuesChange: (_record, recordList) => onChange(recordList),
        }}
      />
    </div>
  );
}
