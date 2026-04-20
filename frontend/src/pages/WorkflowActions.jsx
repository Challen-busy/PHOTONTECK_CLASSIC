import { useCallback, useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { ReactFlow, Background, Controls, MiniMap, useNodesState, useEdgesState, MarkerType } from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { Card, Button, Spin, Badge, Segmented, Empty, Timeline, message } from 'antd';
import {
  ArrowLeftOutlined, ApartmentOutlined, UnorderedListOutlined,
  ClockCircleOutlined, RocketOutlined,
} from '@ant-design/icons';
import { layoutGraph } from '../utils/layout';
import { query } from '../api';
import api from '../api';
import ReportDrawer from '../components/ReportDrawer';

const CARD_SHADOW =
  'rgba(0,0,0,0.06) 0px 0px 0px 1px, rgba(0,0,0,0.04) 0px 1px 2px, rgba(0,0,0,0.04) 0px 2px 4px';

function Pill({ bg, color, children }) {
  return (
    <span style={{
      display: 'inline-block', padding: '2px 10px', borderRadius: 4,
      background: bg, color, fontSize: 12, fontWeight: 500, letterSpacing: '0.02em',
    }}>{children}</span>
  );
}

// 报表节点 code → ReportDrawer key 映射
const REPORT_NODE_MAP = {
  RPT_GENERAL_LEDGER: { key: 'general_ledger', name: '总分类账' },
  RPT_DETAIL_LEDGER: { key: 'detail_ledger', name: '明细分类账' },
  RPT_MULTI_COL: { key: 'multi_column_ledger', name: '多栏账' },
  RPT_PROJECT_DETAIL: { key: 'project_ledger', name: '核算项目明细账' },
  RPT_PROJECT_BALANCE: { key: 'project_balance', name: '核算项目余额表' },
  RPT_TRIAL_BALANCE: { key: 'trial_balance', name: '试算平衡表' },
  RPT_ACCOUNT_BALANCE: { key: 'account_balance', name: '科目余额表' },
  RPT_AR_DETAIL: { key: 'ar_detail', name: '应收款明细表' },
  RPT_AR_SUMMARY: { key: 'ar_summary', name: '应收款汇总表' },
  RPT_RECONCILIATION: { key: 'reconciliation', name: '往来对账单' },
  RPT_AGING: { key: 'aging_analysis', name: '账龄分析' },
  RPT_DUE_LIST: { key: 'due_list', name: '到期债权列表' },
  RPT_SALES_ANALYSIS: { key: 'sales_analysis', name: '销售分析' },
  RPT_COLLECTION: { key: 'collection_analysis', name: '回款分析' },
  RPT_CONTRACT_EXEC: { key: 'contract_exec', name: '合同金额执行汇总表' },
  RPT_CONTRACT_DUE: { key: 'contract_due_list', name: '合同到期款项列表' },
  RPT_CREDIT_LIMIT: { key: 'credit_limit', name: '信用额度分析' },
};

// 状态 → 淡底+深字+左色条 三元色
const NEUTRAL       = { bg: '#f5f2ef', color: '#4e4e4e', border: '#bfbbb5' };
const SEMANTIC_INFO = { bg: '#eaf1fb', color: '#1f5aa8', border: '#1f5aa8' };
const SEMANTIC_WARN = { bg: '#fbf5e4', color: '#b8860b', border: '#b8860b' };
const SEMANTIC_OK   = { bg: '#ebf5ee', color: '#1f8f3a', border: '#1f8f3a' };
const SEMANTIC_ERR  = { bg: '#fdecea', color: '#b42318', border: '#b42318' };
const SEMANTIC_TEAL = { bg: '#e7f3f5', color: '#0e7490', border: '#0e7490' };
const SEMANTIC_PURP = { bg: '#f1ebfa', color: '#6b46c1', border: '#6b46c1' };
const SEMANTIC_PINK = { bg: '#fbeaf1', color: '#b83280', border: '#b83280' };
const SEMANTIC_END  = { bg: '#f5f5f5', color: '#1a1a1a', border: '#4e4e4e' };

const stateColors = {
  DRAFT: NEUTRAL, PROSPECTING: NEUTRAL,
  QUOTED: SEMANTIC_PURP, SAMPLING: SEMANTIC_PURP, INVOICED: SEMANTIC_PURP,
  PICKING: SEMANTIC_PURP, ADJUSTMENT: SEMANTIC_PURP, FX_ADJUSTED: SEMANTIC_PURP,

  PENDING_APPROVAL: SEMANTIC_WARN, PENDING: SEMANTIC_WARN, PENDING_FINANCE: SEMANTIC_WARN,
  PARTIAL_SHIPPED: SEMANTIC_WARN, PARTIAL_RECEIVED: SEMANTIC_WARN, PARTIAL: SEMANTIC_WARN,
  EXPIRING: SEMANTIC_WARN, SMALL_BATCH: SEMANTIC_WARN,

  APPROVED: SEMANTIC_OK, RECEIVED: SEMANTIC_OK, IN_WAREHOUSE: SEMANTIC_OK,
  POSTED: SEMANTIC_OK, PAID: SEMANTIC_OK, ACTIVE: SEMANTIC_OK, OPEN: SEMANTIC_OK,
  RENEWED: SEMANTIC_OK, MASS_PRODUCTION: SEMANTIC_OK,

  IN_PROCUREMENT: SEMANTIC_INFO, ORDERED: SEMANTIC_INFO, RECEIVING: SEMANTIC_INFO,
  AUDITED: SEMANTIC_INFO, QUALIFICATION: SEMANTIC_INFO, VOUCHERS_DONE: SEMANTIC_INFO,

  READY_TO_SHIP: SEMANTIC_TEAL, SHIPPED: SEMANTIC_TEAL, PACKED: SEMANTIC_TEAL,
  RECONCILED: SEMANTIC_TEAL,

  INSPECTING: SEMANTIC_PINK, LABELING: SEMANTIC_PINK, TESTING: SEMANTIC_PINK,
  PL_TRANSFERRED: SEMANTIC_PINK,

  CANCELLED: SEMANTIC_ERR, DISCREPANCY: SEMANTIC_ERR, REVERSED: SEMANTIC_ERR,
  OVERDUE: SEMANTIC_ERR, LOST: SEMANTIC_ERR,

  COMPLETED: SEMANTIC_END, CLOSED: SEMANTIC_END, EXPIRED: SEMANTIC_END,
  BAD_DEBT: SEMANTIC_END,
};

const tableMap = {
  SALES_ORDER: 'sales_order', PURCHASE_ORDER: 'purchase_order',
  SHIPMENT: 'shipment_request', VOUCHER: 'voucher',
  GOODS_RECEIPT: 'goods_receipt', PROJECT: 'project',
  FRAMEWORK_CONTRACT: 'framework_contract',
  ACCOUNTS_RECEIVABLE: 'accounts_receivable', ACCOUNTS_PAYABLE: 'accounts_payable',
  ACCOUNTING_PERIOD: 'accounting_period',
};

// 节点样式：淡底 + 深字 + 左色条
function getNodeStyle(s) {
  const t = s.node_type;
  if (t === 'policy') return {
    background: '#fbf5e4', color: '#8c6d1f',
    border: '1px solid #ece0b7', borderLeft: '4px solid #b8860b',
    borderRadius: 6, padding: '6px 14px', minWidth: 110, fontSize: 12,
  };
  if (t === 'cross_module') return {
    background: '#ebf5ee', color: '#1f8f3a',
    border: '1px solid #c7e6cf', borderLeft: '4px solid #1f8f3a',
    borderRadius: 9999, padding: '6px 14px', minWidth: 110, fontSize: 12,
  };
  if (t === 'report') return {
    background: '#eaf1fb', color: '#1f5aa8',
    border: '1px dashed #a8c4e7', borderRadius: 6,
    padding: '6px 14px', minWidth: 110, fontSize: 12,
  };
  const c = stateColors[s.code] || NEUTRAL;
  return {
    background: c.bg,
    color: c.color,
    border: `1px solid ${c.border}`,
    borderLeft: `4px solid ${c.border}`,
    boxShadow: s.is_initial
      ? 'rgba(0,0,0,0.06) 0px 0px 0px 1.5px, rgba(0,0,0,0.04) 0px 4px 8px'
      : s.is_terminal ? 'none' : 'rgba(0,0,0,0.04) 0px 1px 2px',
    borderRadius: 8,
    padding: '6px 14px',
    minWidth: 110,
    fontSize: 12,
    fontWeight: 500,
    letterSpacing: '0.01em',
    opacity: s.is_terminal ? 0.75 : 1,
    borderStyle: s.is_terminal ? 'dashed' : 'solid',
  };
}

export default function WorkflowActions() {
  const navigate = useNavigate();
  const { workflowId } = useParams();
  const [workflows, setWorkflows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [selectedWf, setSelectedWf] = useState(null);
  const [nodes, setNodes, onNodesChange] = useNodesState([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState([]);
  const [stateCounts, setStateCounts] = useState({});
  const [viewMode, setViewMode] = useState('flow');
  const [recentLogs, setRecentLogs] = useState([]);
  const [creating, setCreating] = useState(false);
  const [reportDrawer, setReportDrawer] = useState({ open: false, key: '', name: '' });

  useEffect(() => {
    api.get('/workflows').then(r => { setWorkflows(r.data || []); setLoading(false); }).catch(() => setLoading(false));
  }, []);

  useEffect(() => {
    if (workflowId && workflows.length > 0 && !selectedWf) {
      const wf = workflows.find(w => w.id === Number(workflowId));
      if (wf) enterWorkflow(wf);
    }
  }, [workflowId, workflows]);

  const enterWorkflow = async (wf) => {
    setNodes([]);
    setEdges([]);
    setSelectedWf(wf);

    const states = wf.states || [];
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
        if (s.node_type && s.node_type !== 'state') continue;
        try {
          const { data } = await query(table, { filters: { status: s.code }, limit: 1 });
          counts[s.code] = data.total || 0;
        } catch { counts[s.code] = 0; }
      }
    }
    setStateCounts(counts);

    // 最近操作日志
    try {
      const { data: logData } = await query('workflow_log', {
        filters: { doc_type: wf.doc_type }, order_by: '-timestamp', limit: 15,
      });
      setRecentLogs(logData.data || []);
    } catch { setRecentLogs([]); }

    const nodeTypeMap = {};
    states.forEach(s => { nodeTypeMap[s.code] = s.node_type || 'state'; });

    let newNodes = states.map(s => {
      const isDisplayOnly = s.node_type === 'policy';
      return {
        id: s.code,
        position: hasSaved && savedPositions[s.code] ? savedPositions[s.code] : { x: 0, y: 0 },
        draggable: false,
        data: {
          label: (
            <div style={{ textAlign: 'center', cursor: isDisplayOnly ? 'default' : 'pointer' }}>
              <div style={{ fontWeight: 500, fontSize: 12, letterSpacing: '0.01em' }}>{s.name}</div>
              {!isDisplayOnly && counts[s.code] > 0 && (
                <Badge
                  count={counts[s.code]}
                  size="small"
                  style={{ backgroundColor: '#000', marginTop: 2 }}
                />
              )}
            </div>
          ),
        },
        style: getNodeStyle(s),
      };
    });

    const stateCodeSet = new Set(states.map(s => s.code));
    const newEdges = transitions
      .filter(t => t.from_state && t.from_state !== t.to_state && stateCodeSet.has(t.from_state) && stateCodeSet.has(t.to_state))
      .map((t, i) => {
        const isPolicy = nodeTypeMap[t.from_state] === 'policy';
        return {
          id: `e-${i}`, source: t.from_state, target: t.to_state,
          label: isPolicy ? '' : t.name,
          labelStyle: { fontSize: 10, fill: '#4e4e4e', letterSpacing: '0.02em' },
          labelBgStyle: { fill: '#fff', fillOpacity: 0.95 },
          markerEnd: { type: MarkerType.ArrowClosed, width: 12, height: 12, color: '#bfbbb5' },
          style: isPolicy
            ? { strokeWidth: 1.5, stroke: '#b8860b', strokeDasharray: '6 3' }
            : { strokeWidth: 1.5, stroke: '#bfbbb5' },
          type: 'smoothstep',
        };
      });

    if (!hasSaved) newNodes = layoutGraph(newNodes, newEdges, 'TB');
    setNodes(newNodes);
    setEdges(newEdges);
  };

  const onNodeClick = useCallback((_, node) => {
    if (!selectedWf) return;
    const st = (selectedWf.states || []).find(s => s.code === node.id);
    if (st?.node_type === 'policy') return;
    if (st?.node_type === 'report') {
      const rpt = REPORT_NODE_MAP[node.id];
      if (rpt) setReportDrawer({ open: true, key: rpt.key, name: rpt.name });
      return;
    }
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
        message.success(`已创建 #${data.doc_id}，进入【${data.to_state}】`);
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
    if (workflowId) return <Spin size="large" style={{ display: 'block', margin: '80px auto' }} />;
    const grouped = workflows.reduce((acc, wf) => {
      const g = wf.group_name || '其他';
      (acc[g] = acc[g] || []).push(wf);
      return acc;
    }, {});
    return (
      <div>
        <h2 style={{
          fontSize: 28, fontWeight: 300, letterSpacing: '-0.01em',
          color: '#000', margin: '0 0 24px', lineHeight: 1.15,
        }}>
          业务流程
        </h2>
        {Object.entries(grouped).map(([groupName, wfs]) => (
          <div key={groupName} style={{ marginBottom: 32 }}>
            <h3 style={{
              fontSize: 12, fontWeight: 500, color: '#777169', letterSpacing: '0.04em',
              textTransform: 'uppercase', margin: '0 0 12px',
            }}>
              {groupName}
            </h3>
            <div style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))',
              gap: 14,
            }}>
              {wfs.map(wf => (
                <Card
                  key={wf.id}
                  hoverable
                  style={{
                    borderRadius: 16,
                    boxShadow: CARD_SHADOW,
                    border: 'none',
                    cursor: 'pointer',
                  }}
                  styles={{ body: { padding: 18 } }}
                  onClick={() => enterWorkflow(wf)}
                >
                  <div style={{
                    fontSize: 16, fontWeight: 500, color: '#000',
                    letterSpacing: '0.01em', marginBottom: 8,
                  }}>
                    {wf.name}
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
                    <Pill bg="#eaf1fb" color="#1f5aa8">{wf.doc_type}</Pill>
                    <span style={{ color: '#777169', fontSize: 12 }}>
                      {(wf.states || []).length} 个节点
                    </span>
                  </div>
                  {wf.description && (
                    <div style={{
                      color: '#4e4e4e', fontSize: 12, marginTop: 8,
                      letterSpacing: '0.01em', lineHeight: 1.45,
                    }}>
                      {wf.description.slice(0, 60)}{wf.description.length > 60 ? '…' : ''}
                    </div>
                  )}
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
      <div style={{
        display: 'flex', alignItems: 'center', gap: 12,
        marginBottom: 14, flexWrap: 'wrap',
      }}>
        <Button icon={<ArrowLeftOutlined />} onClick={() => { setSelectedWf(null); navigate('/actions', { replace: true }); }}>返回</Button>
        <h2 style={{
          fontSize: 22, fontWeight: 300, letterSpacing: '-0.01em',
          color: '#000', margin: 0, lineHeight: 1.15,
        }}>
          {selectedWf.name}
        </h2>
        <Pill bg="#eaf1fb" color="#1f5aa8">{selectedWf.doc_type}</Pill>
        <Pill bg="#fbf5e4" color="#b8860b">进行中 {totalActive}</Pill>
        <div style={{ flex: 1 }} />
        <Segmented
          value={viewMode}
          onChange={setViewMode}
          options={[
            { value: 'flow', label: '流程图', icon: <ApartmentOutlined /> },
            { value: 'overview', label: '总览', icon: <UnorderedListOutlined /> },
          ]}
        />
        <Button type="primary" icon={<RocketOutlined />} loading={creating} onClick={createDoc}>
          发起新{selectedWf.name}
        </Button>
      </div>

      {viewMode === 'flow' ? (
        <Card
          style={{
            borderRadius: 16, height: 'calc(100vh - 160px)',
            boxShadow: CARD_SHADOW, border: 'none', overflow: 'hidden',
          }}
          styles={{ body: { padding: 0, height: '100%' } }}
        >
          <ReactFlow
            nodes={nodes} edges={edges}
            onNodesChange={onNodesChange} onEdgesChange={onEdgesChange}
            onNodeClick={onNodeClick} fitView
            defaultEdgeOptions={{ type: 'smoothstep' }}
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
        </Card>
      ) : (
        <div style={{ display: 'flex', gap: 14 }}>
          {/* 左：各状态单据分布 */}
          <Card
            size="small"
            style={{ flex: 1, borderRadius: 16, boxShadow: CARD_SHADOW, border: 'none' }}
            title={<span style={{ fontSize: 14, fontWeight: 500, letterSpacing: '0.01em' }}>正在进行的流程</span>}
          >
            {(selectedWf.states || []).filter(s => (stateCounts[s.code] || 0) > 0).length === 0 ? (
              <Empty description="当前该流程无单据" />
            ) : (
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10 }}>
                {(selectedWf.states || []).map(s => {
                  const count = stateCounts[s.code] || 0;
                  if (count === 0) return null;
                  const c = stateColors[s.code] || NEUTRAL;
                  return (
                    <div
                      key={s.code}
                      style={{
                        padding: '14px 20px', borderRadius: 12, cursor: 'pointer',
                        background: c.bg, color: c.color,
                        borderLeft: `4px solid ${c.border}`,
                        border: `1px solid ${c.border}`,
                        borderLeftWidth: 4,
                        minWidth: 140, textAlign: 'center',
                        boxShadow: 'rgba(0,0,0,0.04) 0px 1px 2px',
                        transition: 'transform 0.15s',
                      }}
                      onMouseEnter={e => (e.currentTarget.style.transform = 'translateY(-1px)')}
                      onMouseLeave={e => (e.currentTarget.style.transform = 'none')}
                      onClick={() => navigate(`/node/${selectedWf.id}/${s.code}`)}
                    >
                      <div style={{ fontSize: 13, fontWeight: 500, letterSpacing: '0.01em' }}>{s.name}</div>
                      <div style={{
                        fontSize: 28, fontWeight: 300, marginTop: 4,
                        letterSpacing: '-0.02em', lineHeight: 1.1,
                      }}>
                        {count}
                      </div>
                      <div style={{ marginTop: 6, display: 'flex', gap: 4, justifyContent: 'center' }}>
                        {s.is_initial && <Pill bg="#fff" color={c.color}>起始</Pill>}
                        {s.is_terminal && <Pill bg="#fff" color={c.color}>终止</Pill>}
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </Card>
          {/* 右：最近操作 */}
          <Card
            size="small"
            style={{ width: 380, borderRadius: 16, boxShadow: CARD_SHADOW, border: 'none' }}
            title={(
              <span style={{ fontSize: 14, fontWeight: 500, letterSpacing: '0.01em' }}>
                <ClockCircleOutlined style={{ color: '#777169', marginRight: 6 }} />
                最近操作
              </span>
            )}
          >
            {recentLogs.length === 0 ? (
              <Empty description="无记录" image={Empty.PRESENTED_IMAGE_SIMPLE} />
            ) : (
              <Timeline
                style={{ marginTop: 8 }}
                items={recentLogs.map(l => ({
                  color: ['CANCELLED', 'REJECTED', 'REVERSED'].includes(l.to_state) ? '#b42318'
                       : ['COMPLETED', 'CLOSED', 'PAID'].includes(l.to_state) ? '#1f8f3a'
                       : '#1f5aa8',
                  children: (
                    <div style={{ fontSize: 12, paddingBottom: 2 }}>
                      <div style={{ fontWeight: 500, color: '#000', letterSpacing: '0.01em' }}>
                        {l.transition_name}
                        <span style={{
                          color: '#bfbbb5', marginLeft: 6,
                          fontFamily: 'ui-monospace, monospace', fontWeight: 400,
                        }}>
                          #{l.doc_id}
                        </span>
                      </div>
                      <div style={{ color: '#777169', marginTop: 2 }}>
                        {l.from_state || '(空)'} → {l.to_state}
                      </div>
                      <div style={{
                        color: '#bfbbb5', fontSize: 11, marginTop: 1,
                        fontFamily: 'ui-monospace, monospace',
                      }}>
                        {l.timestamp?.replace('T', ' ').slice(0, 19)}
                      </div>
                    </div>
                  ),
                }))}
              />
            )}
          </Card>
        </div>
      )}

      <ReportDrawer
        open={reportDrawer.open}
        onClose={() => setReportDrawer({ open: false, key: '', name: '' })}
        reportKey={reportDrawer.key}
        reportName={reportDrawer.name}
      />
    </div>
  );
}
