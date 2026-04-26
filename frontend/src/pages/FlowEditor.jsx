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
  Card, Button, Space, Spin, Tabs, Form, Input, Select, Modal, message,
  Popconfirm, Empty, Tooltip, Badge, Collapse,
} from 'antd';
import {
  SaveOutlined, PlusOutlined, DeleteOutlined, BranchesOutlined,
  RocketOutlined, PauseOutlined, PlayCircleOutlined, RobotOutlined, SendOutlined,
  EditOutlined, AppstoreOutlined, WarningOutlined, HistoryOutlined, LockOutlined,
} from '@ant-design/icons';
import api from '../api';
import { layoutGraph } from '../utils/layout';
import WorkflowEdge, { decorateWorkflowEdges } from '../components/WorkflowEdge';

const CARD_SHADOW =
  'rgba(0,0,0,0.06) 0px 0px 0px 1px, rgba(0,0,0,0.04) 0px 1px 2px, rgba(0,0,0,0.04) 0px 2px 4px';
const edgeTypes = { workflow: WorkflowEdge };

function Pill({ bg, color, children }) {
  return (
    <span style={{
      display: 'inline-block', padding: '1px 8px', borderRadius: 4,
      background: bg, color, fontSize: 11, fontWeight: 500, letterSpacing: '0.02em',
    }}>{children}</span>
  );
}

// 降饱和状态色
const NEUTRAL = { bg: '#f5f2ef', color: '#4e4e4e', border: '#bfbbb5' };
const stateColors = {
  DRAFT:        NEUTRAL,
  AUDITED:      { bg: '#eaf1fb', color: '#1f5aa8', border: '#1f5aa8' },
  POSTED:       { bg: '#ebf5ee', color: '#1f8f3a', border: '#1f8f3a' },
  RECONCILED:   { bg: '#e7f3f5', color: '#0e7490', border: '#0e7490' },
  FX_ADJUSTED:  { bg: '#f1ebfa', color: '#6b46c1', border: '#6b46c1' },
  PL_TRANSFERRED:{ bg: '#fbeaf1', color: '#b83280', border: '#b83280' },
  CLOSED:       { bg: '#f5f5f5', color: '#1a1a1a', border: '#4e4e4e' },
  REVERSED:     { bg: '#fdecea', color: '#b42318', border: '#b42318' },
  PENDING:      { bg: '#fbf5e4', color: '#b8860b', border: '#b8860b' },
  PARTIAL:      { bg: '#fbf5e4', color: '#b8860b', border: '#b8860b' },
  PAID:         { bg: '#ebf5ee', color: '#1f8f3a', border: '#1f8f3a' },
  OVERDUE:      { bg: '#fdecea', color: '#b42318', border: '#b42318' },
  BAD_DEBT:     { bg: '#f5f5f5', color: '#1a1a1a', border: '#4e4e4e' },
  CANCELLED:    { bg: '#fdecea', color: '#b42318', border: '#b42318' },
};

const ROLE_OPTIONS = ['BOSS','OPERATIONS','FINANCE','SALES_ENGINEER','SALES_ASSISTANT','PRODUCT_MANAGER','PRODUCT_ASSISTANT','LOGISTICS','ADMIN'];

