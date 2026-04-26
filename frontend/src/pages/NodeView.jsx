/**
 * 节点独立页面 - 左侧单据列表 + 右侧DocEditor通用编辑器
 * 如果该节点有custom_html → 优先渲染
 */

import { useEffect, useRef, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { Card, Button, Space, Empty, Spin } from 'antd';
import { ArrowLeftOutlined, FileSearchOutlined } from '@ant-design/icons';
import { query, getTransitions } from '../api';
import api from '../api';
import DocEditor from '../components/DocEditor';
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

const tableMap = {
  SALES_INQUIRY: 'sales_inquiry', QUOTATION: 'quotation',
  SALES_ORDER: 'sales_order', PURCHASE_NOTICE: 'purchase_notice',
  PURCHASE_ORDER: 'purchase_order',
  SHIPMENT: 'shipment_request', VOUCHER: 'voucher', VOUCHER_ADJUSTMENT: 'voucher',
  GOODS_RECEIPT: 'goods_receipt', SALES_RETURN: 'sales_return', PROJECT: 'project',
  FRAMEWORK_CONTRACT: 'framework_contract',
  ACCOUNTS_RECEIVABLE: 'accounts_receivable', ACCOUNTS_PAYABLE: 'accounts_payable',
  ADVANCE_RECEIPT: 'advance_receipt', ADVANCE_PAYMENT: 'advance_payment',
  PURCHASE_INVOICE: 'purchase_invoice', SALES_INVOICE: 'sales_invoice',
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
  const openReport = (key, name) => setReportDrawer({ open: true, key, name });

  const loadData = async () => {
    const { data: wfs } = await api.get('/workflows');
    const wf = wfs.find(w => w.id === Number(workflowId));
    if (!wf) { navigate('/actions'); return; }
    setWorkflow(wf);

    const state = wf.states?.find(s => s.code === stateCode);
    setStateInfo(state || { code: stateCode, name: stateCode });

    const { data: allActions } = await getTransitions();
    const nodeActions = allActions.filter(a => a.doc_type === wf.doc_type && a.from_state === stateCode);
    setActions(nodeActions);

    if (state) {
      if (state.custom_html) setCustomHtml(state.custom_html);
      if (state.description) setNodePrompt(state.description);
    }

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
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 20 }}>
          <Button icon={<ArrowLeftOutlined />} onClick={() => navigate(`/actions/${workflowId}`)}>返回</Button>
          <h2 style={{
            margin: 0, fontSize: 22, fontWeight: 300,
            letterSpacing: '-0.01em', color: '#000', lineHeight: 1.15,
          }}>
            {stateInfo?.name}
            <span style={{ color: '#777169', fontWeight: 300 }}> — {workflow?.name}</span>
          </h2>
        </div>
        <Card style={{ borderRadius: 16, boxShadow: CARD_SHADOW, border: 'none' }}>
          <div ref={htmlRef} />
        </Card>
      </div>
    );
  }

  // === 通用页面 ===
  return (
    <div>
      <div style={{
        display: 'flex', alignItems: 'center', gap: 12,
        marginBottom: 16, flexWrap: 'wrap',
      }}>
        <Button icon={<ArrowLeftOutlined />} onClick={() => navigate(`/actions/${workflowId}`)}>返回</Button>
        <h2 style={{
          margin: 0, fontSize: 22, fontWeight: 300,
          letterSpacing: '-0.01em', color: '#000', lineHeight: 1.15,
        }}>
          {stateInfo?.name}
        </h2>
        <Pill bg="#eaf1fb" color="#1f5aa8">{workflow?.name}</Pill>
        <Pill bg="#f5f2ef" color="#4e4e4e">{docs.length} 条</Pill>
        {isInitial && <Pill bg="#fbf5e4" color="#b8860b">起始</Pill>}
      </div>

      {showReports && (
        <Card
          size="small"
          style={{ borderRadius: 16, marginBottom: 14, boxShadow: CARD_SHADOW, border: 'none' }}
          title={(
            <span style={{ fontSize: 13, fontWeight: 500, letterSpacing: '0.01em' }}>
              <FileSearchOutlined style={{ color: '#777169', marginRight: 6 }} />
              相关报表
            </span>
          )}
        >
          <Space wrap size={[8, 8]}>
            {reports.map(r => (
              <Button
                key={r.key}
                size="small"
                style={{ borderRadius: 9999, fontSize: 12 }}
                onClick={() => openReport(r.key, r.name)}
              >
                {r.name}
              </Button>
            ))}
          </Space>
        </Card>
      )}

      {docs.length === 0 ? (
        <Card style={{ borderRadius: 16, boxShadow: CARD_SHADOW, border: 'none' }}>
          <Empty
            description={isInitial
              ? `当前无单据 — 请在流程页点击【发起新${workflow?.name || '流程'}】`
              : '当前无单据在此节点'}
          />
        </Card>
      ) : (
        <div style={{ display: 'flex', gap: 14 }}>
          {/* 左侧：单据列表 */}
          <Card
            size="small"
            style={{
              width: 240, flexShrink: 0,
              borderRadius: 16, height: 'fit-content',
              boxShadow: CARD_SHADOW, border: 'none',
            }}
            title={<span style={{ fontSize: 13, fontWeight: 500, letterSpacing: '0.01em' }}>单据</span>}
            styles={{ body: { padding: 8 } }}
          >
            <div style={{ maxHeight: 600, overflow: 'auto' }}>
              {docs.map(d => {
                const selected = selectedDocId === d.id;
                const label = d.order_number || d.inquiry_number || d.quotation_number || d.notice_number
                           || d.voucher_number || d.shipment_number || d.return_number || d.payment_number
                           || d.receipt_number || d.contract_number || d.invoice_number || d.name;
                return (
                  <div
                    key={d.id}
                    style={{
                      padding: '10px 12px', borderRadius: 10, marginBottom: 4, cursor: 'pointer',
                      background: selected ? '#000' : 'transparent',
                      color: selected ? '#fff' : '#000',
                      transition: 'background 0.15s',
                    }}
                    onMouseEnter={e => { if (!selected) e.currentTarget.style.background = 'rgba(245, 242, 239, 0.6)'; }}
                    onMouseLeave={e => { if (!selected) e.currentTarget.style.background = 'transparent'; }}
                    onClick={() => setSelectedDocId(d.id)}
                  >
                    <div style={{ fontSize: 13, fontWeight: 500, letterSpacing: '0.01em' }}>
                      <span style={{
                        fontFamily: 'ui-monospace, monospace',
                        opacity: selected ? 0.7 : 0.5,
                        marginRight: 6,
                      }}>#{d.id}</span>
                      {label && label.slice(0, 15)}
                    </div>
                    {(d.total_amount != null || d.amount != null) && (
                      <div style={{
                        fontSize: 11, marginTop: 2,
                        color: selected ? 'rgba(255,255,255,0.75)' : '#777169',
                      }}>
                        {Number(d.total_amount ?? d.amount).toLocaleString()} {d.currency || ''}
                      </div>
                    )}
                  </div>
                );
              })}
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
