import { useEffect, useMemo, useState } from 'react';
import {
  Button, Card, DatePicker, Drawer, Form, Input, InputNumber, Popconfirm, Select, Space,
  Table, Tabs, Tag, Typography, message,
} from 'antd';
import { FileSearchOutlined, ReloadOutlined } from '@ant-design/icons';
import {
  getCommandCatalog, getCommandDetail, getCommandFailureSummary,
  getCommandInventoryMovements, getCommandLogs, retryCommandLog,
} from '../api';

const CARD_SHADOW =
  'rgba(0,0,0,0.06) 0px 0px 0px 1px, rgba(0,0,0,0.04) 0px 1px 2px, rgba(0,0,0,0.04) 0px 2px 4px';

const EMPTY_FILTERS = {
  command_module: undefined,
  command_name: '',
  status: undefined,
  actor_id: undefined,
  company_id: undefined,
  idempotency_key: '',
  date_range: undefined,
};

function n(value) {
  return Number(value || 0).toLocaleString();
}

function fmt(value) {
  return value ? value.slice(0, 19).replace('T', ' ') : '';
}

function payloadText(value) {
  if (!value || Object.keys(value).length === 0) return '{}';
  return JSON.stringify(value, null, 2);
}

export default function CommandCenter() {
  const [logs, setLogs] = useState([]);
  const [detail, setDetail] = useState(null);
  const [catalog, setCatalog] = useState([]);
  const [failures, setFailures] = useState([]);
  const [movements, setMovements] = useState([]);
  const [loading, setLoading] = useState(false);
  const [failureLoading, setFailureLoading] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [filters, setFilters] = useState(EMPTY_FILTERS);
  const [form] = Form.useForm();
  const watchedModule = Form.useWatch('command_module', form);

  const moduleOptions = useMemo(() => (
    [...new Set(catalog.map(item => item.module))]
      .filter(Boolean)
      .sort()
      .map(module => ({ value: module, label: module }))
  ), [catalog]);

  const commandOptions = useMemo(() => (
    catalog
      .filter(item => !watchedModule || item.module === watchedModule)
      .map(item => ({ value: item.name, label: `${item.title} (${item.name})` }))
  ), [catalog, watchedModule]);

  const buildParams = (nextFilters, limit) => {
    const params = { limit };
    if (nextFilters.command_module) params.command_module = nextFilters.command_module;
    if (nextFilters.command_name) params.command_name = nextFilters.command_name;
    if (nextFilters.status) params.status = nextFilters.status;
    if (nextFilters.actor_id) params.actor_id = nextFilters.actor_id;
    if (nextFilters.company_id) params.company_id = nextFilters.company_id;
    if (nextFilters.idempotency_key) params.idempotency_key = nextFilters.idempotency_key;
    if (nextFilters.date_range?.[0]) params.date_from = nextFilters.date_range[0].startOf('day').format('YYYY-MM-DDTHH:mm:ss');
    if (nextFilters.date_range?.[1]) params.date_to = nextFilters.date_range[1].endOf('day').format('YYYY-MM-DDTHH:mm:ss');
    return params;
  };

  const loadFailures = async (nextFilters = filters) => {
    setFailureLoading(true);
    try {
      const params = buildParams(nextFilters, 1000);
      delete params.command_name;
      delete params.status;
      delete params.actor_id;
      delete params.company_id;
      delete params.idempotency_key;
      const { data } = await getCommandFailureSummary(params);
      setFailures(data.data || []);
    } catch (e) {
      message.error(e.response?.data?.detail || '失败聚合加载失败');
    } finally {
      setFailureLoading(false);
    }
  };

  const load = async (nextFilters = filters) => {
    setLoading(true);
    try {
      const params = buildParams(nextFilters, 150);
      const { data } = await getCommandLogs(params);
      setLogs(data.data || []);
    } catch (e) {
      message.error(e.response?.data?.detail || '命令日志加载失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    getCommandCatalog()
      .then(r => setCatalog(r.data.data || []))
      .catch(() => message.error('命令目录加载失败'));
    load(EMPTY_FILTERS);
    loadFailures(EMPTY_FILTERS);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const applyFilters = async () => {
    const values = await form.validateFields();
    const nextFilters = { ...EMPTY_FILTERS, ...values };
    setFilters(nextFilters);
    load(nextFilters);
    loadFailures(nextFilters);
  };

  const resetFilters = () => {
    form.resetFields();
    setFilters(EMPTY_FILTERS);
    load(EMPTY_FILTERS);
    loadFailures(EMPTY_FILTERS);
  };

  const openDetail = async (row) => {
    try {
      const [detailResp, movementResp] = await Promise.all([
        getCommandDetail(row.id),
        getCommandInventoryMovements(row.id),
      ]);
      setDetail(detailResp.data);
      setMovements(movementResp.data.data || []);
      setDrawerOpen(true);
    } catch (e) {
      message.error(e.response?.data?.detail || '命令详情加载失败');
    }
  };

  const retryCommand = async (commandLogId) => {
    try {
      const { data } = await retryCommandLog(commandLogId);
      if (data.success) {
        message.success(`重试成功，新命令 #${data.command_log_id}`);
        load(filters);
        loadFailures(filters);
        if (data.command_log_id) {
          openDetail({ id: data.command_log_id });
        }
      } else {
        message.error(data.error || '重试失败');
        load(filters);
        loadFailures(filters);
      }
    } catch (e) {
      message.error(e.response?.data?.detail || '重试失败');
    }
  };

  const logColumns = [
    { title: 'ID', dataIndex: 'id', width: 80, fixed: 'left' },
    { title: '模块', dataIndex: 'command_module', width: 100, render: v => <Tag>{v}</Tag> },
    {
      title: '命令',
      dataIndex: 'command_name',
      width: 260,
      render: (_, row) => (
        <Space direction="vertical" size={0}>
          <Typography.Text>{row.command_title || row.command_name}</Typography.Text>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>{row.command_name}</Typography.Text>
        </Space>
      ),
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 100,
      render: v => <Tag color={v === 'SUCCESS' ? 'green' : v === 'FAILED' ? 'red' : 'blue'}>{v}</Tag>,
    },
    { title: '操作人', dataIndex: 'actor', width: 140 },
    { title: '公司', dataIndex: 'company', width: 140 },
    { title: '幂等键', dataIndex: 'idempotency_key', width: 220, ellipsis: true },
    {
      title: '影响表',
      dataIndex: 'affected_tables',
      width: 240,
      render: rows => rows?.length ? rows.slice(0, 4).map(name => <Tag key={name}>{name}</Tag>) : '-',
    },
    { title: '开始时间', dataIndex: 'created_at', width: 170, render: fmt },
    { title: '完成时间', dataIndex: 'completed_at', width: 170, render: fmt },
    { title: '失败原因', dataIndex: 'error_message', width: 260, ellipsis: true },
    {
      title: '操作',
      key: 'action',
      fixed: 'right',
      width: 150,
      render: (_, row) => (
        <Space>
          <Button size="small" onClick={() => openDetail(row)}>详情</Button>
          {row.status === 'FAILED' && row.supports_retry && (
            <Popconfirm
              title="确认重试这个失败命令？"
              okText="重试"
              cancelText="取消"
              onConfirm={() => retryCommand(row.id)}
            >
              <Button size="small" type="primary">重试</Button>
            </Popconfirm>
          )}
        </Space>
      ),
    },
  ];

  const failureColumns = [
    { title: '模块', dataIndex: 'command_module', width: 100, render: v => <Tag>{v}</Tag> },
    {
      title: '命令',
      dataIndex: 'command_name',
      width: 260,
      render: (_, row) => (
        <Space direction="vertical" size={0}>
          <Typography.Text>{row.command_title || row.command_name}</Typography.Text>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>{row.command_name}</Typography.Text>
        </Space>
      ),
    },
    { title: '失败次数', dataIndex: 'failed_count', width: 100, align: 'right', render: n },
    { title: '最近失败', dataIndex: 'last_failed_at', width: 170, render: fmt },
    { title: '最近错误', dataIndex: 'last_error_message', width: 320, ellipsis: true },
    {
      title: '重试',
      key: 'retry',
      fixed: 'right',
      width: 90,
      render: (_, row) => row.supports_retry && row.last_command_log_id ? (
        <Popconfirm
          title="确认重试最近一次失败命令？"
          okText="重试"
          cancelText="取消"
          onConfirm={() => retryCommand(row.last_command_log_id)}
        >
          <Button size="small" type="primary">重试</Button>
        </Popconfirm>
      ) : <Tag>未开放</Tag>,
    },
  ];

  const movementColumns = [
    { title: '时间', dataIndex: 'created_at', width: 170, render: fmt },
    { title: '类型', dataIndex: 'movement_type', width: 150, render: v => <Tag>{v}</Tag> },
    { title: '物料', dataIndex: 'material', width: 160 },
    { title: '仓库', dataIndex: 'warehouse', width: 130 },
    { title: '库存ID', dataIndex: 'inventory_id', width: 90 },
    { title: '入仓编号', dataIndex: 'inbound_number', width: 130 },
    { title: 'SN/LOT#', dataIndex: 'serial_lot_number', width: 150 },
    { title: '数量变化', dataIndex: 'quantity_delta', width: 110, align: 'right', render: v => <Tag color={Number(v || 0) < 0 ? 'red' : 'green'}>{n(v)}</Tag> },
    { title: '预留变化', dataIndex: 'reserved_delta', width: 110, align: 'right', render: v => <Tag color={Number(v || 0) < 0 ? 'orange' : 'blue'}>{n(v)}</Tag> },
    { title: '来源', key: 'source', width: 190, render: (_, row) => `${row.source_doc_type || '-'}#${row.source_doc_id || '-'}` },
    { title: '操作人', dataIndex: 'created_by', width: 130 },
    { title: '备注', dataIndex: 'notes', width: 180, ellipsis: true },
  ];

  const drawerItems = detail ? [
    {
      key: 'summary',
      label: '摘要',
      children: (
        <Space direction="vertical" size={10} style={{ width: '100%' }}>
          <Typography.Text>ID：{detail.id}</Typography.Text>
          <Typography.Text>模块：{detail.command_module || '-'}</Typography.Text>
          <Typography.Text>命令：{detail.command_title || detail.command_name} ({detail.command_name})</Typography.Text>
          {detail.command_description && <Typography.Text>说明：{detail.command_description}</Typography.Text>}
          <Typography.Text>状态：<Tag color={detail.status === 'SUCCESS' ? 'green' : detail.status === 'FAILED' ? 'red' : 'blue'}>{detail.status}</Tag></Typography.Text>
          <Typography.Text>操作人：{detail.actor || '-'}</Typography.Text>
          <Typography.Text>公司：{detail.company || '-'}</Typography.Text>
          <Typography.Text>幂等键：{detail.idempotency_key || '-'}</Typography.Text>
          <Typography.Text>开始时间：{fmt(detail.created_at)}</Typography.Text>
          <Typography.Text>完成时间：{fmt(detail.completed_at)}</Typography.Text>
          <div>
            影响表：{detail.affected_tables?.length ? detail.affected_tables.map(name => <Tag key={name}>{name}</Tag>) : '-'}
          </div>
          <div>
            能力：
            <Tag color={detail.supports_retry ? 'green' : undefined}>重试 {detail.supports_retry ? '支持' : '未开放'}</Tag>
            <Tag color={detail.supports_rollback ? 'green' : undefined}>回滚 {detail.supports_rollback ? '支持' : '未开放'}</Tag>
            <Tag color={detail.supports_preview ? 'green' : undefined}>预览 {detail.supports_preview ? '支持' : '未开放'}</Tag>
          </div>
          {detail.error_message && <Typography.Text type="danger">失败原因：{detail.error_message}</Typography.Text>}
        </Space>
      ),
    },
    {
      key: 'payload',
      label: '载荷',
      children: (
        <Tabs
          items={[
            {
              key: 'request',
              label: '请求',
              children: <pre style={{ margin: 0, whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>{payloadText(detail.request_payload)}</pre>,
            },
            {
              key: 'result',
              label: '结果',
              children: <pre style={{ margin: 0, whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>{payloadText(detail.result_payload)}</pre>,
            },
          ]}
        />
      ),
    },
    {
      key: 'movements',
      label: `库存流水 ${movements.length}`,
      children: (
        <Table
          rowKey="id"
          dataSource={movements}
          columns={movementColumns}
          size="small"
          scroll={{ x: 'max-content' }}
          pagination={{ pageSize: 30 }}
        />
      ),
    },
  ] : [];

  return (
    <div>
      <div style={{ marginBottom: 20 }}>
        <h2 style={{ margin: 0, color: '#000', fontSize: 28, fontWeight: 300, lineHeight: 1.15 }}>
          命令中心
        </h2>
        <div style={{ color: '#777169', marginTop: 6, fontSize: 13 }}>
          跨 ERP/WMS/CRM 的写操作日志、幂等键和事实流水
        </div>
      </div>

      <Card style={{ borderRadius: 8, border: 'none', boxShadow: CARD_SHADOW, marginBottom: 16 }}>
        <Form form={form} layout="inline">
          <Form.Item name="command_module" label="模块">
            <Select
              allowClear
              options={moduleOptions}
              style={{ width: 120 }}
              onChange={() => form.setFieldValue('command_name', undefined)}
            />
          </Form.Item>
          <Form.Item name="command_name" label="命令">
            <Select
              allowClear
              showSearch
              optionFilterProp="label"
              options={commandOptions}
              style={{ width: 250 }}
            />
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
          <Form.Item name="actor_id" label="操作人ID">
            <InputNumber min={1} style={{ width: 120 }} />
          </Form.Item>
          <Form.Item name="company_id" label="公司ID">
            <InputNumber min={1} style={{ width: 110 }} />
          </Form.Item>
          <Form.Item name="idempotency_key" label="幂等键">
            <Input allowClear style={{ width: 190 }} />
          </Form.Item>
          <Form.Item name="date_range" label="时间">
            <DatePicker.RangePicker allowClear style={{ width: 250 }} />
          </Form.Item>
          <Form.Item>
            <Space>
              <Button type="primary" icon={<FileSearchOutlined />} onClick={applyFilters}>筛选</Button>
              <Button onClick={resetFilters}>重置</Button>
              <Button icon={<ReloadOutlined />} onClick={() => load()}>刷新</Button>
            </Space>
          </Form.Item>
        </Form>
      </Card>

      <Card
        title="失败聚合"
        style={{ borderRadius: 8, border: 'none', boxShadow: CARD_SHADOW, marginBottom: 16 }}
      >
        <Table
          rowKey={row => `${row.command_module}-${row.command_name}`}
          dataSource={failures}
          columns={failureColumns}
          loading={failureLoading}
          size="small"
          scroll={{ x: 'max-content' }}
          pagination={{ pageSize: 8 }}
        />
      </Card>

      <Card title="命令日志" style={{ borderRadius: 8, border: 'none', boxShadow: CARD_SHADOW }}>
        <Table
          rowKey="id"
          dataSource={logs}
          columns={logColumns}
          loading={loading}
          size="small"
          scroll={{ x: 'max-content' }}
          pagination={{ pageSize: 50 }}
        />
      </Card>

      <Drawer
        title={detail ? `命令详情 #${detail.id}` : '命令详情'}
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        width={900}
      >
        <Tabs items={drawerItems} />
      </Drawer>
    </div>
  );
}
