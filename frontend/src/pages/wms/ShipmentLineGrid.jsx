/**
 * ShipmentLineGrid —— 拣货明细网格录入（PRD 03b 页面 1·2 子表 + 录单增强 14 律）
 *
 * 列由 shipment_line 的 /api/schema 驱动（后端 ➕ 列自动出现），叠加出库录单增强：
 *   ① 入仓编号 cell 选择器：候选只来自「本公司 + 可售(AVAILABLE) + 结存>0 + 原厂报备客户∈{本单客户,空}」
 *      的 inventory 批次（前端过滤提示），选中即自动带出 型号/SN/供应商/性质/原厂报备客户/可用结存（PRD E8）。
 *   ② 入仓编号可扫标签条码入格：扫码=直接填 inbound_number，匹配到候选批次则带出（访谈 05 L666）。
 *   ③ 出库数量 ≤ 该批次可用结存：超出就地标红 + 阻断（不静默；红线⑦ 禁 magic）。
 *   ④ 串货隔离前端提示：所选批次原厂报备客户≠本单客户即整行标红提示（后端 validator 终判，前端先提示）。
 *   ⑤ 每包照片引用槽（可见）：每行登记照片引用 URL/路径，缺照片在互检前由父页提示（PRD E4，引擎无对象存储，先存引用文本）。
 *   ⑥ 分箱箱号 carton_number 行内录入。
 *
 * 乐观 UI：改即写本地 value，父页提交时落 /api/transition sub_updates 走引擎唯一路径；失败父页标红、不静默。
 * ⚠️ 不写死成本列、不绕底座：本组件只产出子表行 value + 选批次带出展示，写入由父页 sub_updates。
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { App, Button, Tooltip, Tag, Input } from 'antd';
import { ScanOutlined, CameraOutlined } from '@ant-design/icons';
import { BizEditableTable } from '../../components/biz';
import { getSchema, query } from '../../api';
import { loadFkOptions } from '../master/fkOptions';

// 子表不进网格的系统/自动列（line_number 自动；shipment_id 父 FK）
const GRID_SKIP = new Set([
  'id', 'shipment_id', 'created_at', 'updated_at', 'created_by_id', 'updated_by_id',
  'company_id', 'line_number',
]);

// 选中入仓编号后自动带出的批次字段 → shipment_line 列（带出只读展示，仍可改）
const CARRY_OVER = {
  serial_lot_number: 'serial_lot_number',
  supplier_id: 'supplier_id',
  goods_nature: 'goods_nature',
  uom: 'uom',
  origin_country: 'origin_country',
  hs_code: 'hs_code',
};

const COL_WIDTH = {
  inbound_number: 170, sales_order_line_id: 140, inventory_id: 70, quantity: 110, uom: 80,
  serial_lot_number: 150, supplier_id: 130, goods_nature: 110, tracking_number: 130,
  delivery_method: 120, invoice_number: 120, carton_number: 110, origin_country: 110,
  hs_code: 110, _photo: 200, _avail: 100,
};

const NUMERIC_TYPES = new Set(['number', 'integer']);

export default function ShipmentLineGrid({ value = [], onChange, customerId }) {
  const { message } = App.useApp();
  const [fields, setFields] = useState([]);
  const [fkOpts, setFkOpts] = useState({});          // {字段: [{label,value}]}（sales_order_line_id 等）
  const [batches, setBatches] = useState([]);        // 可出库批次候选（本公司+可售+结存>0）
  const [scanMode, setScanMode] = useState(false);
  const [scanText, setScanText] = useState('');

  // 拉子表 schema + FK 候选
  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const { data } = await getSchema('shipment_line');
        if (!alive) return;
        const fs = (data?.fields || []).filter((f) => !GRID_SKIP.has(f.name) && !f.primary_key);
        setFields(fs);
        const opts = {};
        // inventory_id 不走通用 fk 选择器（改用入仓编号批次选择器带出），其余 FK 走通用候选
        for (const f of fs.filter((x) => x.fk?.table && x.name !== 'inventory_id')) {
          opts[f.name] = await loadFkOptions(f.fk.table, f.name);
        }
        if (alive) setFkOpts(opts);
      } catch {
        if (alive) setFields([]);
      }
    })();
    return () => { alive = false; };
  }, []);

  // 拉可出库批次候选：本公司（/api/query 已按 active_company 行级隔离）+ 可售 + 结存>0
  // 串货隔离按本单客户在前端再过滤（原厂报备客户∈{本单客户, 空}）；后端 validator 终判。
  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const { data } = await query('inventory', {
          filters: { status: 'AVAILABLE' }, order_by: '-id', limit: 300,
        });
        if (!alive) return;
        const rows = (data?.data || []).filter((r) => {
          const remain = Number(r.quantity || 0) - Number(r.reserved_quantity || 0);
          if (remain <= 0) return false;
          if (customerId && r.reported_customer_id != null
            && Number(r.reported_customer_id) !== Number(customerId)) return false;
          return true;
        });
        setBatches(rows);
      } catch { if (alive) setBatches([]); }
    })();
    return () => { alive = false; };
  }, [customerId]);

  // 批次候选 → 选择器 options（label 含 结存/型号/性质 提示；value=inbound_number）
  const batchOptions = useMemo(() => batches
    .filter((b) => b.inbound_number)
    .map((b) => {
      const remain = Number(b.quantity || 0) - Number(b.reserved_quantity || 0);
      return {
        value: b.inbound_number,
        label: `${b.inbound_number} · 结存${remain} · ${b.goods_nature || '—'}`,
        _batch: b,
      };
    }), [batches]);

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

  // 选中/扫到入仓编号 → 把批次信息带出到该行（型号/SN/供应商/性质/单位/原产地/HS/批次结存/原厂报备客户）
  const applyBatch = useCallback((rows, rowId, inbound) => {
    const b = batchByInbound[inbound];
    const next = rows.map((r) => {
      if (r.id !== rowId) return r;
      const merged = { ...r, inbound_number: inbound };
      if (b) {
        merged.inventory_id = b.id;
        for (const [src, dst] of Object.entries(CARRY_OVER)) {
          if (b[src] != null && b[src] !== '') merged[dst] = b[src];
        }
        merged._material = b.material_id;
        merged._reported_customer_id = b.reported_customer_id;
        merged._avail = Number(b.quantity || 0) - Number(b.reserved_quantity || 0);
      }
      return merged;
    });
    return next;
  }, [batchByInbound]);

  const onInboundChange = useCallback((rowId, inbound) => {
    onChange(applyBatch(value, rowId, inbound));
  }, [value, onChange, applyBatch]);

  // 扫码枪录入：扫一条入仓编号 → 新建行并带出批次（或聚焦已存在行）
  const onScan = useCallback((raw) => {
    const inbound = (raw || '').trim();
    if (!inbound) return;
    setScanText('');
    if (!batchByInbound[inbound]) {
      message.warning(`入仓编号「${inbound}」不在可出库批次中（非本公司/不可售/结存为0/串货不匹配）`);
      return;
    }
    const newId = `new_${Date.now()}`;
    const rows = [...value, { id: newId, inbound_number: inbound, quantity: 0 }];
    onChange(applyBatch(rows, newId, inbound));
    message.success(`已扫入 ${inbound}，已带出批次信息`);
  }, [value, onChange, applyBatch, batchByInbound, message]);

  // 串货命中提示：所选批次原厂报备客户≠本单客户
  const isCrossOver = useCallback((row) => {
    const rc = row._reported_customer_id;
    return customerId && rc != null && Number(rc) !== Number(customerId);
  }, [customerId]);

  // schema → 网格列
  const columns = useMemo(() => {
    const cols = [];
    for (const f of fields) {
      const base = {
        title: f.label || f.name,
        dataIndex: f.name,
        width: COL_WIDTH[f.name] || 130,
        formItemProps: !f.nullable && !NUMERIC_TYPES.has(f.type)
          ? { rules: [{ required: true, message: '必填' }] }
          : undefined,
      };

      // 入仓编号：批次选择器（带「本公司+可售+结存>0+串货匹配」候选）+ 可扫/手填
      if (f.name === 'inbound_number') {
        cols.push({
          ...base,
          valueType: 'select',
          fieldProps: (_, { rowKey }) => ({
            options: batchOptions,
            showSearch: true,
            optionFilterProp: 'label',
            placeholder: '选/扫入仓编号（仅本公司·可售·结存>0）',
            onChange: (v) => onInboundChange(rowKey, v),
          }),
          render: (_, row) => {
            const cross = isCrossOver(row);
            return (
              <span style={{ color: cross ? '#b42318' : '#000', fontWeight: cross ? 600 : 400 }}>
                {row.inbound_number || <span style={{ color: '#bfbbb5' }}>—</span>}
                {cross && <Tag color="error" style={{ marginInlineStart: 6 }}>串货</Tag>}
              </span>
            );
          },
        });
        continue;
      }

      // inventory_id：批次链（选入仓编号后自动带出，只读展示 #id）
      if (f.name === 'inventory_id') {
        cols.push({
          ...base, editable: false,
          render: (_, row) => (row.inventory_id != null
            ? <span style={{ color: '#777169' }}>#{row.inventory_id}</span>
            : <span style={{ color: '#bfbbb5' }}>—</span>),
        });
        continue;
      }

      // 出库数量：≤批次结存，超出标红
      if (f.name === 'quantity') {
        cols.push({
          ...base, valueType: 'digit',
          fieldProps: { precision: 2, min: 0 },
          render: (_, row) => {
            const remain = remainOf(row.inbound_number);
            const over = remain != null && Number(row.quantity || 0) > remain;
            return (
              <span style={{
                fontFamily: 'ui-monospace, monospace', textAlign: 'right',
                color: over ? '#b42318' : '#000', fontWeight: over ? 600 : 400,
              }}>
                {row.quantity ?? <span style={{ color: '#bfbbb5' }}>—</span>}
                {over && <Tag color="error" style={{ marginInlineStart: 6 }}>超结存{remain}</Tag>}
              </span>
            );
          },
        });
        continue;
      }

      // 其余 FK（sales_order_line_id / supplier_id）→ 选择器
      if (f.fk?.table) {
        cols.push({
          ...base, valueType: 'select',
          fieldProps: { options: fkOpts[f.name] || [], showSearch: true, optionFilterProp: 'label' },
          render: (_, row) => {
            const opt = (fkOpts[f.name] || []).find((o) => o.value === row[f.name]);
            return opt ? opt.label : (row[f.name] != null
              ? <span style={{ color: '#777169' }}>#{row[f.name]}</span>
              : <span style={{ color: '#bfbbb5' }}>—</span>);
          },
        });
        continue;
      }

      if (NUMERIC_TYPES.has(f.type)) {
        cols.push({ ...base, valueType: 'digit', fieldProps: { precision: f.type === 'integer' ? 0 : 2 } });
        continue;
      }
      cols.push(base);
    }

    // 可用结存（带出展示列，只读）
    cols.push({
      title: '可用结存', dataIndex: '_avail', width: COL_WIDTH._avail, editable: false, search: false,
      render: (_, row) => {
        const remain = row._avail != null ? row._avail : remainOf(row.inbound_number);
        return remain == null
          ? <span style={{ color: '#bfbbb5' }}>—</span>
          : <span style={{ fontFamily: 'ui-monospace, monospace' }}>{remain}</span>;
      },
    });

    // 每包照片引用槽（可见；缺照片互检前父页提示）
    cols.push({
      title: '每包照片引用', dataIndex: '_photo', width: COL_WIDTH._photo,
      render: (_, row) => (
        <span style={{ color: row._photo ? '#1f8f3a' : '#b8860b', fontSize: 12 }}>
          {row._photo
            ? <><CameraOutlined style={{ marginInlineEnd: 4 }} />已挂照片</>
            : <><CameraOutlined style={{ marginInlineEnd: 4 }} />待补照片</>}
        </span>
      ),
      renderFormItem: () => (
        <Input placeholder="粘贴出库照片库引用（共享文档 URL/路径）" allowClear prefix={<CameraOutlined />} />
      ),
    });

    return cols;
  }, [fields, fkOpts, batchOptions, onInboundChange, isCrossOver, remainOf]);

  return (
    <div>
      {/* 录单增强工具条（14 律录单效率：扫码入格 + 串货/结存提示） */}
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
        <Tooltip title="候选批次=本公司 + 可售(AVAILABLE) + 结存>0 + 原厂报备客户匹配本单客户（串货隔离）">
          <Tag color="processing">可出库批次 {batchOptions.length} 个</Tag>
        </Tooltip>
        {!customerId && (
          <span style={{ color: '#b8860b', fontSize: 12 }}>
            先在单据头选客户，串货隔离候选才会按本单客户过滤
          </span>
        )}
        <span style={{ flex: 1 }} />
        <span style={{ color: '#777169', fontSize: 12 }}>{value.length} 行</span>
      </div>

      <BizEditableTable
        value={value}
        onChange={onChange}
        rowKey="id"
        columns={columns}
        scroll={{ x: 'max-content', y: 360 }}
        recordCreatorProps={{ record: () => ({ id: `new_${Date.now()}`, quantity: 0 }) }}
        editable={{
          type: 'multiple',
          editableKeys: value.map((r) => r.id),
          onValuesChange: (_record, recordList) => onChange(recordList),
        }}
      />
    </div>
  );
}