function getNodeStyle(s) {
  const t = s.node_type;
  if (t === 'policy') return {
    background: '#fbf5e4', color: '#8c6d1f',
    border: '1px solid #ece0b7', borderLeft: '4px solid #b8860b',
    borderRadius: 6, padding: '6px 14px', minWidth: 120,
  };
  if (t === 'cross_module') return {
    background: '#ebf5ee', color: '#1f8f3a',
    border: '1px solid #c7e6cf', borderLeft: '4px solid #1f8f3a',
    borderRadius: 9999, padding: '6px 14px', minWidth: 120,
  };
  if (t === 'report') return {
    background: '#eaf1fb', color: '#1f5aa8',
    border: '1px dashed #a8c4e7', borderRadius: 6,
    padding: '6px 14px', minWidth: 120,
  };
  const c = stateColors[s.code] || NEUTRAL;
  return {
    background: c.bg,
    color: c.color,
    border: `1px solid ${c.border}`,
    borderLeft: `4px solid ${c.border}`,
    boxShadow: s.is_initial
      ? 'rgba(0,0,0,0.06) 0px 0px 0px 1.5px, rgba(0,0,0,0.04) 0px 4px 8px'
      : 'rgba(0,0,0,0.04) 0px 1px 2px',
    borderRadius: 8,
    padding: '6px 14px',
    minWidth: 120,
    fontSize: 12,
    fontWeight: 500,
    letterSpacing: '0.01em',
    opacity: s.is_terminal ? 0.75 : 1,
    borderStyle: s.is_terminal ? 'dashed' : 'solid',
  };
}

