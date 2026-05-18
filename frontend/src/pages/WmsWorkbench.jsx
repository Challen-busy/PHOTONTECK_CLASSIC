import { useEffect, useMemo, useState } from 'react';
import {
  Alert, Button, Card, Col, DatePicker, Empty, Form, Input, InputNumber,
  Modal, Row, Select, Space, Statistic, Table, Tabs, Tag, Upload, message,
} from 'antd';
import {
  CheckSquareOutlined, CloudUploadOutlined, DownloadOutlined, FileSearchOutlined,
  LockOutlined, ReloadOutlined, SafetyCertificateOutlined, ThunderboltOutlined,
  UnlockOutlined, WarningOutlined,
} from '@ant-design/icons';
import dayjs from 'dayjs';
import {
  adjustWmsCount, autoAllocateWmsShipment, createWmsCount, getWmsAlerts,
  getWmsCommandAudit, getWmsCountDetail, getWmsCounts, getWmsInventory,
  getWmsMovementAudit, getWmsPolicies, getWmsReport, getWmsReservations,
  getWmsSnRules, getWmsSummary, importWmsInventoryCsv,
  matchWmsStock, query, releaseWmsReservation, reserveWmsInventory, saveWmsPolicy,
  saveWmsSnRule, submitWmsCount, updateWmsCountLine, validateWmsSnRule,
} from '../api';

const CARD_SHADOW =
  'rgba(0,0,0,0.06) 0px 0px 0px 1px, rgba(0,0,0,0.04) 0px 1px 2px, rgba(0,0,0,0.04) 0px 2px 4px';

function n(value) {
  return Number(value || 0).toLocaleString();
}

function optionLabel(row) {
  return row.short_name || row.name || row.sku || row.order_number || row.shipment_number ||
    row.receipt_number || row.count_number || row.code || `#${row.id}`;
}

function csvUrl(reportName, params = {}) {
  const qs = new URLSearchParams({ ...params, format: 'csv' });
  return `/api/wms/reports/${reportName}?${qs.toString()}`;
}

const EMPTY_AUDIT_FILTERS = {
  command_name: '',
  status: undefined,
  movement_type: undefined,
  material_id: undefined,
  inventory_id: undefined,
  command_log_id: undefined,
};

const MOVEMENT_TYPE_OPTIONS = [
  { value: 'INVENTORY_IMPORT', label: '导入入库' },
  { value: 'GOODS_RECEIPT_IN', label: '采购入库' },
  { value: 'SHIPMENT_OUT', label: '销售出库' },
  { value: 'RESERVE', label: '库存预留' },
  { value: 'RELEASE_RESERVATION', label: '释放预留' },
  { value: 'COUNT_ADJUST', label: '盘点调整' },
];

function Metric({ title, value }) {
  return (
    <Card style={{ borderRadius: 8, border: 'none', boxShadow: CARD_SHADOW }} styles={{ body: { padding: 16 } }}>
      <Statistic title={title} value={Number(value || 0)} precision={0} />
    </Card>
  );
}

