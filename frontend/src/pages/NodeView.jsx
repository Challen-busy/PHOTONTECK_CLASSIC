/**
 * 节点独立页面 - 左侧单据列表 + 右侧DocEditor通用编辑器
 * 如果该节点有custom_html → 优先渲染
 */

import { useEffect, useRef, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { Card, Tag, Button, Space, Empty, Spin } from 'antd';
import { ArrowLeftOutlined, FileSearchOutlined } from '@ant-design/icons';
import { query, getTransitions } from '../api';
import api from '../api';
import DocEditor from '../components/DocEditor';
import ReportDrawer from '../components/ReportDrawer';

const tableMap = {
  SALES_ORDER: 'sales_order', PURCHASE_ORDER: 'purchase_order',
  SHIPMENT: 'shipment_request', VOUCHER: 'voucher', VOUCHER_ADJUSTMENT: 'voucher',
  GOODS_RECEIPT: 'goods_receipt', PROJECT: 'project',
  FRAMEWORK_CONTRACT: 'framework_contract',
  ACCOUNTS_RECEIVABLE: 'accounts_receivable', ACCOUNTS_PAYABLE: 'accounts_payable',
  INVENTORY: 'inventory', INVENTORY_VIRTUAL: 'inventory', INVENTORY_COUNT: 'inventory',
  INVENTORY_COSTING: 'inventory_transaction',
};

export default function NodeView() {
  const { workflowId, stateCode } = useParams();
  const navigate = useNavigate();

  const [workflow, setWorkflow] = useState(null);
  const [stateInfo, setStateInfo] = useState(null);
  const [actions, setActions] = useState([]);
  const [docs, setDocs] = useState([]);
  const [selectedDocId, setSelectedDocId] = useState(null);
  const [loading, setLoading] = useState(true);
  const [customHtml, setCustomHtml] = useState('');
  const [nodePrompt, setNodePrompt] = useState('');

  const htmlRef = useRef(null);

  const isInitial = stateInfo?.is_initial;

  // 报表云朵配置（按 doc_type）
  // VOUCHER 报表已搬到流程图节点（WorkflowActions），此处只保留 AR
  const REPORT_CONFIG = {
    ACCOUNTS_RECEIVABLE: {
      states: new Set(['COLLECTING', 'VOUCHER_PROCESSED', 'CLOSED']),
      reports: [
        { key: 'ar_detail', name: '应收款明细表' },
        { key: 'ar_summary', name: '应收款汇总表' },
        { key: 'reconciliation', name: '往来对账单' },
        { key: 'aging_analysis', name: '账龄分析' },
        { key: 'due_list', name: '到期债权列表' },
        { key: 'contract_due_list', name: '合同到期款项列表' },
        { key: 'credit_limit', name: '信用额度分析' },
        { key: 'sales_analysis', name: '销售分析' },
        { key: 'collection_analysis', name: '回款分析' },
        { key: 'contract_exec', name: '合同金额执行汇总表' },
      ],
    },
  };
  const [reportDrawer, setReportDrawer] = useState({ open: false, key: '', name: '' });

  const reportCfg = REPORT_CONFIG[workflow?.doc_type];
  const showReports = reportCfg && reportCfg.states.has(stateCode);
  const reports = reportCfg?.reports || [];
  const openReport = (key, name) => {
    setReportDrawer({ open: true, key, name });
  };

  const loadData = async () => {
    // 加载流程定义
    const { data: wfs } = await api.get('/workflows');
    const wf = wfs.find(w => w.id === Number(workflowId));
    if (!wf) { navigate('/actions'); return; }
    setWorkflow(wf);

    const state = wf.states?.find(s => s.code === stateCode);
    setStateInfo(state || { code: stateCode, name: stateCode });

    // 加载用户可用操作（当前 state 的 next 列表，按角色过滤）
    const { data: allActions } = await getTransitions();
    const nodeActions = allActions.filter(a => a.doc_type === wf.doc_type && a.from_state === stateCode);
    setActions(nodeActions);

    // 节点描述和自定义HTML 直接来自 state
    if (state) {
      if (state.custom_html) setCustomHtml(state.custom_html);
      if (state.description) setNodePrompt(state.description);
    }

    // 加载该状态的单据
    const table = tableMap[wf.doc_type];
    if (table) {
      try {
        const { data } = await query(table, { filters: { status: stateCode }, limit: 50 });
        setDocs(data.data || []);
        if (data.data?.length > 0) setSelectedDocId(data.data[0].id);
      } catch {}
    }

    setLoading(false);
  };

  useEffect(() => {
    setLoading(true);
    loadData();
  }, [workflowId, stateCode]);

  useEffect(() => {
    if (customHtml && htmlRef.current) {
      htmlRef.current.innerHTML = customHtml;
    }
  }, [customHtml]);

  if (loading) return <Spin size="large" style={{ display: 'block', margin: '80px auto' }} />;

  // === 自定义HTML ===
  if (customHtml) {
    return (
      <div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 16 }}>
          <Button icon={<ArrowLeftOutlined />} onClick={() => navigate(`/actions/${workflowId}`)}>返回</Button>
          <h2 style={{ margin: 0, fontSize: 18, fontWeight: 600 }}>
            {stateInfo?.name} — {workflow?.name}
          </h2>
        </div>
        <Card style={{ borderRadius: 12 }}>
          <div ref={htmlRef} />
        </Card>
      </div>
    );
  }

  // === 通用页面 ===
  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 12 }}>
        <Button icon={<ArrowLeftOutlined />} onClick={() => navigate(`/actions/${workflowId}`)}>返回</Button>
        <h2 style={{ margin: 0, fontSize: 18, fontWeight: 600, color: '#1a1a2e' }}>
          {stateInfo?.name}
        </h2>
        <Tag color="blue">{workflow?.name}</Tag>
        <Tag>{docs.length} 条</Tag>
        {isInitial && <Tag color="gold">起始</Tag>}
      </div>

      {showReports && (
        <Card size="small" style={{ borderRadius: 12, marginBottom: 12 }}
          title={<span><FileSearchOutlined /> 相关报表</span>}>
          <Space wrap size={[8, 8]}>
            {reports.map(r => (
              <Button key={r.key} size="small" style={{ borderRadius: 14 }}
                onClick={() => openReport(r.key, r.name)}>{r.name}</Button>
            ))}
          </Space>
        </Card>
      )}

      {docs.length === 0 ? (
        <Card style={{ borderRadius: 12 }}>
          <Empty description={isInitial ? `当前无单据 — 请在流程页点击【发起新${workflow?.name || '流程'}】` : "当前无单据在此节点"} />
        </Card>
      ) : (
        <div style={{ display: 'flex', gap: 12 }}>
          {/* 左侧：单据列表 */}
          <Card size="small" style={{ width: 220, flexShrink: 0, borderRadius: 12, height: 'fit-content' }}
            title="单据">
            <div style={{ maxHeight: 600, overflow: 'auto' }}>
              {docs.map(d => (
                <div key={d.id}
                  style={{
                    padding: '8px 10px', borderRadius: 6, marginBottom: 4, cursor: 'pointer',
                    background: selectedDocId === d.id ? '#1a1a2e' : '#fafafa',
                    color: selectedDocId === d.id ? '#fff' : '#333',
                  }}
                  onClick={() => setSelectedDocId(d.id)}>
                  <div style={{ fontSize: 13, fontWeight: 500 }}>
                    #{d.id}
                    {(d.order_number || d.voucher_number || d.shipment_number || d.receipt_number || d.contract_number || d.invoice_number || d.name) &&
                      <span> · {(d.order_number || d.voucher_number || d.shipment_number || d.receipt_number || d.contract_number || d.invoice_number || d.name).slice(0, 15)}</span>
                    }
                  </div>
                  {(d.total_amount != null || d.amount != null) && (
                    <div style={{ fontSize: 11, opacity: 0.8 }}>
                      {Number(d.total_amount ?? d.amount).toLocaleString()} {d.currency || ''}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </Card>

          {/* 中间：DocEditor */}
          <div style={{ flex: 1, minWidth: 0 }}>
            {selectedDocId ? (
              <DocEditor
                docType={workflow.doc_type}
                docId={selectedDocId}
                currentState={stateCode}
                actions={actions}
                onRefresh={loadData}
                nodeDescription={nodePrompt}
              />
            ) : <Empty description="请选择单据" />}
          </div>
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
