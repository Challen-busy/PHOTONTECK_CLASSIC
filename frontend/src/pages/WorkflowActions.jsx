import { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { ReactFlow, Background, Controls, MiniMap, useNodesState, useEdgesState, MarkerType } from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { Card, Tag, Button, Spin, Badge, Segmented, Empty, Timeline, message } from 'antd';
import { ArrowLeftOutlined, ApartmentOutlined, UnorderedListOutlined, ClockCircleOutlined, RocketOutlined } from '@ant-design/icons';
import { layoutGraph } from '../utils/layout';
import { query } from '../api';
import api from '../api';

const stateColors = {
  DRAFT: '#d9d9d9', QUOTED: '#b37feb', PENDING_APPROVAL: '#faad14', APPROVED: '#52c41a',
  IN_PROCUREMENT: '#1890ff', READY_TO_SHIP: '#13c2c2', PARTIAL_SHIPPED: '#ffa940',
  SHIPPED: '#13c2c2', INVOICED: '#722ed1', COMPLETED: '#8c8c8c',
  CANCELLED: '#ff4d4f', ORDERED: '#1890ff', PARTIAL_RECEIVED: '#ffa940',
  RECEIVED: '#52c41a', INSPECTING: '#eb2f96', IN_WAREHOUSE: '#52c41a',
  PENDING_FINANCE: '#faad14', PICKING: '#722ed1', LABELING: '#eb2f96', PACKED: '#13c2c2',
  PENDING: '#faad14', RECEIVING: '#1890ff', DISCREPANCY: '#ff4d4f',
  AUDITED: '#1890ff', POSTED: '#52c41a', REVERSED: '#ff4d4f', RECONCILED: '#13c2c2', ADJUSTMENT: '#722ed1',
  PARTIAL: '#ffa940', PAID: '#52c41a', OVERDUE: '#ff4d4f', BAD_DEBT: '#434343',
  PROSPECTING: '#d9d9d9', QUALIFICATION: '#1890ff', SAMPLING: '#722ed1',
  TESTING: '#eb2f96', SMALL_BATCH: '#ffa940', MASS_PRODUCTION: '#52c41a', LOST: '#ff4d4f',
  ACTIVE: '#52c41a', EXPIRING: '#faad14', EXPIRED: '#8c8c8c', RENEWED: '#52c41a',
  OPEN: '#52c41a', VOUCHERS_DONE: '#1890ff', FX_ADJUSTED: '#722ed1', PL_TRANSFERRED: '#eb2f96', CLOSED: '#8c8c8c',
};

const tableMap = {
  SALES_ORDER: 'sales_order', PURCHASE_ORDER: 'purchase_order',
  SHIPMENT: 'shipment_request', VOUCHER: 'voucher',
  GOODS_RECEIPT: 'goods_receipt', PROJECT: 'project',
  FRAMEWORK_CONTRACT: 'framework_contract',
  ACCOUNTS_RECEIVABLE: 'accounts_receivable', ACCOUNTS_PAYABLE: 'accounts_payable',
  ACCOUNTING_PERIOD: 'accounting_period',
};

export default function WorkflowActions() {
  const navigate = useNavigate();
  const [workflows, setWorkflows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [selectedWf, setSelectedWf] = useState(null);
  const [nodes, setNodes, onNodesChange] = useNodesState([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState([]);
  const [stateCounts, setStateCounts] = useState({});
  const [viewMode, setViewMode] = useState('flow');  // 'flow' | 'overview'
  const [recentLogs, setRecentLogs] = useState([]);
  const [creating, setCreating] = useState(false);

  useEffect(() => {
    api.get('/workflows').then(r => { setWorkflows(r.data || []); setLoading(false); }).catch(() => setLoading(false));
  }, []);

  const enterWorkflow = async (wf) => {
    setNodes([]);
    setEdges([]);
    setSelectedWf(wf);

    const states = wf.states || [];
    // 边由 state.next 派生
    const transitions = states.flatMap(s =>
      (s.next || []).map(n => ({ from_state: s.code, to_state: n.to, name: n.label }))
    );
    const savedPositions = wf.node_positions || {};
    const hasSaved = Object.keys(savedPositions).length > 0;

    // 统计
    const table = tableMap[wf.doc_type];
    const counts = {};
    if (table) {
      for (const s of states) {
        try {
          const { data } = await query(table, { filters: { status: s.code }, limit: 1 });
          counts[s.code] = data.total || 0;
        } catch { counts[s.code] = 0; }
      }
    }
    setStateCounts(counts);

    // 加载该流程的最近操作日志
    try {
      const { data: logData } = await query('workflow_log', {
        filters: { doc_type: wf.doc_type }, order_by: '-timestamp', limit: 15,
      });
      setRecentLogs(logData.data || []);
    } catch { setRecentLogs([]); }

    let newNodes = states.map(s => ({
      id: s.code,
      position: hasSaved && savedPositions[s.code] ? savedPositions[s.code] : { x: 0, y: 0 },
      draggable: false,
      data: {
        label: (
          <div style={{ textAlign: 'center', cursor: 'pointer' }}>
            <div style={{ fontWeight: 600, fontSize: 12 }}>{s.name}</div>
            {counts[s.code] > 0 && <Badge count={counts[s.code]} size="small" style={{ backgroundColor: '#1a1a2e' }} />}
          </div>
        ),
      },
      style: {
        background: stateColors[s.code] || '#d9d9d9',
        color: ['DRAFT', 'COMPLETED', 'CLOSED', 'EXPIRED', 'PROSPECTING', 'OPEN'].includes(s.code) ? '#333' : '#fff',
        border: s.is_initial ? '3px solid #1a1a2e' : s.is_terminal ? '2px dashed #999' : '1px solid #ddd',
        borderRadius: 8, padding: '6px 14px', minWidth: 110, fontSize: 12,
      },
    }));

    // 流程图只画业务状态推进 — 过滤掉"创建"(from="")和"编辑"(自循环)元转换
    const stateCodeSet = new Set(states.map(s => s.code));
    const newEdges = transitions
      .filter(t => t.from_state && t.from_state !== t.to_state && stateCodeSet.has(t.from_state) && stateCodeSet.has(t.to_state))
      .map((t, i) => ({
        id: `e-${i}`, source: t.from_state, target: t.to_state, label: t.name,
        labelStyle: { fontSize: 10, fill: '#555' }, labelBgStyle: { fill: '#fff', fillOpacity: 0.9 },
        markerEnd: { type: MarkerType.ArrowClosed, width: 12, height: 12 },
        style: { strokeWidth: 1.5, stroke: '#999' }, type: 'smoothstep',
      }));

    if (!hasSaved) newNodes = layoutGraph(newNodes, newEdges, 'TB');
    setNodes(newNodes);
    setEdges(newEdges);
  };

  const onNodeClick = useCallback((_, node) => {
    if (!selectedWf) return;
    navigate(`/node/${selectedWf.id}/${node.id}`);
  }, [selectedWf, navigate]);

  const createDoc = async () => {
    try {
      setCreating(true);
      const { data } = await api.post('/transition', {
        doc_type: selectedWf.doc_type,
        doc_id: null,
      });
      if (data.success) {
        message.success(`已创建 #${data.doc_id}，进入【${data.to_state}】。现在点推进进入首个业务节点录入数据`);
        navigate(`/node/${selectedWf.id}/${data.to_state}`);
      } else {
        message.error(data.error || '创建失败');
      }
    } catch (e) {
      message.error(e.response?.data?.detail || '创建失败');
    }
    setCreating(false);
  };

  if (loading) return <Spin size="large" style={{ display: 'block', margin: '80px auto' }} />;

  // === 第一层：按分组的流程卡片 ===
  if (!selectedWf) {
    const grouped = workflows.reduce((acc, wf) => {
      const g = wf.group_name || '其他';
      (acc[g] = acc[g] || []).push(wf);
      return acc;
    }, {});
    return (
      <div>
        <h2 style={{ fontSize: 20, fontWeight: 600, color: '#1a1a2e', marginBottom: 16 }}>业务流程</h2>
        {Object.entries(grouped).map(([groupName, wfs]) => (
          <div key={groupName} style={{ marginBottom: 24 }}>
            <h3 style={{ fontSize: 14, color: '#666', marginBottom: 10, borderLeft: '3px solid #1a1a2e', paddingLeft: 8 }}>{groupName}</h3>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))', gap: 12 }}>
              {wfs.map(wf => (
                <Card key={wf.id} hoverable style={{ borderRadius: 12 }} onClick={() => enterWorkflow(wf)}>
                  <div style={{ fontSize: 15, fontWeight: 600, color: '#1a1a2e' }}>{wf.name}</div>
                  <div style={{ marginTop: 4 }}>
                    <Tag>{wf.doc_type}</Tag>
                    <span style={{ color: '#888', fontSize: 12 }}>{(wf.states || []).length}个节点</span>
                  </div>
                  {wf.description && <div style={{ color: '#666', fontSize: 11, marginTop: 6 }}>{wf.description.slice(0, 60)}...</div>}
                </Card>
              ))}
            </div>
          </div>
        ))}
      </div>
    );
  }

  // === 第二层：流程图 / 总览切换 ===
  const totalActive = Object.entries(stateCounts)
    .filter(([code]) => !selectedWf.states?.find(s => s.code === code)?.is_terminal)
    .reduce((sum, [, v]) => sum + v, 0);

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 12 }}>
        <Button icon={<ArrowLeftOutlined />} onClick={() => setSelectedWf(null)}>返回</Button>
        <h2 style={{ fontSize: 18, fontWeight: 600, color: '#1a1a2e', margin: 0 }}>{selectedWf.name}</h2>
        <Tag>{selectedWf.doc_type}</Tag>
        <Tag color="blue">进行中 {totalActive}</Tag>
        <div style={{ flex: 1 }} />
        <Segmented value={viewMode} onChange={setViewMode}
          options={[
            { value: 'flow', label: '流程图', icon: <ApartmentOutlined /> },
            { value: 'overview', label: '总览', icon: <UnorderedListOutlined /> },
          ]} />
        <Button type="primary" icon={<RocketOutlined />} loading={creating} onClick={createDoc}>
          开始新{selectedWf.name}
        </Button>
      </div>

      {viewMode === 'flow' ? (
        <Card style={{ borderRadius: 12, height: 'calc(100vh - 160px)' }} styles={{ body: { padding: 0, height: '100%' } }}>
          <ReactFlow nodes={nodes} edges={edges} onNodesChange={onNodesChange} onEdgesChange={onEdgesChange}
            onNodeClick={onNodeClick} fitView defaultEdgeOptions={{ type: 'smoothstep' }}>
            <Background />
            <Controls />
            <MiniMap style={{ borderRadius: 8 }} nodeStrokeWidth={2} />
          </ReactFlow>
        </Card>
      ) : (
        <div style={{ display: 'flex', gap: 12 }}>
          {/* 左：各状态的单据数量分布 */}
          <Card size="small" style={{ flex: 1, borderRadius: 12 }} title="正在进行的流程">
            {(selectedWf.states || []).filter(s => (stateCounts[s.code] || 0) > 0).length === 0 ? (
              <Empty description="当前该流程无单据" />
            ) : (
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
                {(selectedWf.states || []).map(s => {
                  const count = stateCounts[s.code] || 0;
                  if (count === 0) return null;
                  return (
                    <div key={s.code}
                      style={{
                        padding: '10px 16px', borderRadius: 8, cursor: 'pointer',
                        background: stateColors[s.code] || '#f0f0f0',
                        color: ['DRAFT', 'COMPLETED', 'CLOSED', 'EXPIRED', 'PROSPECTING', 'OPEN'].includes(s.code) ? '#333' : '#fff',
                        minWidth: 120, textAlign: 'center',
                      }}
                      onClick={() => navigate(`/node/${selectedWf.id}/${s.code}`)}>
                      <div style={{ fontSize: 13, fontWeight: 500 }}>{s.name}</div>
                      <div style={{ fontSize: 22, fontWeight: 700, marginTop: 4 }}>{count}</div>
                      {s.is_initial && <Tag color="gold" style={{ marginTop: 4 }}>起始</Tag>}
                      {s.is_terminal && <Tag style={{ marginTop: 4 }}>终止</Tag>}
                    </div>
                  );
                })}
              </div>
            )}
          </Card>
          {/* 右：最近操作 */}
          <Card size="small" style={{ width: 360, borderRadius: 12 }}
            title={<span><ClockCircleOutlined /> 最近操作</span>}>
            {recentLogs.length === 0 ? <Empty description="无记录" image={Empty.PRESENTED_IMAGE_SIMPLE} /> : (
              <Timeline style={{ marginTop: 8 }}
                items={recentLogs.map(l => ({
                  color: ['CANCELLED', 'REJECTED', 'REVERSED'].includes(l.to_state) ? 'red' :
                         ['COMPLETED', 'CLOSED', 'PAID'].includes(l.to_state) ? 'green' : 'blue',
                  children: (
                    <div style={{ fontSize: 12 }}>
                      <div style={{ fontWeight: 500 }}>
                        {l.transition_name}
                        <span style={{ color: '#888', marginLeft: 4 }}>#{l.doc_id}</span>
                      </div>
                      <div style={{ color: '#888' }}>{l.from_state || '(空)'} → {l.to_state}</div>
                      <div style={{ color: '#999', fontSize: 11 }}>{l.timestamp?.replace('T', ' ').slice(0, 19)}</div>
                    </div>
                  ),
                }))} />
            )}
          </Card>
        </div>
      )}
    </div>
  );
}
