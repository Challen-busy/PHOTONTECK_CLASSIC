/**
 * 流程管理 — 三栏布局
 * 左：分组流程列表    中：画布(diagram)     右：节点详情/AI助手 Tab
 *
 * 生命周期：
 *  - 草稿(is_published=False, is_active=False)：随便改，可删
 *  - 上线(is_published=True, is_active=True)：内容锁定，仅位置可改
 *  - 停用(is_published=True, is_active=False)：仍锁定，对用户隐藏
 */

import { useCallback, useEffect, useMemo, useState, useRef } from 'react';
import { ReactFlow, Background, Controls, MiniMap, useNodesState, useEdgesState, MarkerType } from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import {
  Card, Tag, Button, Space, Spin, Tabs, Form, Input, Select, Modal, message,
  Popconfirm, Empty, Tooltip, Badge, Collapse,
} from 'antd';
import {
  SaveOutlined, PlusOutlined, DeleteOutlined, BranchesOutlined,
  RocketOutlined, PauseOutlined, PlayCircleOutlined, RobotOutlined, SendOutlined,
  EditOutlined, AppstoreOutlined, WarningOutlined, HistoryOutlined,
} from '@ant-design/icons';
import api from '../api';
import { layoutGraph } from '../utils/layout';

const stateColors = {
  DRAFT: '#d9d9d9', AUDITED: '#1890ff', POSTED: '#52c41a', RECONCILED: '#13c2c2',
  FX_ADJUSTED: '#722ed1', PL_TRANSFERRED: '#eb2f96', CLOSED: '#8c8c8c',
  REVERSED: '#ff4d4f', PENDING: '#faad14', PARTIAL: '#ffa940', PAID: '#52c41a',
  OVERDUE: '#ff4d4f', BAD_DEBT: '#434343', CANCELLED: '#ff4d4f',
};

const ROLE_OPTIONS = ['BOSS','OPERATIONS','FINANCE','SALES_ENGINEER','SALES_ASSISTANT','PRODUCT_MANAGER','PRODUCT_ASSISTANT','LOGISTICS','ADMIN'];

// 流程状态 helpers
function getStatusBadge(wf) {
  if (!wf.is_published) return <Tag color="orange">草稿</Tag>;
  if (wf.is_active) return <Tag color="green">上线</Tag>;
  return <Tag>停用</Tag>;
}
function isLocked(wf, dangerMode) { return !!wf.is_published && !dangerMode; }