export default function WmsWorkbench() {
  const [summary, setSummary] = useState(null);
  const [inventory, setInventory] = useState([]);
  const [reservations, setReservations] = useState([]);
  const [commandAudit, setCommandAudit] = useState([]);
  const [movementAudit, setMovementAudit] = useState([]);
  const [auditFilters, setAuditFilters] = useState(EMPTY_AUDIT_FILTERS);
  const [rules, setRules] = useState([]);
  const [policies, setPolicies] = useState([]);
  const [alerts, setAlerts] = useState([]);
  const [counts, setCounts] = useState([]);
  const [countDetail, setCountDetail] = useState(null);
  const [stockMatch, setStockMatch] = useState(null);
  const [customers, setCustomers] = useState([]);
  const [salesOrders, setSalesOrders] = useState([]);
  const [shipments, setShipments] = useState([]);
  const [suppliers, setSuppliers] = useState([]);
  const [materials, setMaterials] = useState([]);
  const [warehouses, setWarehouses] = useState([]);
  const [search, setSearch] = useState('');
  const [loading, setLoading] = useState(false);
  const [reserveOpen, setReserveOpen] = useState(false);
  const [selectedInventory, setSelectedInventory] = useState(null);
  const [reportDate, setReportDate] = useState(dayjs());
  const [report, setReport] = useState(null);
  const [reserveForm] = Form.useForm();
  const [ruleForm] = Form.useForm();
  const [snCheckForm] = Form.useForm();
  const [policyForm] = Form.useForm();
  const [countForm] = Form.useForm();
  const [matchForm] = Form.useForm();
  const [auditForm] = Form.useForm();

  const customerOptions = useMemo(
    () => customers.map(r => ({ value: r.id, label: optionLabel(r) })),
    [customers],
  );
  const salesOrderOptions = useMemo(
    () => salesOrders.map(r => ({ value: r.id, label: optionLabel(r) })),
    [salesOrders],
  );
  const shipmentOptions = useMemo(
    () => shipments.map(r => ({ value: r.id, label: optionLabel(r) })),
    [shipments],
  );
  const supplierOptions = useMemo(
    () => suppliers.map(r => ({ value: r.id, label: optionLabel(r) })),
    [suppliers],
  );
  const materialOptions = useMemo(
    () => materials.map(r => ({ value: r.id, label: optionLabel(r) })),
    [materials],
  );
  const warehouseOptions = useMemo(
    () => warehouses.map(r => ({ value: r.id, label: optionLabel(r) })),
    [warehouses],
  );

  const loadOptions = async () => {
    const [c, so, sh, sp, mt, wh] = await Promise.all([
      query('customer', { limit: 300 }),
      query('sales_order', { limit: 300 }),
      query('shipment_request', { limit: 300 }),
      query('supplier', { limit: 300 }),
      query('material', { limit: 300 }),
      query('warehouse', { limit: 300 }),
    ]);
    setCustomers(c.data.data || []);
    setSalesOrders(so.data.data || []);
    setShipments(sh.data.data || []);
    setSuppliers(sp.data.data || []);
    setMaterials(mt.data.data || []);
    setWarehouses(wh.data.data || []);
  };

  const loadAudit = async (filters = auditFilters) => {
    try {
      const commandParams = { limit: 100 };
      if (filters.command_name) commandParams.command_name = filters.command_name;
      if (filters.status) commandParams.status = filters.status;

      const movementParams = { limit: 200 };
      if (filters.movement_type) movementParams.movement_type = filters.movement_type;
      if (filters.material_id) movementParams.material_id = filters.material_id;
      if (filters.inventory_id) movementParams.inventory_id = filters.inventory_id;
      if (filters.command_log_id) movementParams.command_log_id = filters.command_log_id;

      const [commands, movements] = await Promise.all([
        getWmsCommandAudit(commandParams),
        getWmsMovementAudit(movementParams),
      ]);
      setCommandAudit(commands.data.data || []);
      setMovementAudit(movements.data.data || []);
    } catch {
      message.error('审计数据加载失败');
    }
  };

  const load = async () => {
    setLoading(true);
    try {
      const [s, inv, rsv, rule, policy, alert, count] = await Promise.all([
        getWmsSummary(),
        getWmsInventory({ search }),
        getWmsReservations(),
        getWmsSnRules(),
        getWmsPolicies(),
        getWmsAlerts(),
        getWmsCounts(),
      ]);
      setSummary(s.data);
      setInventory(inv.data.data || []);
      setReservations(rsv.data.data || []);
      setRules(rule.data.data || []);
      setPolicies(policy.data.data || []);
      setAlerts(alert.data.data || []);
      setCounts(count.data.data || []);
      loadAudit();
    } catch {
      message.error('WMS 数据加载失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadOptions();
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const openReserve = (row) => {
    setSelectedInventory(row);
    reserveForm.setFieldsValue({
      inventory_id: row.id,
      quantity: Math.max(0, Number(row.available_quantity || 0)),
    });
    setReserveOpen(true);
  };

  const submitReserve = async () => {
    const values = await reserveForm.validateFields();
    try {
      await reserveWmsInventory(values);
      message.success('库存已预留');
      setReserveOpen(false);
      load();
    } catch (e) {
      message.error(e.response?.data?.detail || '预留失败');
    }
  };

  const releaseReservation = async (row) => {
    try {
      await releaseWmsReservation(row.id);
      message.success('预留已释放');
      load();
    } catch {
      message.error('释放失败');
    }
  };

  const saveRule = async () => {
    const values = await ruleForm.validateFields();
    try {
      await saveWmsSnRule(values);
      message.success('SN/LOT 规则已保存');
      ruleForm.resetFields();
      load();
    } catch (e) {
      message.error(e.response?.data?.detail || '规则保存失败');
    }
  };

  const validateSn = async () => {
    const values = await snCheckForm.validateFields();
    try {
      const { data } = await validateWmsSnRule(values);
      if (data.passed) message.success('校验通过');
      else data.failures.forEach(x => message.warning(x));
    } catch (e) {
      message.error(e.response?.data?.detail || '校验失败');
    }
  };

  const savePolicy = async () => {
    const values = await policyForm.validateFields();
    try {
      await saveWmsPolicy(values);
      message.success('库存策略已保存');
      policyForm.resetFields();
      load();
    } catch (e) {
      message.error(e.response?.data?.detail || '策略保存失败');
    }
  };

  const createCount = async () => {
    const values = await countForm.validateFields();
    try {
      const { data } = await createWmsCount({
        ...values,
        planned_date: values.planned_date?.format?.('YYYY-MM-DD'),
      });
      message.success(`已创建盘点任务 ${data.count_number}`);
      countForm.resetFields();
      load();
      openCount(data.id);
    } catch (e) {
      message.error(e.response?.data?.detail || '创建盘点失败');
    }
  };

  const openCount = async (id) => {
    try {
      const { data } = await getWmsCountDetail(id);
      setCountDetail(data);
    } catch (e) {
      message.error(e.response?.data?.detail || '盘点明细加载失败');
    }
  };

  const saveCountLine = async (line) => {
    try {
      await updateWmsCountLine(countDetail.id, line.id, {
        counted_quantity: line.counted_quantity,
        notes: line.notes || '',
      });
      message.success('盘点数量已保存');
      openCount(countDetail.id);
      load();
    } catch (e) {
      message.error(e.response?.data?.detail || '保存失败');
    }
  };

  const submitCountTask = async () => {
    try {
      await submitWmsCount(countDetail.id);
      message.success('盘点已提交');
      openCount(countDetail.id);
      load();
    } catch (e) {
      message.error(e.response?.data?.detail || '提交失败');
    }
  };

  const adjustCountTask = async () => {
    try {
      const { data } = await adjustWmsCount(countDetail.id);
      message.success(`已调整 ${data.adjusted} 行库存`);
      openCount(countDetail.id);
      load();
    } catch (e) {
      message.error(e.response?.data?.detail || '调整失败');
    }
  };

  const runStockMatch = async () => {
    const values = await matchForm.validateFields();
    try {
      const { data } = await matchWmsStock(values);
      setStockMatch(data);
    } catch (e) {
      message.error(e.response?.data?.detail || '自动选库存失败');
    }
  };

  const autoAllocate = async () => {
    const values = await matchForm.validateFields();
    if (!values.shipment_id) {
      message.warning('需要先选择发货单');
      return;
    }
    try {
      const { data } = await autoAllocateWmsShipment(values.shipment_id, { warehouse_id: values.warehouse_id });
      message.success(`已生成 ${data.created} 条发货明细`);
      runStockMatch();
    } catch (e) {
      message.error(e.response?.data?.detail || '生成发货明细失败');
    }
  };

  const loadReport = async (name) => {
    const params = {};
    if (name.includes('daily')) params.date = reportDate.format('YYYY-MM-DD');
    const { data } = await getWmsReport(name, params);
    setReport({ name, ...data });
  };

  const applyAuditFilters = async () => {
    const values = await auditForm.validateFields();
    const filters = { ...EMPTY_AUDIT_FILTERS, ...values };
    setAuditFilters(filters);
    loadAudit(filters);
  };

  const resetAuditFilters = () => {
    auditForm.resetFields();
    setAuditFilters(EMPTY_AUDIT_FILTERS);
    loadAudit(EMPTY_AUDIT_FILTERS);
  };

  const filterAuditByCommand = (commandLogId) => {
    const filters = { ...auditFilters, command_log_id: commandLogId };
    auditForm.setFieldsValue({ command_log_id: commandLogId });
    setAuditFilters(filters);
    loadAudit(filters);
  };

  const inventoryColumns = [
    { title: '入仓编号', dataIndex: 'inbound_number', fixed: 'left', width: 130 },
    { title: '型号', dataIndex: 'material', width: 160 },
    { title: 'SN/LOT#', dataIndex: 'serial_lot_number', width: 160 },
    { title: '供应商', dataIndex: 'supplier', width: 130 },
    { title: '性质', dataIndex: 'goods_nature', width: 90 },
    { title: '数量', dataIndex: 'quantity', width: 90, align: 'right', render: n },
    { title: '已预留', dataIndex: 'reserved_quantity', width: 90, align: 'right', render: n },
    { title: '可用', dataIndex: 'available_quantity', width: 90, align: 'right', render: n },
    { title: '单位成本', dataIndex: 'unit_cost', width: 100, align: 'right', render: v => v == null ? '' : n(v) },
    { title: '库存成本', dataIndex: 'total_cost', width: 110, align: 'right', render: v => v == null ? '' : n(v) },
    { title: '单位', dataIndex: 'uom', width: 80 },
    { title: '位置', dataIndex: 'location_code', width: 90 },
    { title: 'Date Code', dataIndex: 'date_code', width: 110 },
    { title: '生产日期', dataIndex: 'production_date', width: 120 },
    {
      title: '操作',
      key: 'action',
      fixed: 'right',
      width: 90,
      render: (_, row) => (
        <Button
          size="small"
          icon={<LockOutlined />}
          disabled={Number(row.available_quantity || 0) <= 0}
          onClick={() => openReserve(row)}
        >
          预留
        </Button>
      ),
    },
  ];

  const reservationColumns = [
    { title: '预留单号', dataIndex: 'reservation_number', width: 150 },
    { title: '入仓编号', dataIndex: 'inbound_number', width: 130 },
    { title: '型号', dataIndex: 'material', width: 150 },
    { title: 'SN/LOT#', dataIndex: 'serial_lot_number', width: 150 },
    { title: '客户', dataIndex: 'customer', width: 140 },
    { title: '销售订单', dataIndex: 'sales_order', width: 140 },
    { title: '数量', dataIndex: 'quantity', align: 'right', width: 90, render: n },
    { title: '预留时间', dataIndex: 'reserved_at', width: 170, render: v => v ? v.slice(0, 19).replace('T', ' ') : '' },
    {
      title: '操作',
      key: 'action',
      fixed: 'right',
      width: 100,
      render: (_, row) => (
        <Button size="small" icon={<UnlockOutlined />} onClick={() => releaseReservation(row)}>
          释放
        </Button>
      ),
    },
  ];

  const ruleColumns = [
    { title: '供应商', dataIndex: 'supplier', width: 160 },
    { title: '物料', dataIndex: 'material', width: 160, render: v => v || '全部物料' },
    { title: '规则名称', dataIndex: 'rule_name', width: 160 },
    { title: '固定长度', dataIndex: 'exact_length', width: 90 },
    { title: '最小', dataIndex: 'min_length', width: 80 },
    { title: '最大', dataIndex: 'max_length', width: 80 },
    { title: '正则', dataIndex: 'pattern', width: 180 },
    { title: '允许重复', dataIndex: 'allow_duplicate', width: 100, render: v => v ? '是' : '否' },
    { title: '唯一范围', dataIndex: 'unique_scope', width: 140 },
    { title: '启用', dataIndex: 'is_active', width: 80, render: v => v ? '是' : '否' },
  ];

  const policyColumns = [
    { title: '物料', dataIndex: 'material', width: 160 },
    { title: '仓库', dataIndex: 'warehouse', width: 130 },
    { title: '安全库存', dataIndex: 'safety_stock', width: 100, align: 'right', render: n },
    { title: '补货点', dataIndex: 'reorder_point', width: 100, align: 'right', render: n },
    { title: '最高库存', dataIndex: 'max_stock', width: 100, align: 'right', render: n },
    { title: '提前期', dataIndex: 'lead_time_days', width: 90, align: 'right', render: v => `${v || 0} 天` },
    { title: '启用', dataIndex: 'is_active', width: 80, render: v => v ? '是' : '否' },
    { title: '备注', dataIndex: 'notes', width: 180, ellipsis: true },
  ];

  const alertColumns = [
    {
      title: '级别',
      dataIndex: 'level',
      width: 90,
      render: v => <Tag color={v === 'critical' ? 'red' : v === 'warning' ? 'orange' : 'blue'}>{v}</Tag>,
    },
    { title: '状态', dataIndex: 'status', width: 120 },
    { title: '物料', dataIndex: 'material', width: 160 },
    { title: '仓库', dataIndex: 'warehouse', width: 130 },
    { title: '库存', dataIndex: 'quantity', width: 90, align: 'right', render: n },
    { title: '已预留', dataIndex: 'reserved_quantity', width: 90, align: 'right', render: n },
    { title: '可用', dataIndex: 'available_quantity', width: 90, align: 'right', render: n },
    { title: '安全库存', dataIndex: 'safety_stock', width: 100, align: 'right', render: n },
    { title: '补货点', dataIndex: 'reorder_point', width: 100, align: 'right', render: n },
  ];

  const countColumns = [
    { title: '盘点单号', dataIndex: 'count_number', width: 160 },
    { title: '仓库', dataIndex: 'warehouse', width: 130 },
    { title: '计划日期', dataIndex: 'planned_date', width: 110 },
    { title: '状态', dataIndex: 'status', width: 110, render: v => <Tag>{v}</Tag> },
    { title: '行数', dataIndex: 'line_count', width: 80, align: 'right', render: n },
    { title: '差异行', dataIndex: 'diff_count', width: 90, align: 'right', render: n },
    {
      title: '操作',
      key: 'action',
      fixed: 'right',
      width: 90,
      render: (_, row) => <Button size="small" onClick={() => openCount(row.id)}>明细</Button>,
    },
  ];

  const countLineColumns = [
    { title: '型号', dataIndex: 'material', width: 160 },
    { title: '仓库', dataIndex: 'warehouse', width: 120 },
    { title: '位置', dataIndex: 'location_code', width: 90 },
    { title: '入仓编号', dataIndex: 'inbound_number', width: 130 },
    { title: 'SN/LOT#', dataIndex: 'serial_lot_number', width: 150 },
    { title: '系统数', dataIndex: 'system_quantity', width: 90, align: 'right', render: n },
    {
      title: '实盘数',
      dataIndex: 'counted_quantity',
      width: 110,
      render: (_, row) => (
        <InputNumber
          min={0}
          value={row.counted_quantity}
          disabled={!['DRAFT', 'IN_PROGRESS'].includes(countDetail?.status)}
          onChange={(value) => {
            setCountDetail(prev => ({
              ...prev,
              lines: prev.lines.map(x => x.id === row.id ? {
                ...x,
                counted_quantity: value,
                difference_quantity: Number(value || 0) - Number(x.system_quantity || 0),
              } : x),
            }));
          }}
          style={{ width: '100%' }}
        />
      ),
    },
    { title: '差异', dataIndex: 'difference_quantity', width: 90, align: 'right', render: v => <Tag color={Number(v || 0) === 0 ? 'green' : 'orange'}>{n(v)}</Tag> },
    {
      title: '操作',
      key: 'action',
      fixed: 'right',
      width: 90,
      render: (_, row) => <Button size="small" onClick={() => saveCountLine(row)}>保存</Button>,
    },
  ];

  const stockMatchColumns = [
    { title: '行号', dataIndex: 'line_number', width: 70 },
    { title: '物料', dataIndex: 'material', width: 160 },
    { title: '需求', dataIndex: 'required_quantity', width: 90, align: 'right', render: n },
    { title: '已匹配', dataIndex: 'allocated_quantity', width: 90, align: 'right', render: n },
    { title: '缺口', dataIndex: 'missing_quantity', width: 90, align: 'right', render: v => <Tag color={Number(v || 0) > 0 ? 'red' : 'green'}>{n(v)}</Tag> },
    {
      title: '推荐库存',
      dataIndex: 'allocations',
      width: 360,
      render: rows => rows?.length ? rows.map(x => (
        <Tag key={x.inventory_id} style={{ marginBottom: 4 }}>
          {x.inbound_number || `#${x.inventory_id}`} / {x.serial_lot_number || '-'} / {n(x.allocated_quantity)}
        </Tag>
      )) : '-',
    },
    {
      title: '未采用库存',
      dataIndex: 'rejected',
      width: 260,
      render: rows => rows?.length ? rows.map(x => (
        <Tag key={x.inventory_id} color="orange" style={{ marginBottom: 4 }}>
          {x.inbound_number}: {x.reason}
        </Tag>
      )) : '-',
    },
  ];

  const commandAuditColumns = [
    { title: 'ID', dataIndex: 'id', width: 80 },
    { title: '命令', dataIndex: 'command_name', width: 220 },
    {
      title: '状态',
      dataIndex: 'status',
      width: 100,
      render: v => <Tag color={v === 'SUCCESS' ? 'green' : v === 'FAILED' ? 'red' : 'blue'}>{v}</Tag>,
    },
    { title: '操作人', dataIndex: 'actor', width: 140 },
    { title: '开始时间', dataIndex: 'created_at', width: 170, render: v => v ? v.slice(0, 19).replace('T', ' ') : '' },
    { title: '完成时间', dataIndex: 'completed_at', width: 170, render: v => v ? v.slice(0, 19).replace('T', ' ') : '' },
    { title: '失败原因', dataIndex: 'error_message', width: 260, ellipsis: true },
    {
      title: '操作',
      key: 'action',
      fixed: 'right',
      width: 90,
      render: (_, row) => <Button size="small" onClick={() => filterAuditByCommand(row.id)}>看流水</Button>,
    },
  ];

  const movementAuditColumns = [
    { title: '时间', dataIndex: 'created_at', width: 170, render: v => v ? v.slice(0, 19).replace('T', ' ') : '' },
    { title: '类型', dataIndex: 'movement_type', width: 150, render: v => <Tag>{v}</Tag> },
    { title: '物料', dataIndex: 'material', width: 160 },
    { title: '仓库', dataIndex: 'warehouse', width: 130 },
    { title: '入仓编号', dataIndex: 'inbound_number', width: 130 },
    { title: 'SN/LOT#', dataIndex: 'serial_lot_number', width: 150 },
    { title: '数量变化', dataIndex: 'quantity_delta', width: 110, align: 'right', render: v => <Tag color={Number(v || 0) < 0 ? 'red' : 'green'}>{n(v)}</Tag> },
    { title: '预留变化', dataIndex: 'reserved_delta', width: 110, align: 'right', render: v => <Tag color={Number(v || 0) < 0 ? 'orange' : 'blue'}>{n(v)}</Tag> },
    { title: '单位成本', dataIndex: 'unit_cost', width: 100, align: 'right', render: v => v == null ? '' : n(v) },
    { title: '来源', key: 'source', width: 190, render: (_, row) => `${row.source_doc_type || '-'}#${row.source_doc_id || '-'}` },
    { title: '命令', dataIndex: 'command_name', width: 190, ellipsis: true },
    { title: '操作人', dataIndex: 'created_by', width: 130 },
    { title: '备注', dataIndex: 'notes', width: 180, ellipsis: true },
  ];

  const reportColumns = report?.details?.[0]
    ? Object.keys(report.details[0]).map(key => ({
        title: key,
        dataIndex: key,
        key,
        width: key.includes('quantity') ? 110 : 150,
        ellipsis: true,
        align: key.includes('quantity') ? 'right' : undefined,
      }))
    : [];

  return (
    <div>
      <div style={{ marginBottom: 20 }}>
        <h2 style={{ margin: 0, color: '#000', fontSize: 28, fontWeight: 300, lineHeight: 1.15 }}>
          WMS 一期工作台
        </h2>
        <div style={{ color: '#777169', marginTop: 6, fontSize: 13 }}>
          包装级库存、客户预留、SN/LOT 校验和仓库报表
        </div>
      </div>

      <Row gutter={[12, 12]} style={{ marginBottom: 16 }}>
        <Col xs={12} md={6}><Metric title="库存包装数" value={summary?.inventory_count} /></Col>
        <Col xs={12} md={6}><Metric title="库存总量" value={summary?.total_quantity} /></Col>
        <Col xs={12} md={6}><Metric title="已预留" value={summary?.reserved_quantity} /></Col>
        <Col xs={12} md={6}><Metric title="可用库存" value={summary?.available_quantity} /></Col>
      </Row>
      {alerts.length > 0 && (
        <Alert
          type="warning"
          showIcon
          icon={<WarningOutlined />}
          style={{ marginBottom: 16 }}
          message={`当前有 ${alerts.length} 条库存预警`}
        />
      )}

      <Tabs
        items={[
          {
            key: 'inventory',
            label: '库存与预留',
            children: (
              <Card style={{ borderRadius: 8, border: 'none', boxShadow: CARD_SHADOW }}>
                <Space style={{ marginBottom: 12 }} wrap>
                  <Input.Search
                    placeholder="型号 / 入仓编号 / SN/LOT / 运单号"
                    value={search}
                    onChange={e => setSearch(e.target.value)}
                    onSearch={load}
                    allowClear
                    style={{ width: 300 }}
                  />
                  <Button icon={<ReloadOutlined />} onClick={load} loading={loading}>刷新</Button>
                  <Upload
                    showUploadList={false}
                    customRequest={async ({ file, onSuccess, onError }) => {
                      const fd = new FormData();
                      fd.append('file', file);
                      try {
                        const { data } = await importWmsInventoryCsv(fd);
                        if (data.success) {
                          message.success(`导入 ${data.inserted} 条库存`);
                          load();
                          onSuccess?.(data);
                        } else {
                          message.error(`导入失败：第 ${data.errors?.[0]?.row} 行 ${data.errors?.[0]?.error}`);
                          onError?.(new Error('import failed'));
                        }
                      } catch (e) {
                        message.error('导入失败');
                        onError?.(e);
                      }
                    }}
                  >
                    <Button icon={<CloudUploadOutlined />}>导入库存 CSV</Button>
                  </Upload>
                  <Button icon={<DownloadOutlined />} onClick={() => window.open(csvUrl('inventory-summary'), '_blank')}>
                    导出库存表
                  </Button>
                </Space>
                <Table
                  rowKey="id"
                  dataSource={inventory}
                  columns={inventoryColumns}
                  loading={loading}
                  size="small"
                  scroll={{ x: 'max-content' }}
                  pagination={{ pageSize: 50 }}
                />
                <div style={{ marginTop: 20, fontWeight: 500 }}>当前有效预留</div>
                <Table
                  rowKey="id"
                  dataSource={reservations}
                  columns={reservationColumns}
                  size="small"
                  scroll={{ x: 'max-content' }}
                  pagination={{ pageSize: 20 }}
                  style={{ marginTop: 10 }}
                />
              </Card>
            ),
          },
          {
            key: 'policies',
            label: '策略与预警',
            children: (
              <Row gutter={[16, 16]}>
                <Col xs={24} lg={8}>
                  <Card title="库存策略" style={{ borderRadius: 8, border: 'none', boxShadow: CARD_SHADOW }}>
                    <Form
                      form={policyForm}
                      layout="vertical"
                      initialValues={{ safety_stock: 0, reorder_point: 0, max_stock: 0, lead_time_days: 0, is_active: true }}
                    >
                      <Form.Item name="material_id" label="物料" rules={[{ required: true }]}>
                        <Select showSearch optionFilterProp="label" options={materialOptions} />
                      </Form.Item>
                      <Form.Item name="warehouse_id" label="仓库">
                        <Select allowClear showSearch optionFilterProp="label" options={warehouseOptions} />
                      </Form.Item>
                      <Row gutter={8}>
                        <Col span={8}><Form.Item name="safety_stock" label="安全库存"><InputNumber min={0} style={{ width: '100%' }} /></Form.Item></Col>
                        <Col span={8}><Form.Item name="reorder_point" label="补货点"><InputNumber min={0} style={{ width: '100%' }} /></Form.Item></Col>
                        <Col span={8}><Form.Item name="max_stock" label="最高库存"><InputNumber min={0} style={{ width: '100%' }} /></Form.Item></Col>
                      </Row>
                      <Form.Item name="lead_time_days" label="采购提前期">
                        <InputNumber min={0} style={{ width: '100%' }} />
                      </Form.Item>
                      <Form.Item name="is_active" label="启用">
                        <Select options={[{ value: true, label: '启用' }, { value: false, label: '停用' }]} />
                      </Form.Item>
                      <Form.Item name="notes" label="备注">
                        <Input.TextArea rows={2} />
                      </Form.Item>
                      <Button type="primary" icon={<WarningOutlined />} onClick={savePolicy}>保存策略</Button>
                    </Form>
                  </Card>
                </Col>
                <Col xs={24} lg={16}>
                  <Card title="库存预警" style={{ borderRadius: 8, border: 'none', boxShadow: CARD_SHADOW }}>
                    <Table
                      rowKey={row => `${row.policy_id}-${row.status}`}
                      dataSource={alerts}
                      columns={alertColumns}
                      size="small"
                      scroll={{ x: 'max-content' }}
                      pagination={{ pageSize: 10 }}
                    />
                  </Card>
                  <Card title="策略列表" style={{ marginTop: 16, borderRadius: 8, border: 'none', boxShadow: CARD_SHADOW }}>
                    <Table
                      rowKey="id"
                      dataSource={policies}
                      columns={policyColumns}
                      size="small"
                      scroll={{ x: 'max-content' }}
                      pagination={{ pageSize: 10 }}
                    />
                  </Card>
                </Col>
              </Row>
            ),
          },
          {
            key: 'match',
            label: '自动选库存',
            children: (
              <Card style={{ borderRadius: 8, border: 'none', boxShadow: CARD_SHADOW }}>
                <Form form={matchForm} layout="inline" style={{ marginBottom: 12 }}>
                  <Form.Item name="shipment_id" label="发货单">
                    <Select allowClear showSearch optionFilterProp="label" options={shipmentOptions} style={{ width: 220 }} />
                  </Form.Item>
                  <Form.Item name="sales_order_id" label="销售订单">
                    <Select allowClear showSearch optionFilterProp="label" options={salesOrderOptions} style={{ width: 220 }} />
                  </Form.Item>
                  <Form.Item name="warehouse_id" label="仓库">
                    <Select allowClear showSearch optionFilterProp="label" options={warehouseOptions} style={{ width: 180 }} />
                  </Form.Item>
                  <Form.Item>
                    <Space>
                      <Button type="primary" icon={<FileSearchOutlined />} onClick={runStockMatch}>匹配库存</Button>
                      <Button icon={<ThunderboltOutlined />} onClick={autoAllocate}>生成发货明细</Button>
                    </Space>
                  </Form.Item>
                </Form>
                {stockMatch ? (
                  <>
                    {stockMatch.barcode_requirements && (
                      <Alert
                        type="info"
                        showIcon
                        style={{ marginBottom: 12 }}
                        message="条码要求"
                        description={stockMatch.barcode_requirements}
                      />
                    )}
                    <Table
                      rowKey="sales_order_line_id"
                      dataSource={stockMatch.lines || []}
                      columns={stockMatchColumns}
                      size="small"
                      scroll={{ x: 'max-content' }}
                      pagination={false}
                    />
                  </>
                ) : (
                  <Empty description="选择销售订单或发货单后匹配库存" />
                )}
              </Card>
            ),
          },
          {
            key: 'counts',
            label: '库存盘点',
            children: (
              <Row gutter={[16, 16]}>
                <Col xs={24} lg={8}>
                  <Card title="新建盘点" style={{ borderRadius: 8, border: 'none', boxShadow: CARD_SHADOW }}>
                    <Form form={countForm} layout="vertical" initialValues={{ planned_date: dayjs() }}>
                      <Form.Item name="warehouse_id" label="仓库">
                        <Select allowClear showSearch optionFilterProp="label" options={warehouseOptions} />
                      </Form.Item>
                      <Form.Item name="planned_date" label="计划日期">
                        <DatePicker style={{ width: '100%' }} />
                      </Form.Item>
                      <Form.Item name="notes" label="备注">
                        <Input.TextArea rows={2} />
                      </Form.Item>
                      <Button type="primary" icon={<CheckSquareOutlined />} onClick={createCount}>创建盘点任务</Button>
                    </Form>
                  </Card>
                  <Card title="盘点任务" style={{ marginTop: 16, borderRadius: 8, border: 'none', boxShadow: CARD_SHADOW }}>
                    <Table
                      rowKey="id"
                      dataSource={counts}
                      columns={countColumns}
                      size="small"
                      scroll={{ x: 'max-content' }}
                      pagination={{ pageSize: 8 }}
                    />
                  </Card>
                </Col>
                <Col xs={24} lg={16}>
                  <Card
                    title={countDetail ? `盘点明细 ${countDetail.count_number}` : '盘点明细'}
                    extra={countDetail && (
                      <Space>
                        <Tag>{countDetail.status}</Tag>
                        <Button size="small" disabled={!['DRAFT', 'IN_PROGRESS'].includes(countDetail.status)} onClick={submitCountTask}>提交</Button>
                        <Button size="small" disabled={countDetail.status !== 'SUBMITTED'} onClick={adjustCountTask}>调整库存</Button>
                      </Space>
                    )}
                    style={{ borderRadius: 8, border: 'none', boxShadow: CARD_SHADOW }}
                  >
                    {countDetail ? (
                      <Table
                        rowKey="id"
                        dataSource={countDetail.lines || []}
                        columns={countLineColumns}
                        size="small"
                        scroll={{ x: 'max-content' }}
                        pagination={{ pageSize: 30 }}
                      />
                    ) : (
                      <Empty description="选择或创建一个盘点任务" />
                    )}
                  </Card>
                </Col>
              </Row>
            ),
          },
          {
            key: 'rules',
            label: 'SN/LOT 规则',
            children: (
              <Row gutter={[16, 16]}>
                <Col xs={24} lg={9}>
                  <Card title="新增/更新规则" style={{ borderRadius: 8, border: 'none', boxShadow: CARD_SHADOW }}>
                    <Form form={ruleForm} layout="vertical" initialValues={{ allow_duplicate: false, unique_scope: 'SUPPLIER_MATERIAL', is_active: true }}>
                      <Form.Item name="supplier_id" label="供应商" rules={[{ required: true }]}>
                        <Select showSearch optionFilterProp="label" options={supplierOptions} />
                      </Form.Item>
                      <Form.Item name="material_id" label="物料">
                        <Select allowClear showSearch optionFilterProp="label" options={materialOptions} />
                      </Form.Item>
                      <Form.Item name="rule_name" label="规则名称">
                        <Input placeholder="如 LUMENTUM SN 14位" />
                      </Form.Item>
                      <Row gutter={8}>
                        <Col span={8}><Form.Item name="exact_length" label="固定长度"><InputNumber style={{ width: '100%' }} /></Form.Item></Col>
                        <Col span={8}><Form.Item name="min_length" label="最小"><InputNumber style={{ width: '100%' }} /></Form.Item></Col>
                        <Col span={8}><Form.Item name="max_length" label="最大"><InputNumber style={{ width: '100%' }} /></Form.Item></Col>
                      </Row>
                      <Form.Item name="pattern" label="正则规则">
                        <Input placeholder="例如 [A-Z0-9]{14}" />
                      </Form.Item>
                      <Form.Item name="allow_duplicate" label="允许重复">
                        <Select options={[{ value: false, label: '不允许重复' }, { value: true, label: '允许重复' }]} />
                      </Form.Item>
                      <Form.Item name="unique_scope" label="唯一性范围">
                        <Select options={[
                          { value: 'SUPPLIER_MATERIAL', label: '同供应商+物料' },
                          { value: 'SUPPLIER', label: '同供应商' },
                          { value: 'MATERIAL', label: '同物料' },
                          { value: 'GLOBAL', label: '全库' },
                        ]} />
                      </Form.Item>
                      <Form.Item name="is_active" label="启用">
                        <Select options={[{ value: true, label: '启用' }, { value: false, label: '停用' }]} />
                      </Form.Item>
                      <Button type="primary" icon={<SafetyCertificateOutlined />} onClick={saveRule}>保存规则</Button>
                    </Form>
                  </Card>
                  <Card title="快速校验" style={{ marginTop: 16, borderRadius: 8, border: 'none', boxShadow: CARD_SHADOW }}>
                    <Form form={snCheckForm} layout="vertical">
                      <Form.Item name="supplier_id" label="供应商" rules={[{ required: true }]}>
                        <Select showSearch optionFilterProp="label" options={supplierOptions} />
                      </Form.Item>
                      <Form.Item name="material_id" label="物料">
                        <Select allowClear showSearch optionFilterProp="label" options={materialOptions} />
                      </Form.Item>
                      <Form.Item name="serial_lot_number" label="SN/LOT#" rules={[{ required: true }]}>
                        <Input />
                      </Form.Item>
                      <Button onClick={validateSn}>校验</Button>
                    </Form>
                  </Card>
                </Col>
                <Col xs={24} lg={15}>
                  <Card title="规则列表" style={{ borderRadius: 8, border: 'none', boxShadow: CARD_SHADOW }}>
                    <Table rowKey="id" dataSource={rules} columns={ruleColumns} size="small" scroll={{ x: 'max-content' }} />
                  </Card>
                </Col>
              </Row>
            ),
          },
          {
            key: 'audit',
            label: '审计与流水',
            children: (
              <Row gutter={[16, 16]}>
                <Col xs={24}>
                  <Card title="审计筛选" style={{ borderRadius: 8, border: 'none', boxShadow: CARD_SHADOW }}>
                    <Form form={auditForm} layout="inline">
                      <Form.Item name="movement_type" label="流水类型">
                        <Select
                          allowClear
                          options={MOVEMENT_TYPE_OPTIONS}
                          style={{ width: 160 }}
                        />
                      </Form.Item>
                      <Form.Item name="material_id" label="物料">
                        <Select
                          allowClear
                          showSearch
                          optionFilterProp="label"
                          options={materialOptions}
                          style={{ width: 200 }}
                        />
                      </Form.Item>
                      <Form.Item name="inventory_id" label="库存ID">
                        <InputNumber min={1} style={{ width: 120 }} />
                      </Form.Item>
                      <Form.Item name="command_log_id" label="命令ID">
                        <InputNumber min={1} style={{ width: 120 }} />
                      </Form.Item>
                      <Form.Item name="command_name" label="命令">
                        <Input allowClear style={{ width: 180 }} />
                      </Form.Item>
                      <Form.Item name="status" label="状态">
                        <Select
                          allowClear
                          options={[
                            { value: 'SUCCESS', label: '成功' },
                            { value: 'FAILED', label: '失败' },
                            { value: 'RUNNING', label: '执行中' },
                          ]}
                          style={{ width: 120 }}
                        />
                      </Form.Item>
                      <Form.Item>
                        <Space>
                          <Button type="primary" icon={<FileSearchOutlined />} onClick={applyAuditFilters}>筛选</Button>
                          <Button onClick={resetAuditFilters}>重置</Button>
                        </Space>
                      </Form.Item>
                    </Form>
                  </Card>
                </Col>
                <Col xs={24}>
                  <Card
                    title="库存事实流水"
                    extra={<Button size="small" icon={<ReloadOutlined />} onClick={() => loadAudit()}>刷新</Button>}
                    style={{ borderRadius: 8, border: 'none', boxShadow: CARD_SHADOW }}
                  >
                    <Table
                      rowKey="id"
                      dataSource={movementAudit}
                      columns={movementAuditColumns}
                      size="small"
                      scroll={{ x: 'max-content' }}
                      pagination={{ pageSize: 50 }}
                    />
                  </Card>
                </Col>
                <Col xs={24}>
                  <Card title="命令执行日志" style={{ borderRadius: 8, border: 'none', boxShadow: CARD_SHADOW }}>
                    <Table
                      rowKey="id"
                      dataSource={commandAudit}
                      columns={commandAuditColumns}
                      size="small"
                      scroll={{ x: 'max-content' }}
                      pagination={{ pageSize: 30 }}
                    />
                  </Card>
                </Col>
              </Row>
            ),
          },
          {
            key: 'reports',
            label: '报表',
            children: (
              <Card style={{ borderRadius: 8, border: 'none', boxShadow: CARD_SHADOW }}>
                <Space style={{ marginBottom: 12 }} wrap>
                  <DatePicker value={reportDate} onChange={v => setReportDate(v || dayjs())} />
                  <Button onClick={() => loadReport('inbound-daily')}>入库日报</Button>
                  <Button onClick={() => loadReport('outbound-daily')}>出库日报</Button>
                  <Button onClick={() => loadReport('inventory-summary')}>库存总表</Button>
                  <Button onClick={() => loadReport('count-sheet')}>盘点表</Button>
                  <Button
                    icon={<DownloadOutlined />}
                    disabled={!report}
                    onClick={() => {
                      const params = report?.name?.includes('daily') ? { date: reportDate.format('YYYY-MM-DD') } : {};
                      window.open(csvUrl(report.name, params), '_blank');
                    }}
                  >
                    导出当前报表
                  </Button>
                </Space>
                {report ? (
                  <>
                    {report.summary && (
                      <Table
                        rowKey="group"
                        dataSource={report.summary}
                        columns={[
                          { title: '分组', dataIndex: 'group' },
                          { title: '数量', dataIndex: 'quantity', align: 'right', render: n },
                        ]}
                        size="small"
                        pagination={false}
                        style={{ marginBottom: 14, maxWidth: 520 }}
                      />
                    )}
                    <Table
                      rowKey={(_, i) => i}
                      dataSource={report.details || []}
                      columns={reportColumns}
                      size="small"
                      scroll={{ x: 'max-content' }}
                      pagination={{ pageSize: 50 }}
                    />
                  </>
                ) : (
                  <Empty description="选择一个报表" />
                )}
              </Card>
            ),
          },
        ]}
      />

      <Modal
        title="库存预留"
        open={reserveOpen}
        onOk={submitReserve}
        onCancel={() => setReserveOpen(false)}
        okText="确认预留"
      >
        {selectedInventory && (
          <Alert
            type="info"
            showIcon
            style={{ marginBottom: 12 }}
            message={`${selectedInventory.material} / ${selectedInventory.inbound_number}`}
            description={`可用数量：${n(selectedInventory.available_quantity)} ${selectedInventory.uom || ''}`}
          />
        )}
        <Form form={reserveForm} layout="vertical">
          <Form.Item name="inventory_id" hidden><Input /></Form.Item>
          <Form.Item name="customer_id" label="预留客户" rules={[{ required: true }]}>
            <Select showSearch optionFilterProp="label" options={customerOptions} />
          </Form.Item>
          <Form.Item name="sales_order_id" label="关联销售订单">
            <Select allowClear showSearch optionFilterProp="label" options={salesOrderOptions} />
          </Form.Item>
          <Form.Item name="quantity" label="预留数量" rules={[{ required: true }]}>
            <InputNumber min={0} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="notes" label="备注">
            <Input.TextArea rows={2} />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