function getStatusBadge(wf) {
  if (!wf.is_published) return <Pill bg="#fbf5e4" color="#b8860b">草稿</Pill>;
  if (wf.is_active)     return <Pill bg="#ebf5ee" color="#1f8f3a">上线</Pill>;
  return <Pill bg="#f5f2ef" color="#4e4e4e">停用</Pill>;
}
function isLocked(wf, dangerMode) { return !!wf?.is_published && !dangerMode; }

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
  const [nextEdges, setNextEdges] = useState([]);
  const [dangerMode, setDangerMode] = useState(false);
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
    setDangerMode(false);
    const states = selected.states || [];
    const savedPos = selected.node_positions || {};
    const hasSaved = Object.keys(savedPos).length > 0;

    const nodeTypeMap = {};
    states.forEach(s => { nodeTypeMap[s.code] = s.node_type || 'state'; });

    let newNodes = states.map(s => ({
      id: s.code,
      position: hasSaved && savedPos[s.code] ? savedPos[s.code] : { x: 0, y: 0 },
      data: {
        label: (
          <div style={{ textAlign: 'center', cursor: 'pointer' }}>
            <div style={{ fontWeight: 500, fontSize: 12, letterSpacing: '0.01em' }}>{s.name}</div>
            <div style={{
              fontSize: 9, opacity: 0.6, marginTop: 2,
              fontFamily: 'ui-monospace, monospace',
            }}>{s.code}</div>
          </div>
        ),
      },
      style: getNodeStyle(s),
    }));

    const codeSet = new Set(states.map(s => s.code));
    const newEdges = decorateWorkflowEdges(states.flatMap(s =>
      (s.next || [])
        .filter(n => codeSet.has(n.to))
        .map((n, i) => {
          const isPolicy = nodeTypeMap[s.code] === 'policy';
          return {
            id: `e-${s.code}-${n.to}-${i}`,
            source: s.code, target: n.to,
            label: isPolicy ? '' : n.label,
            markerEnd: { type: MarkerType.ArrowClosed, width: 12, height: 12, color: '#bfbbb5' },
            style: isPolicy
              ? { strokeWidth: 1.5, stroke: '#b8860b', strokeDasharray: '6 3' }
              : { strokeWidth: 1.5, stroke: '#bfbbb5' },
          };
        })
    ));

    if (!hasSaved && newNodes.length > 0) {
      newNodes = layoutGraph(newNodes, newEdges, 'TB');
    }
    setNodes(newNodes);
    setEdges(newEdges);
    setSelectedNodeCode(null);
  }, [selected]);

  const handleNodesChange = useCallback((changes) => {
    onNodesChange(changes);
    if (changes.some(c => c.type === 'position' && c.dragging === false)) {
      setLayoutDirty(true);
    }
  }, [onNodesChange]);

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
      next: nextEdges.filter(n => n.to && n.label),
    };
    const newStates = [...selected.states];
    newStates[idx] = newState;
    const { data: r } = await api.patch(`/admin/workflows/${selected.id}/states`, { states: newStates, force: dangerMode });
    if (r?.error) { message.error(r.error); return; }
    message.success('节点已保存');
    load();
  };

  const deleteNode = async () => {
    if (isLocked(selected, dangerMode)) return;
    const newStates = (selected.states || []).filter(s => s.code !== selectedNodeCode);
    newStates.forEach(s => {
      s.next = (s.next || []).filter(n => n.to !== selectedNodeCode);
    });
    const { data: r } = await api.patch(`/admin/workflows/${selected.id}/states`, { states: newStates, force: dangerMode });
    if (r?.error) { message.error(r.error); return; }
    message.success('节点已删除');
    setSelectedNodeCode(null);
    load();
  };

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
      await load();
    } catch (e) {
      setChatMessages(prev => [...prev, { role: 'agent', content: '错误: ' + (e.response?.data?.detail || e.message) }]);
    }
    setChatLoading(false);
    setTimeout(() => chatEndRef.current?.scrollIntoView({ behavior: 'smooth' }), 100);
  };

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

  const locked = isLocked(selected, dangerMode);

  if (loading) return <Spin size="large" style={{ display: 'block', margin: '80px auto' }} />;

  return (
    <div style={{ display: 'flex', height: 'calc(100vh - 100px)', gap: 14 }}>
      {/* === 左栏：分组流程列表 === */}
      <div style={{ width: 250, display: 'flex', flexDirection: 'column' }}>
        <div style={{
          display: 'flex', justifyContent: 'space-between', alignItems: 'center',
          marginBottom: 10,
        }}>
          <h3 style={{
            margin: 0, fontSize: 13, fontWeight: 500,
            color: '#4e4e4e', letterSpacing: '0.03em', textTransform: 'uppercase',
          }}>
            所有流程
          </h3>
          <Tooltip title="新建空白流程">
            <Button size="small" type="primary" icon={<PlusOutlined />} onClick={() => setCreateModal(true)} />
          </Tooltip>
        </div>
        <Card
          size="small"
          style={{ flex: 1, overflow: 'auto', borderRadius: 14, boxShadow: CARD_SHADOW, border: 'none' }}
          styles={{ body: { padding: 8 } }}
        >
          <Collapse
            defaultActiveKey={Object.keys(grouped)} ghost size="small"
            items={Object.entries(grouped).map(([groupName, wfs]) => ({
              key: groupName,
              label: (
                <span style={{ fontSize: 12, color: '#4e4e4e', fontWeight: 500, letterSpacing: '0.02em' }}>
                  <AppstoreOutlined style={{ marginRight: 6 }} />
                  {groupName} <span style={{ color: '#bfbbb5' }}>({wfs.length})</span>
                </span>
              ),
              children: (
                <div>
                  {wfs.map(wf => {
                    const isSel = selected?.id === wf.id;
                    return (
                      <div
                        key={wf.id}
                        style={{
                          padding: '8px 10px', borderRadius: 8, marginBottom: 4, cursor: 'pointer',
                          background: isSel ? '#000' : 'transparent',
                          color: isSel ? '#fff' : '#000',
                          fontSize: 12, transition: 'background 0.15s',
                        }}
                        onMouseEnter={e => { if (!isSel) e.currentTarget.style.background = 'rgba(245, 242, 239, 0.6)'; }}
                        onMouseLeave={e => { if (!isSel) e.currentTarget.style.background = 'transparent'; }}
                        onClick={() => setSelected(wf)}
                      >
                        <div style={{ fontWeight: 500, letterSpacing: '0.01em' }}>{wf.name}</div>
                        <div style={{
                          marginTop: 4, display: 'flex', alignItems: 'center',
                          gap: 6, fontSize: 10,
                          opacity: isSel ? 0.85 : 1,
                        }}>
                          {getStatusBadge(wf)}
                          <span style={{ color: isSel ? 'rgba(255,255,255,0.7)' : '#777169' }}>
                            v{wf.version} · {(wf.states||[]).length} 节点
                          </span>
                        </div>
                      </div>
                    );
                  })}
                </div>
              ),
            }))}
          />
        </Card>
      </div>

      {/* === 中栏：画布 === */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column' }}>
        {!selected ? (
          <Card
            style={{
              flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center',
              borderRadius: 14, boxShadow: CARD_SHADOW, border: 'none',
            }}
          >
            <Empty description="选择一个流程查看 / 编辑" />
          </Card>
        ) : (
          <>
            {/* 顶部工具栏 */}
            <div style={{
              display: 'flex', alignItems: 'center', gap: 10, marginBottom: 10,
              padding: '10px 14px', background: '#fff',
              borderRadius: 14, boxShadow: CARD_SHADOW,
              flexWrap: 'wrap',
            }}>
              <h3 style={{ margin: 0, fontSize: 15, fontWeight: 500, letterSpacing: '0.01em' }}>
                {selected.name}
              </h3>
              <Pill bg="#eaf1fb" color="#1f5aa8">{selected.doc_type}</Pill>
              {getStatusBadge(selected)}
              <span style={{
                color: '#777169', fontSize: 11,
                fontFamily: 'ui-monospace, monospace',
              }}>v{selected.version}</span>
              <Tooltip title="分组只是前端显示，上线流程也可以任意改">
                <Select
                  size="small"
                  value={selected.group_name || '未分组'}
                  style={{ minWidth: 120 }}
                  onChange={changeGroup}
                  options={[
                    ...allGroups.map(g => ({ value: g, label: g })),
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

              {layoutDirty && (
                <Button size="small" type="primary" icon={<SaveOutlined />} onClick={savePositions}>
                  保存布局
                </Button>
              )}

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
                    <Button
                      size="small"
                      danger={dangerMode}
                      icon={<WarningOutlined />}
                      type={dangerMode ? 'primary' : 'default'}
                      onClick={() => setDangerMode(!dangerMode)}
                    >
                      {dangerMode ? '危险修改 ON' : '危险修改'}
                    </Button>
                  </Tooltip>
                </>
              )}
              <Button
                size="small"
                icon={<HistoryOutlined />}
                onClick={async () => {
                  const { data } = await api.get(`/admin/workflows/${selected.id}/audit`);
                  setAuditLogs(data || []);
                  setAuditModal(true);
                }}
              >
                修改记录
              </Button>
            </div>

            {/* 危险修改警告条 */}
            {dangerMode && selected.is_published && (
              <div style={{
                background: '#fdecea',
                border: '1px solid #f5c6ce',
                borderLeft: '4px solid #b42318',
                padding: '10px 14px', borderRadius: 10, marginBottom: 10,
                color: '#b42318', fontSize: 12, letterSpacing: '0.01em',
              }}>
                <WarningOutlined style={{ marginRight: 6 }} />
                危险修改模式：你正在直接编辑已上线流程。所有改动会被审计日志记录，慎重操作。
              </div>
            )}

            {/* 画布 */}
            <Card
              style={{ flex: 1, borderRadius: 14, boxShadow: CARD_SHADOW, border: 'none', overflow: 'hidden' }}
              styles={{ body: { padding: 0, height: '100%' } }}
            >
              {nodes.length === 0 ? (
                <div style={{ display: 'flex', height: '100%', alignItems: 'center', justifyContent: 'center' }}>
                  <Empty description={selected.is_published ? '空流程' : '空流程，点"加节点"开始'} />
                </div>
              ) : (
                <ReactFlow
                  nodes={nodes} edges={edges}
                  edgeTypes={edgeTypes}
                  onNodesChange={handleNodesChange} onEdgesChange={onEdgesChange}
                  onNodeClick={onNodeClick} fitView
                  defaultEdgeOptions={{ type: 'workflow' }}
                  nodesDraggable={true}
                >
                  <Background gap={24} size={1} color="rgba(0,0,0,0.06)" />
                  <Controls />
                  <MiniMap
                    style={{
                      borderRadius: 10,
                      background: 'rgba(245,242,239,0.8)',
                      border: '1px solid rgba(0,0,0,0.05)',
                    }}
                    nodeStrokeWidth={2}
                    maskColor="rgba(0,0,0,0.04)"
                  />
                </ReactFlow>
              )}
            </Card>
          </>
        )}
      </div>

      {/* === 右栏：节点详情 / AI 助手 === */}
      <div style={{ width: 400, display: 'flex', flexDirection: 'column' }}>
        <Tabs
          activeKey={rightTab}
          onChange={setRightTab}
          size="small"
          items={[
            {
              key: 'detail',
              label: <span><EditOutlined /> 节点详情</span>,
              children: !selectedNode ? (
                <Empty description="点画布上的节点编辑" image={Empty.PRESENTED_IMAGE_SIMPLE} style={{ paddingTop: 60 }} />
              ) : (
                <div style={{ maxHeight: 'calc(100vh - 200px)', overflowY: 'auto', paddingRight: 4 }}>
                <Card
                  size="small"
                  style={{ borderRadius: 12, boxShadow: CARD_SHADOW, border: 'none' }}
                >
                  <div style={{ marginBottom: 14, display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
                    <Pill bg="#eaf1fb" color="#1f5aa8">{selectedNode.code}</Pill>
                    {locked && (
                      <Pill bg="#fdecea" color="#b42318">
                        <LockOutlined style={{ fontSize: 10, marginRight: 2 }} />
                        已上线，不可改
                      </Pill>
                    )}
                  </div>
                  <Form form={nodeForm} layout="vertical" disabled={locked}>
                    <Form.Item name="name" label="节点名" rules={[{ required: true }]}>
                      <Input />
                    </Form.Item>
                    <Form.Item name="allowed_roles" label="允许角色">
                      <Select mode="multiple" options={ROLE_OPTIONS.map(r => ({ value: r, label: r }))} />
                    </Form.Item>
                    <Form.Item name="description" label="描述（给 Agent 看的中文）">
                      <Input.TextArea rows={4} />
                    </Form.Item>
                    <Form.Item
                      label="出边（用户在此节点可做的动作）"
                      help={<span style={{ fontSize: 10, color: '#777169' }}>
                        每条出边 = 一个按钮 + 此按钮打开的录入字段 + 可选校验/钩子。
                      </span>}
                    >
                      <div>
                        {nextEdges.map((n, i) => (
                          <div
                            key={i}
                            style={{
                              border: '1px solid rgba(0,0,0,0.08)',
                              padding: 10, borderRadius: 10, marginBottom: 8,
                              background: 'rgba(245, 242, 239, 0.5)',
                            }}
                          >
                            <Space.Compact style={{ width: '100%', marginBottom: 8 }}>
                              <Input
                                value={n.label}
                                placeholder="按钮名（如: 提交审核）"
                                onChange={e => { const a = [...nextEdges]; a[i] = { ...a[i], label: e.target.value }; setNextEdges(a); }}
                                disabled={locked}
                              />
                              <span style={{
                                padding: '0 10px', background: '#fff',
                                border: '1px solid #e5e5e5',
                                display: 'flex', alignItems: 'center',
                                color: '#777169',
                              }}>→</span>
                              <Select
                                value={n.to}
                                placeholder="目标节点"
                                style={{ minWidth: 140 }}
                                disabled={locked}
                                options={(selected.states || []).filter(s => s.code !== selectedNodeCode).map(s => ({
                                  value: s.code, label: s.name,
                                }))}
                                onChange={v => { const a = [...nextEdges]; a[i] = { ...a[i], to: v }; setNextEdges(a); }}
                              />
                              {!locked && (
                                <Button danger icon={<DeleteOutlined />} onClick={() => setNextEdges(nextEdges.filter((_, idx) => idx !== i))} />
                              )}
                            </Space.Compact>
                            <div style={{ fontSize: 10, color: '#777169', margin: '6px 0 2px', letterSpacing: '0.02em' }}>
                              1. 角色限制（留空 = 继承节点）
                            </div>
                            <Select
                              mode="multiple"
                              value={n.roles || []}
                              placeholder="不填 = 节点角色都能点"
                              style={{ width: '100%', marginBottom: 4 }}
                              size="small"
                              disabled={locked}
                              options={ROLE_OPTIONS.map(r => ({ value: r, label: r }))}
                              onChange={v => { const a = [...nextEdges]; a[i] = { ...a[i], roles: v.length ? v : undefined }; setNextEdges(a); }}
                            />
                            <div style={{ fontSize: 10, color: '#777169', margin: '6px 0 2px', letterSpacing: '0.02em' }}>
                              2. 录入字段（点按钮时打开这些字段让用户填；逗号分隔）
                            </div>
                            <Input
                              value={(n.editable_fields || []).join(', ')}
                              placeholder="如: amount, notes"
                              style={{ marginBottom: 4, fontSize: 12 }}
                              size="small"
                              disabled={locked}
                              onChange={e => {
                                const a = [...nextEdges];
                                const fields = e.target.value.split(',').map(s => s.trim()).filter(Boolean);
                                a[i] = { ...a[i], editable_fields: fields };
                                setNextEdges(a);
                              }}
                            />
                            <div style={{ fontSize: 10, color: '#777169', margin: '6px 0 2px', letterSpacing: '0.02em' }}>
                              3. 硬规则（只读判定，一行一条；不通过拦截）
                            </div>
                            <Input.TextArea
                              value={(n.hard_rules || []).join('\n')}
                              rows={2}
                              placeholder="如: doc.total_amount > 0"
                              style={{ fontFamily: 'ui-monospace, monospace', fontSize: 11, marginBottom: 4 }}
                              disabled={locked}
                              onChange={e => {
                                const a = [...nextEdges];
                                const rules = e.target.value.split('\n').map(s => s.trim()).filter(Boolean);
                                a[i] = { ...a[i], hard_rules: rules.length ? rules : undefined };
                                setNextEdges(a);
                              }}
                            />
                            <div style={{ fontSize: 10, color: '#777169', margin: '6px 0 2px', letterSpacing: '0.02em' }}>
                              4. 钩子脚本（commit 前副作用；--- 分隔多段）
                            </div>
                            <Input.TextArea
                              value={(n.hooks || []).join('\n---\n')}
                              rows={3}
                              placeholder={`for line in lines:\n  insert("inventory", {...})`}
                              style={{ fontFamily: 'ui-monospace, monospace', fontSize: 11 }}
                              disabled={locked}
                              onChange={e => {
                                const a = [...nextEdges];
                                const hks = e.target.value.split(/\n---\n/).map(s => s.trim()).filter(Boolean);
                                a[i] = { ...a[i], hooks: hks.length ? hks : undefined };
                                setNextEdges(a);
                              }}
                            />
                          </div>
                        ))}
                        {!locked && (
                          <Button block size="small" icon={<PlusOutlined />} onClick={() => setNextEdges([...nextEdges, { to: '', label: '' }])}>
                            加出边
                          </Button>
                        )}
                      </div>
                    </Form.Item>
                    <Form.Item
                      name="hard_rules"
                      label="节点级硬规则（任何动作都查；可选）"
                      help={<span style={{ fontSize: 10, color: '#777169' }}>
                        跟出边的硬规则区分：节点级永远查，出边级只查这条边
                      </span>}
                    >
                      <Input.TextArea rows={2} style={{ fontFamily: 'ui-monospace, monospace', fontSize: 11 }} />
                    </Form.Item>
                    <Form.Item
                      name="hooks"
                      label="节点级钩子（进入此节点时执行；可选）"
                      help={<span style={{ fontSize: 10, color: '#777169' }}>
                        commit 前运行的副作用脚本。多段用 --- 分隔。可写其他表，失败则整单回滚。
                      </span>}
                    >
                      <Input.TextArea
                        rows={3}
                        style={{ fontFamily: 'ui-monospace, monospace', fontSize: 11 }}
                        placeholder={`for line in lines:\n    insert("inventory", {"material_id": line.material_id, ...})`}
                      />
                    </Form.Item>
                    <Form.Item name="custom_html" label="自定义 HTML"><Input.TextArea rows={2} /></Form.Item>
                    <Space>
                      <Form.Item name="is_initial" valuePropName="checked" noStyle>
                        <label style={{ fontSize: 13, color: '#4e4e4e' }}><input type="checkbox" /> 起始</label>
                      </Form.Item>
                      <Form.Item name="is_terminal" valuePropName="checked" noStyle>
                        <label style={{ fontSize: 13, color: '#4e4e4e' }}><input type="checkbox" /> 终止</label>
                      </Form.Item>
                    </Space>
                  </Form>
                  {!locked && (
                    <Space style={{ marginTop: 14, width: '100%', justifyContent: 'space-between' }}>
                      <Popconfirm title="删除节点？" onConfirm={deleteNode}>
                        <Button size="small" danger icon={<DeleteOutlined />}>删除节点</Button>
                      </Popconfirm>
                      <Button size="small" type="primary" icon={<SaveOutlined />} onClick={saveNode}>保存</Button>
                    </Space>
                  )}
                </Card>
                </div>
              ),
            },
            {
              key: 'agent',
              label: <span><RobotOutlined /> AI 助手</span>,
              children: (
                <div style={{ display: 'flex', flexDirection: 'column', height: 'calc(100vh - 200px)' }}>
                  <Card
                    size="small"
                    style={{
                      flex: 1, overflow: 'auto', borderRadius: 12, marginBottom: 10,
                      boxShadow: CARD_SHADOW, border: 'none',
                    }}
                    styles={{ body: { padding: 12 } }}
                  >
                    {chatMessages.length === 0 && (
                      <div style={{ textAlign: 'center', padding: 40, color: '#777169', fontSize: 12 }}>
                        <div style={{
                          width: 52, height: 52, margin: '0 auto 12px',
                          borderRadius: 14, background: '#f5f2ef',
                          display: 'flex', alignItems: 'center', justifyContent: 'center',
                        }}>
                          <RobotOutlined style={{ fontSize: 24, color: '#4e4e4e' }} />
                        </div>
                        <div style={{ fontSize: 14, fontWeight: 300, color: '#000', marginBottom: 4 }}>
                          让 Agent 帮你改流程
                        </div>
                        <span style={{ fontSize: 11 }}>
                          "给凭证录入加金额&gt;0规则" / "fork 凭证流程"
                        </span>
                      </div>
                    )}
                    {chatMessages.map((m, i) => {
                      const isUser = m.role === 'user';
                      return (
                        <div
                          key={i}
                          style={{
                            padding: '8px 12px', margin: '6px 0',
                            borderRadius: 12, fontSize: 12,
                            background: isUser ? '#000' : '#ffffff',
                            color: isUser ? '#fff' : '#000',
                            boxShadow: isUser ? 'none' : 'rgba(0,0,0,0.06) 0px 0px 0px 1px',
                            whiteSpace: 'pre-wrap',
                            letterSpacing: '0.01em',
                          }}
                        >
                          {m.content}
                          {m.tools?.length > 0 && (
                            <div style={{
                              marginTop: 4, fontSize: 10,
                              opacity: 0.65, letterSpacing: '0.02em',
                            }}>
                              工具: {m.tools.map(t => t.tool).join(', ')}
                            </div>
                          )}
                        </div>
                      );
                    })}
                    {chatLoading && <Spin size="small" style={{ display: 'block', margin: 10 }} />}
                    <div ref={chatEndRef} />
                  </Card>
                  <div style={{ display: 'flex', gap: 6 }}>
                    <Input
                      size="small"
                      value={chatInput}
                      onChange={e => setChatInput(e.target.value)}
                      onPressEnter={sendChat}
                      placeholder="跟 Agent 说..."
                      style={{ borderRadius: 10 }}
                    />
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
          <Form.Item
            name="doc_type"
            label="标识符（英文）"
            rules={[{ required: true }]}
            help="流程的英文标签，如 EXPENSE_REPORT。已存在的会自动加后缀"
          >
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
              <label style={{ fontSize: 13, color: '#4e4e4e' }}><input type="checkbox" /> 起始节点</label>
            </Form.Item>
            <Form.Item name="is_terminal" valuePropName="checked" noStyle>
              <label style={{ fontSize: 13, color: '#4e4e4e' }}><input type="checkbox" /> 终止节点</label>
            </Form.Item>
          </Space>
        </Form>
      </Modal>

      {/* === 修改记录弹窗 === */}
      <Modal
        title={<span><HistoryOutlined /> 修改记录 — {selected?.name}</span>}
        open={auditModal}
        onCancel={() => setAuditModal(false)}
        footer={null}
        width={780}
      >
        {auditLogs.length === 0 ? (
          <Empty description="无记录" />
        ) : (
          <div style={{ maxHeight: 500, overflow: 'auto' }}>
            {auditLogs.map(l => {
              const typeColor = {
                create:        { bg: '#ebf5ee', color: '#1f8f3a' },
                delete:        { bg: '#fdecea', color: '#b42318' },
                fork:          { bg: '#eaf1fb', color: '#1f5aa8' },
                fork_source:   { bg: '#eaf1fb', color: '#1f5aa8' },
                publish:       { bg: '#ebf5ee', color: '#1f8f3a' },
                disable:       { bg: '#fbf5e4', color: '#b8860b' },
                enable:        { bg: '#ebf5ee', color: '#1f8f3a' },
                edit_states:   { bg: '#e7f3f5', color: '#0e7490' },
                change_group:  { bg: '#f1ebfa', color: '#6b46c1' },
                save_positions:{ bg: '#f5f2ef', color: '#4e4e4e' },
              }[l.change_type] || { bg: '#f5f2ef', color: '#4e4e4e' };
              return (
                <div
                  key={l.id}
                  style={{
                    padding: 12, marginBottom: 10, borderRadius: 10,
                    background: l.danger_mode ? '#fdecea' : 'rgba(245,242,239,0.5)',
                    border: l.danger_mode
                      ? '1px solid #f5c6ce'
                      : '1px solid rgba(0,0,0,0.05)',
                    borderLeft: l.danger_mode ? '4px solid #b42318' : undefined,
                  }}
                >
                  <div style={{
                    display: 'flex', justifyContent: 'space-between', marginBottom: 6,
                    alignItems: 'center', flexWrap: 'wrap', gap: 6,
                  }}>
                    <Space size={6}>
                      <Pill bg={typeColor.bg} color={typeColor.color}>{l.change_type}</Pill>
                      {l.danger_mode && <Pill bg="#fff" color="#b42318">危险修改</Pill>}
                      <span style={{ fontSize: 12, color: '#4e4e4e', letterSpacing: '0.01em' }}>{l.by}</span>
                    </Space>
                    <span style={{
                      fontSize: 11, color: '#bfbbb5',
                      fontFamily: 'ui-monospace, monospace',
                    }}>
                      {l.timestamp?.replace('T', ' ').slice(0, 19)}
                    </span>
                  </div>
                  <div style={{ fontSize: 12, color: '#000', letterSpacing: '0.01em' }}>
                    {l.summary || '(无描述)'}
                  </div>
                  {l.ip && (
                    <div style={{
                      fontSize: 10, color: '#bfbbb5', marginTop: 4,
                      fontFamily: 'ui-monospace, monospace',
                    }}>
                      IP: {l.ip}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </Modal>
    </div>
  );
}