export default function FlowEditor() {
  const [workflows, setWorkflows] = useState([]);
  const [selected, setSelected] = useState(null);
  const [nodes, setNodes, onNodesChange] = useNodesState([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState([]);
  const [loading, setLoading] = useState(true);
  const [selectedNodeCode, setSelectedNodeCode] = useState(null);
  const [rightTab, setRightTab] = useState('detail');
  const [layoutDirty, setLayoutDirty] = useState(false);
  const [createModal, setCreateModal] = useState(false);
  const [addNodeModal, setAddNodeModal] = useState(false);
  const [createForm] = Form.useForm();
  const [addNodeForm] = Form.useForm();
  const [nodeForm] = Form.useForm();
  const [nextEdges, setNextEdges] = useState([]);  // 当前节点的"出边"编辑状态
  const [dangerMode, setDangerMode] = useState(false);  // 危险修改模式
  const [auditModal, setAuditModal] = useState(false);
  const [auditLogs, setAuditLogs] = useState([]);

  // Agent chat
  const [chatMessages, setChatMessages] = useState([]);
  const [chatInput, setChatInput] = useState('');
  const [chatLoading, setChatLoading] = useState(false);
  const chatEndRef = useRef(null);

  const load = async () => {
    setLoading(true);
    const { data } = await api.get('/admin/workflows');
    setWorkflows(data || []);
    setLoading(false);
    if (selected) {
      const fresh = (data || []).find(w => w.id === selected.id);
      if (fresh) setSelected(fresh);
    }
  };
  useEffect(() => { load(); }, []);

  // 渲染画布
  useEffect(() => {
    if (!selected) {
      setNodes([]); setEdges([]);
      return;
    }
    setLayoutDirty(false);
    setDangerMode(false);  // 切流程时关闭危险模式
    const states = selected.states || [];
    const savedPos = selected.node_positions || {};
    const hasSaved = Object.keys(savedPos).length > 0;

    let newNodes = states.map(s => ({
      id: s.code,
      position: hasSaved && savedPos[s.code] ? savedPos[s.code] : { x: 0, y: 0 },
      data: {
        label: (
          <div style={{ textAlign: 'center', cursor: 'pointer' }}>
            <div style={{ fontWeight: 600, fontSize: 12 }}>{s.name}</div>
            <div style={{ fontSize: 9, color: '#aaa' }}>{s.code}</div>
          </div>
        ),
      },
      style: {
        background: stateColors[s.code] || '#d9d9d9',
        color: ['DRAFT', 'COMPLETED', 'CLOSED', 'EXPIRED', 'PROSPECTING'].includes(s.code) ? '#333' : '#fff',
        border: s.is_initial ? '3px solid #1a1a2e' : s.is_terminal ? '2px dashed #999' : '1px solid #ddd',
        borderRadius: 8, padding: '6px 14px', minWidth: 120,
      },
    }));

    const codeSet = new Set(states.map(s => s.code));
    const newEdges = states.flatMap(s =>
      (s.next || [])
        .filter(n => codeSet.has(n.to))
        .map((n, i) => ({
          id: `e-${s.code}-${n.to}-${i}`,
          source: s.code, target: n.to, label: n.label,
          labelStyle: { fontSize: 10, fill: '#555' },
          labelBgStyle: { fill: '#fff', fillOpacity: 0.9 },
          markerEnd: { type: MarkerType.ArrowClosed, width: 12, height: 12 },
          style: { strokeWidth: 1.5, stroke: '#999' },
          type: 'smoothstep',
        }))
    );

    if (!hasSaved && newNodes.length > 0) {
      newNodes = layoutGraph(newNodes, newEdges, 'TB');
    }
    setNodes(newNodes);
    setEdges(newEdges);
    setSelectedNodeCode(null);
  }, [selected]);

  // 节点拖拽
  const handleNodesChange = useCallback((changes) => {
    onNodesChange(changes);
    if (changes.some(c => c.type === 'position' && c.dragging === false)) {
      setLayoutDirty(true);
    }
  }, [onNodesChange]);

  // 点节点 → 跳到详情 Tab
  const onNodeClick = useCallback((_, node) => {
    setSelectedNodeCode(node.id);
    setRightTab('detail');
    if (selected) {
      const s = (selected.states || []).find(x => x.code === node.id);
      if (s) {
        nodeForm.setFieldsValue({
          name: s.name,
          allowed_roles: s.allowed_roles || [],
          description: s.description || '',
          hard_rules: (s.hard_rules || []).join('\n'),
          hooks: (s.hooks || []).join('\n---\n'),
          custom_html: s.custom_html || '',
          is_initial: !!s.is_initial,
          is_terminal: !!s.is_terminal,
        });
        setNextEdges(s.next || []);
      }
    }
  }, [selected, nodeForm]);

  const savePositions = async () => {
    const positions = {};
    nodes.forEach(n => { positions[n.id] = { x: Math.round(n.position.x), y: Math.round(n.position.y) }; });
    await api.post('/admin/save-positions', { workflow_id: selected.id, positions });
    message.success('布局已保存');
    setLayoutDirty(false);
    load();
  };

  // 保存节点（仅草稿态）
  const saveNode = async () => {
    if (isLocked(selected, dangerMode)) { message.warning('已上线流程不能改节点内容'); return; }
    const v = await nodeForm.validateFields();
    const idx = (selected.states || []).findIndex(s => s.code === selectedNodeCode);
    if (idx < 0) return;
    const old = selected.states[idx];
    const newState = {
      ...old,
      name: v.name,
      allowed_roles: v.allowed_roles || [],
      description: v.description || '',
      hard_rules: v.hard_rules ? v.hard_rules.split('\n').map(s => s.trim()).filter(Boolean) : [],
      hooks: v.hooks ? v.hooks.split(/\n---\n/).map(s => s.trim()).filter(Boolean) : [],
      custom_html: v.custom_html || '',
      is_initial: !!v.is_initial,
      is_terminal: !!v.is_terminal,
      next: nextEdges.filter(n => n.to && n.label),  // 出边（editable_fields/hard_rules/hooks 挂在这里）
    };
    const newStates = [...selected.states];
    newStates[idx] = newState;
    const { data: r } = await api.patch(`/admin/workflows/${selected.id}/states`, { states: newStates, force: dangerMode });
    if (r?.error) { message.error(r.error); return; }
    message.success('节点已保存');
    load();
  };

  // 删节点
  const deleteNode = async () => {
    if (isLocked(selected, dangerMode)) return;
    const newStates = (selected.states || []).filter(s => s.code !== selectedNodeCode);
    // 同时清掉其他节点指向它的 next
    newStates.forEach(s => {
      s.next = (s.next || []).filter(n => n.to !== selectedNodeCode);
    });
    const { data: r } = await api.patch(`/admin/workflows/${selected.id}/states`, { states: newStates, force: dangerMode });
    if (r?.error) { message.error(r.error); return; }
    message.success('节点已删除');
    setSelectedNodeCode(null);
    load();
  };

  // 加节点
  const addNode = async () => {
    if (isLocked(selected, dangerMode)) return;
    const v = await addNodeForm.validateFields();
    const exists = (selected.states || []).find(s => s.code === v.code);
    if (exists) { message.error('状态码已存在'); return; }
    const newStates = [...(selected.states || []), {
      code: v.code, name: v.name,
      allowed_roles: [],
      description: '', agent_tools: [], custom_html: '', hard_rules: [], hooks: [],
      next: [],
      ...(v.is_initial ? { is_initial: true } : {}),
      ...(v.is_terminal ? { is_terminal: true } : {}),
    }];
    const { data: r } = await api.patch(`/admin/workflows/${selected.id}/states`, { states: newStates, force: dangerMode });
    if (r?.error) { message.error(r.error); return; }
    setAddNodeModal(false);
    addNodeForm.resetFields();
    message.success('节点已添加');
    load();
  };

  // 流程级操作
  const createWorkflow = async () => {
    const v = await createForm.validateFields();
    const { data } = await api.post('/admin/workflows', v);
    if (data.error) { message.error(data.error); return; }
    message.success(`已创建：${data.name}`);
    setCreateModal(false);
    createForm.resetFields();
    await load();
  };
  const forkWorkflow = async () => {
    const { data } = await api.post(`/admin/workflows/${selected.id}/fork`);
    if (data.error) { message.error(data.error); return; }
    message.success(`已 Fork：${data.name}`);
    await load();
  };
  const publishWorkflow = async () => {
    const { data } = await api.post(`/admin/workflows/${selected.id}/publish`);
    if (data.error) { message.error(data.error); return; }
    message.success('已上线，内容锁定');
    load();
  };
  const disableWorkflow = async () => {
    const { data } = await api.post(`/admin/workflows/${selected.id}/disable`);
    if (data.error) { message.error(data.error); return; }
    message.success('已停用');
    load();
  };
  const enableWorkflow = async () => {
    const { data } = await api.post(`/admin/workflows/${selected.id}/enable`);
    if (data.error) { message.error(data.error); return; }
    message.success('已启用');
    load();
  };
  const deleteWorkflow = async () => {
    const { data } = await api.delete(`/admin/workflows/${selected.id}`);
    if (data.error) { message.error(data.error); return; }
    message.success('已删除');
    setSelected(null);
    load();
  };
  const changeGroup = async (newGroup) => {
    if (!newGroup || newGroup === selected.group_name) return;
    const { data } = await api.patch(`/admin/workflows/${selected.id}/group`, { group_name: newGroup });
    if (data.error) { message.error(data.error); return; }
    message.success(`已移至「${newGroup}」`);
    load();
  };

  // Agent chat
  const sendChat = async () => {
    if (!chatInput.trim()) return;
    const q = chatInput.trim();
    setChatInput('');
    setChatMessages(prev => [...prev, { role: 'user', content: q }]);
    setChatLoading(true);
    try {
      const { data } = await api.post('/admin/agent/chat', { query: q });
      setChatMessages(prev => [...prev, {
        role: 'agent', content: data.response,
        tools: data.tools_called, tokens: data.tokens_used,
      }]);
      // Agent 可能改了流程，刷新
      await load();
    } catch (e) {
      setChatMessages(prev => [...prev, { role: 'agent', content: '错误: ' + (e.response?.data?.detail || e.message) }]);
    }
    setChatLoading(false);
    setTimeout(() => chatEndRef.current?.scrollIntoView({ behavior: 'smooth' }), 100);
  };

  // 分组
  const grouped = useMemo(() => {
    const g = {};
    workflows.forEach(wf => {
      const key = wf.group_name || '未分组';
      if (!g[key]) g[key] = [];
      g[key].push(wf);
    });
    return g;
  }, [workflows]);
  const allGroups = useMemo(() =>
    Array.from(new Set(workflows.map(w => w.group_name || '未分组'))).sort()
  , [workflows]);

  const selectedNode = selected && selectedNodeCode
    ? (selected.states || []).find(s => s.code === selectedNodeCode)
    : null;

  if (loading) return <Spin size="large" style={{ display: 'block', margin: '80px auto' }} />;

  return (
    <div style={{ display: 'flex', height: 'calc(100vh - 100px)', gap: 12 }}>
      {/* === 左栏：分组流程列表 === */}
      <div style={{ width: 240, display: 'flex', flexDirection: 'column' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
          <h3 style={{ margin: 0, fontSize: 14 }}>所有流程</h3>
          <Tooltip title="新建空白流程">
            <Button size="small" type="primary" icon={<PlusOutlined />} onClick={() => setCreateModal(true)} />
          </Tooltip>
        </div>
        <Card size="small" style={{ flex: 1, overflow: 'auto', borderRadius: 8 }} styles={{ body: { padding: 8 } }}>
          <Collapse defaultActiveKey={Object.keys(grouped)} ghost size="small"
            items={Object.entries(grouped).map(([groupName, wfs]) => ({
              key: groupName,
              label: <span style={{ fontSize: 12, color: '#555' }}><AppstoreOutlined /> {groupName} ({wfs.length})</span>,
              children: (
                <div>
                  {wfs.map(wf => (
                    <div key={wf.id}
                      style={{
                        padding: '6px 10px', borderRadius: 6, marginBottom: 4, cursor: 'pointer',
                        background: selected?.id === wf.id ? '#1a1a2e' : '#fafafa',
                        color: selected?.id === wf.id ? '#fff' : '#333',
                        fontSize: 12,
                      }}
                      onClick={() => setSelected(wf)}>
                      <div style={{ fontWeight: 500 }}>{wf.name}</div>
                      <div style={{ marginTop: 2, fontSize: 10, opacity: 0.8 }}>
                        {getStatusBadge(wf)}
                        <span style={{ marginLeft: 4 }}>v{wf.version} · {(wf.states||[]).length} 节点</span>
                      </div>
                    </div>
                  ))}
                </div>
              ),
            }))}
          />
        </Card>
      </div>

      {/* === 中栏：画布 === */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column' }}>
        {!selected ? (
          <Card style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <Empty description="选择一个流程查看 / 编辑" />
          </Card>
        ) : (
          <>
            {/* 顶部工具栏 */}
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8, padding: '6px 10px', background: '#fff', borderRadius: 8, boxShadow: '0 1px 3px rgba(0,0,0,0.06)' }}>
              <h3 style={{ margin: 0, fontSize: 14 }}>{selected.name}</h3>
              <Tag>{selected.doc_type}</Tag>
              {getStatusBadge(selected)}
              <span style={{ color: '#888', fontSize: 11 }}>v{selected.version}</span>
              <Tooltip title="分组只是前端显示，上线流程也可以任意改">
                <Select
                  size="small"
                  value={selected.group_name || '未分组'}
                  style={{ minWidth: 110 }}
                  onChange={changeGroup}
                  options={[
                    ...allGroups.map(g => ({ value: g, label: `📁 ${g}` })),
                    { value: '__new__', label: '＋ 新分组…' },
                  ]}
                  onSelect={(v) => {
                    if (v === '__new__') {
                      const name = window.prompt('新分组名', '');
                      if (name && name.trim()) changeGroup(name.trim());
                    }
                  }}
                />
              </Tooltip>
              <div style={{ flex: 1 }} />

              {/* 节点位置始终能改 */}
              {layoutDirty && (
                <Button size="small" type="primary" icon={<SaveOutlined />} onClick={savePositions}>保存布局</Button>
              )}

              {/* 草稿态：加节点 + 上线 + 删除 */}
              {!selected.is_published && (
                <>
                  <Button size="small" icon={<PlusOutlined />} onClick={() => setAddNodeModal(true)}>加节点</Button>
                  <Popconfirm title="上线后内容永久锁定（节点位置仍可改），确定？" onConfirm={publishWorkflow}>
                    <Button size="small" type="primary" icon={<RocketOutlined />}>上线</Button>
                  </Popconfirm>
                  <Popconfirm title={`删除流程 "${selected.name}"？`} onConfirm={deleteWorkflow}>
                    <Button size="small" danger icon={<DeleteOutlined />}>删除</Button>
                  </Popconfirm>
                </>
              )}

              {/* 已上线：Fork + 停用/启用 + 危险修改 + 修改记录 */}
              {selected.is_published && (
                <>
                  <Button size="small" icon={<BranchesOutlined />} onClick={forkWorkflow}>Fork</Button>
                  {selected.is_active ? (
                    <Popconfirm title="停用后用户看不到，确认？" onConfirm={disableWorkflow}>
                      <Button size="small" icon={<PauseOutlined />}>停用</Button>
                    </Popconfirm>
                  ) : (
                    <Button size="small" type="primary" icon={<PlayCircleOutlined />} onClick={enableWorkflow}>启用</Button>
                  )}
                  <Tooltip title={dangerMode ? "关闭危险修改" : "开启后可直接改已上线流程，所有改动会被记录"}>
                    <Button size="small" danger={dangerMode} icon={<WarningOutlined />}
                      type={dangerMode ? "primary" : "default"}
                      onClick={() => setDangerMode(!dangerMode)}>
                      {dangerMode ? "🚨 危险修改 ON" : "危险修改"}
                    </Button>
                  </Tooltip>
                </>
              )}
              <Button size="small" icon={<HistoryOutlined />} onClick={async () => {
                const { data } = await api.get(`/admin/workflows/${selected.id}/audit`);
                setAuditLogs(data || []);
                setAuditModal(true);
              }}>修改记录</Button>
            </div>

            {/* 危险修改警告条 */}
            {dangerMode && selected.is_published && (
              <div style={{ background: '#fff1f0', border: '1px solid #ffa39e', padding: '6px 12px', borderRadius: 6, marginBottom: 8, color: '#cf1322', fontSize: 12 }}>
                ⚠️ 危险修改模式：你正在直接编辑已上线流程。所有改动会被审计日志记录，慎重操作。
              </div>
            )}

            {/* 画布 */}
            <Card style={{ flex: 1, borderRadius: 8 }} styles={{ body: { padding: 0, height: '100%' } }}>
              {nodes.length === 0 ? (
                <div style={{ display: 'flex', height: '100%', alignItems: 'center', justifyContent: 'center' }}>
                  <Empty description={selected.is_published ? '空流程' : '空流程，点"加节点"开始'} />
                </div>
              ) : (
                <ReactFlow
                  nodes={nodes} edges={edges}
                  onNodesChange={handleNodesChange} onEdgesChange={onEdgesChange}
                  onNodeClick={onNodeClick} fitView
                  nodesDraggable={true}>
                  <Background />
                  <Controls />
                  <MiniMap style={{ borderRadius: 8 }} nodeStrokeWidth={2} />
                </ReactFlow>
              )}
            </Card>
          </>
        )}
      </div>

      {/* === 右栏：节点详情 / AI 助手 === */}
      <div style={{ width: 380, display: 'flex', flexDirection: 'column' }}>
        <Tabs activeKey={rightTab} onChange={setRightTab} size="small"
          items={[
            {
              key: 'detail',
              label: <span><EditOutlined /> 节点详情</span>,
              children: !selectedNode ? (
                <Empty description="点画布上的节点编辑" image={Empty.PRESENTED_IMAGE_SIMPLE} style={{ paddingTop: 60 }} />
              ) : (
                <Card size="small" style={{ borderRadius: 8 }}>
                  <div style={{ marginBottom: 12 }}>
                    <Tag color="blue">{selectedNode.code}</Tag>
                    {isLocked(selected, dangerMode) && <Tag color="red">🔒 已上线，不可改</Tag>}
                  </div>
                  <Form form={nodeForm} layout="vertical" disabled={isLocked(selected, dangerMode)}>
                    <Form.Item name="name" label="节点名" rules={[{ required: true }]}>
                      <Input />
                    </Form.Item>
                    <Form.Item name="allowed_roles" label="允许角色">
                      <Select mode="multiple" options={ROLE_OPTIONS.map(r => ({ value: r, label: r }))} />
                    </Form.Item>
                    <Form.Item name="description" label="描述（给Agent看的中文）">
                      <Input.TextArea rows={4} />
                    </Form.Item>
                    <Form.Item label="出边（用户在此节点可以做的动作）"
                      help={<span style={{ fontSize: 10 }}>每条出边 = 一个按钮 + 此按钮打开的录入字段 + 可选校验/钩子。</span>}>
                      <div>
                        {nextEdges.map((n, i) => (
                          <div key={i} style={{ border: '1px dashed #ddd', padding: 8, borderRadius: 6, marginBottom: 6, background: '#fafafa' }}>
                            <Space.Compact style={{ width: '100%', marginBottom: 6 }}>
                              <Input value={n.label} placeholder="按钮名（如:提交审核）"
                                onChange={e => { const a=[...nextEdges]; a[i] = {...a[i], label:e.target.value}; setNextEdges(a); }}
                                disabled={isLocked(selected, dangerMode)} />
                              <span style={{ padding: '4px 6px', background: '#fff', border: '1px solid #d9d9d9' }}>→</span>
                              <Select value={n.to} placeholder="目标节点" style={{ minWidth: 130 }}
                                disabled={isLocked(selected, dangerMode)}
                                options={(selected.states || []).filter(s => s.code !== selectedNodeCode).map(s => ({
                                  value: s.code, label: s.name,
                                }))}
                                onChange={v => { const a=[...nextEdges]; a[i] = {...a[i], to:v}; setNextEdges(a); }}
                              />
                              {!isLocked(selected, dangerMode) && (
                                <Button danger icon={<DeleteOutlined />}
                                  onClick={() => setNextEdges(nextEdges.filter((_, idx) => idx !== i))} />
                              )}
                            </Space.Compact>
                            <div style={{ fontSize: 10, color: '#888', margin: '4px 0 2px' }}>① 角色限制（留空 = 继承节点）</div>
                            <Select mode="multiple" value={n.roles || []} placeholder="不填 = 节点角色都能点"
                              style={{ width: '100%', marginBottom: 4 }} size="small"
                              disabled={isLocked(selected, dangerMode)}
                              options={ROLE_OPTIONS.map(r => ({ value: r, label: r }))}
                              onChange={v => { const a=[...nextEdges]; a[i] = {...a[i], roles: v.length ? v : undefined}; setNextEdges(a); }}
                            />
                            <div style={{ fontSize: 10, color: '#888', margin: '4px 0 2px' }}>② 录入字段（点按钮时打开这些字段让用户填；逗号分隔）</div>
                            <Input value={(n.editable_fields || []).join(', ')}
                              placeholder="如: amount, notes"
                              style={{ marginBottom: 4, fontSize: 12 }} size="small"
                              disabled={isLocked(selected, dangerMode)}
                              onChange={e => {
                                const a = [...nextEdges];
                                const fields = e.target.value.split(',').map(s => s.trim()).filter(Boolean);
                                a[i] = {...a[i], editable_fields: fields};
                                setNextEdges(a);
                              }}
                            />
                            <div style={{ fontSize: 10, color: '#888', margin: '4px 0 2px' }}>③ 硬规则（只读判定，一行一条；不通过拦截）</div>
                            <Input.TextArea value={(n.hard_rules || []).join('\n')} rows={2}
                              placeholder="如: doc.total_amount > 0"
                              style={{ fontFamily: 'ui-monospace, monospace', fontSize: 11, marginBottom: 4 }}
                              disabled={isLocked(selected, dangerMode)}
                              onChange={e => {
                                const a = [...nextEdges];
                                const rules = e.target.value.split('\n').map(s => s.trim()).filter(Boolean);
                                a[i] = {...a[i], hard_rules: rules.length ? rules : undefined};
                                setNextEdges(a);
                              }}
                            />
                            <div style={{ fontSize: 10, color: '#888', margin: '4px 0 2px' }}>④ 钩子脚本（commit 前副作用；--- 分隔多段）</div>
                            <Input.TextArea value={(n.hooks || []).join('\n---\n')} rows={3}
                              placeholder={`for line in lines:\n  insert("inventory", {...})`}
                              style={{ fontFamily: 'ui-monospace, monospace', fontSize: 11 }}
                              disabled={isLocked(selected, dangerMode)}
                              onChange={e => {
                                const a = [...nextEdges];
                                const hks = e.target.value.split(/\n---\n/).map(s => s.trim()).filter(Boolean);
                                a[i] = {...a[i], hooks: hks.length ? hks : undefined};
                                setNextEdges(a);
                              }}
                            />
                          </div>
                        ))}
                        {!isLocked(selected, dangerMode) && (
                          <Button block size="small" icon={<PlusOutlined />}
                            onClick={() => setNextEdges([...nextEdges, { to: '', label: '' }])}>
                            加出边
                          </Button>
                        )}
                      </div>
                    </Form.Item>
                    <Form.Item name="hard_rules" label="节点级硬规则（任何动作都查；可选）"
                      help={<span style={{ fontSize: 10 }}>跟出边的硬规则区分：节点级永远查，出边级只查这条边</span>}>
                      <Input.TextArea rows={2} style={{ fontFamily: 'ui-monospace, monospace', fontSize: 11 }} />
                    </Form.Item>
                    <Form.Item name="hooks" label="节点级钩子（进入此节点时执行；可选）"
                      help={<span style={{ fontSize: 10 }}>commit 前运行的副作用脚本。多段用 --- 分隔。可写其他表（insert/update），失败则整单回滚。</span>}>
                      <Input.TextArea rows={3} style={{ fontFamily: 'ui-monospace, monospace', fontSize: 11 }}
                        placeholder={`for line in lines:\n    insert("inventory", {"material_id": line.material_id, ...})`} />
                    </Form.Item>
                    <Form.Item name="custom_html" label="自定义HTML"><Input.TextArea rows={2} /></Form.Item>
                    <Space>
                      <Form.Item name="is_initial" valuePropName="checked" noStyle>
                        <label><input type="checkbox" /> 起始</label>
                      </Form.Item>
                      <Form.Item name="is_terminal" valuePropName="checked" noStyle>
                        <label><input type="checkbox" /> 终止</label>
                      </Form.Item>
                    </Space>
                  </Form>
                  {!isLocked(selected, dangerMode) && (
                    <Space style={{ marginTop: 12, width: '100%', justifyContent: 'space-between' }}>
                      <Popconfirm title="删除节点？" onConfirm={deleteNode}>
                        <Button size="small" danger icon={<DeleteOutlined />}>删除节点</Button>
                      </Popconfirm>
                      <Button size="small" type="primary" icon={<SaveOutlined />} onClick={saveNode}>保存</Button>
                    </Space>
                  )}
                </Card>
              ),
            },
            {
              key: 'agent',
              label: <span><RobotOutlined /> AI 助手</span>,
              children: (
                <div style={{ display: 'flex', flexDirection: 'column', height: 'calc(100vh - 200px)' }}>
                  <Card size="small" style={{ flex: 1, overflow: 'auto', borderRadius: 8, marginBottom: 8 }} styles={{ body: { padding: 10 } }}>
                    {chatMessages.length === 0 && (
                      <div style={{ textAlign: 'center', padding: 40, color: '#999', fontSize: 12 }}>
                        <RobotOutlined style={{ fontSize: 28, marginBottom: 10 }} /><br/>
                        让 Agent 帮你改流程<br/>
                        <span style={{ fontSize: 10 }}>"给凭证录入加金额&gt;0规则" / "fork 凭证流程"</span>
                      </div>
                    )}
                    {chatMessages.map((m, i) => (
                      <div key={i} style={{
                        padding: '6px 10px', margin: '4px 0', borderRadius: 6, fontSize: 12,
                        background: m.role === 'user' ? '#1a1a2e' : '#f5f5f5',
                        color: m.role === 'user' ? '#fff' : '#333',
                        whiteSpace: 'pre-wrap',
                      }}>
                        {m.content}
                        {m.tools?.length > 0 && (
                          <div style={{ marginTop: 4, fontSize: 9, opacity: 0.6 }}>
                            工具: {m.tools.map(t => t.tool).join(', ')}
                          </div>
                        )}
                      </div>
                    ))}
                    {chatLoading && <Spin size="small" style={{ display: 'block', margin: 8 }} />}
                    <div ref={chatEndRef} />
                  </Card>
                  <div style={{ display: 'flex', gap: 4 }}>
                    <Input size="small" value={chatInput} onChange={e => setChatInput(e.target.value)}
                      onPressEnter={sendChat} placeholder="跟 Agent 说..." />
                    <Button size="small" type="primary" icon={<SendOutlined />} onClick={sendChat} loading={chatLoading} />
                  </div>
                </div>
              ),
            },
          ]}
        />
      </div>

      {/* === 新建流程弹窗 === */}
      <Modal title="新建空白流程" open={createModal} onCancel={() => setCreateModal(false)} onOk={createWorkflow}>
        <Form form={createForm} layout="vertical">
          <Form.Item name="doc_type" label="标识符（英文）" rules={[{ required: true }]}
            help="流程的英文标签，如 EXPENSE_REPORT。已存在的会自动加后缀">
            <Input placeholder="EXPENSE_REPORT" />
          </Form.Item>
          <Form.Item name="name" label="流程名（中文）" rules={[{ required: true }]}>
            <Input placeholder="员工报销流程" />
          </Form.Item>
          <Form.Item name="group_name" label="分组">
            <Input placeholder="财务 / 业务 / 仓储 / 自定义" />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input.TextArea rows={3} placeholder="这个流程做什么用的" />
          </Form.Item>
        </Form>
      </Modal>

      {/* === 加节点弹窗 === */}
      <Modal title="添加节点" open={addNodeModal} onCancel={() => setAddNodeModal(false)} onOk={addNode}>
        <Form form={addNodeForm} layout="vertical">
          <Form.Item name="code" label="状态码（英文，唯一）" rules={[{ required: true }]}>
            <Input placeholder="DRAFT" />
          </Form.Item>
          <Form.Item name="name" label="节点名（中文）" rules={[{ required: true }]}>
            <Input placeholder="草稿录入" />
          </Form.Item>
          <Space>
            <Form.Item name="is_initial" valuePropName="checked" noStyle>
              <label><input type="checkbox" /> 起始节点</label>
            </Form.Item>
            <Form.Item name="is_terminal" valuePropName="checked" noStyle>
              <label><input type="checkbox" /> 终止节点</label>
            </Form.Item>
          </Space>
        </Form>
      </Modal>

      {/* === 修改记录弹窗 === */}
      <Modal title={<span><HistoryOutlined /> 修改记录 — {selected?.name}</span>}
        open={auditModal} onCancel={() => setAuditModal(false)} footer={null} width={780}>
        {auditLogs.length === 0 ? (
          <Empty description="无记录" />
        ) : (
          <div style={{ maxHeight: 500, overflow: 'auto' }}>
            {auditLogs.map(l => (
              <div key={l.id} style={{
                padding: 10, marginBottom: 8, borderRadius: 6,
                background: l.danger_mode ? '#fff1f0' : '#fafafa',
                border: l.danger_mode ? '1px solid #ffa39e' : '1px solid #f0f0f0',
              }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
                  <Space>
                    <Tag color={({
                      create: 'green', delete: 'red', fork: 'blue', publish: 'green',
                      disable: 'orange', enable: 'green', edit_states: 'cyan',
                      change_group: 'purple', save_positions: 'default', fork_source: 'blue',
                    })[l.change_type] || 'default'}>{l.change_type}</Tag>
                    {l.danger_mode && <Tag color="red">🚨 危险修改</Tag>}
                    <span style={{ fontSize: 12, color: '#888' }}>{l.by}</span>
                  </Space>
                  <span style={{ fontSize: 11, color: '#999' }}>
                    {l.timestamp?.replace('T', ' ').slice(0, 19)}
                  </span>
                </div>
                <div style={{ fontSize: 12 }}>{l.summary || '(无描述)'}</div>
                {l.ip && <div style={{ fontSize: 10, color: '#aaa', marginTop: 4 }}>IP: {l.ip}</div>}
              </div>
            ))}
          </div>
        )}
      </Modal>
    </div>
  );
}
