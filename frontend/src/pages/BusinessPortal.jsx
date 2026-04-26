import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Button, Card, Col, Empty, Row, Spin, Tag } from 'antd';
import {
  AuditOutlined, BankOutlined, CheckSquareOutlined, DollarOutlined,
  FileDoneOutlined, FileTextOutlined, InboxOutlined, ProjectOutlined,
  ShoppingCartOutlined, ShoppingOutlined, TeamOutlined, TruckOutlined,
} from '@ant-design/icons';
import { aggregate, getWorkflows } from '../api';

const CARD_SHADOW =
  'rgba(0,0,0,0.06) 0px 0px 0px 1px, rgba(0,0,0,0.04) 0px 1px 2px, rgba(0,0,0,0.04) 0px 2px 4px';

const DOMAIN = {
  crm: {
    title: 'CRM',
    subtitle: '客户、询价、报价和销售订单前置管理',
    color: '#1f8f3a',
    bg: '#ebf5ee',
    workflows: [
      { docType: 'SALES_INQUIRY', title: '客户询价', desc: '录入客户需求、目标价、交期、包装和条码要求', icon: <TeamOutlined />, table: 'sales_inquiry' },
      { docType: 'QUOTATION', title: '报价单', desc: 'PM 授权报价，客户确认后转销售订单', icon: <FileDoneOutlined />, table: 'quotation' },
      { docType: 'SALES_ORDER', title: '销售订单', desc: '客户确认后的正式订单和履约源单', icon: <ShoppingCartOutlined />, table: 'sales_order' },
    ],
    data: [
      { table: 'customer', title: '客户主数据', icon: <TeamOutlined /> },
      { table: 'project', title: '选型项目', icon: <ProjectOutlined /> },
      { table: 'sales_inquiry', title: '客户询价', icon: <FileTextOutlined /> },
      { table: 'quotation', title: '报价单', icon: <FileDoneOutlined /> },
    ],
  },
  erp: {
    title: 'ERP',
    subtitle: '订单、采购、收付款、发票、勾稽和核算',
    color: '#1f5aa8',
    bg: '#eaf1fb',
    workflows: [
      { docType: 'SALES_ORDER', title: '销售订单履约', desc: '销售审核、预收判断、采购通知和发货准备', icon: <ShoppingCartOutlined />, table: 'sales_order' },
      { docType: 'PURCHASE_NOTICE', title: '采购通知', desc: '销售需求传递给采购侧，生成采购订单', icon: <ShoppingOutlined />, table: 'purchase_notice' },
      { docType: 'PURCHASE_ORDER', title: '采购订单履约', desc: '采购审核、预付判断、到货和采购核算', icon: <ShoppingOutlined />, table: 'purchase_order' },
      { docType: 'ADVANCE_RECEIPT', title: '预收单', desc: '客户未发货前付款，关联销售订单', icon: <DollarOutlined />, table: 'advance_receipt' },
      { docType: 'ADVANCE_PAYMENT', title: '预付单', desc: '提前支付供应商款项，关联采购订单', icon: <DollarOutlined />, table: 'advance_payment' },
      { docType: 'PURCHASE_INVOICE', title: '采购发票勾稽', desc: '采购发票与外购入库匹配，生成应付', icon: <AuditOutlined />, table: 'purchase_invoice' },
      { docType: 'SALES_INVOICE', title: '销售发票勾稽', desc: '销售发票与出库匹配，生成应收和成本基础', icon: <AuditOutlined />, table: 'sales_invoice' },
    ],
    data: [
      { table: 'accounts_receivable', title: '应收账款', icon: <BankOutlined /> },
      { table: 'accounts_payable', title: '应付账款', icon: <BankOutlined /> },
      { table: 'voucher', title: '凭证', icon: <FileTextOutlined /> },
      { table: 'inventory_transaction', title: '库存流水', icon: <InboxOutlined /> },
    ],
  },
  wms: {
    title: 'WMS',
    subtitle: '收货、入库、库存、包装、贴标、复检、出库和退货',
    color: '#b8860b',
    bg: '#fbf5e4',
    workflows: [
      { docType: 'GOODS_RECEIPT', title: '采购收货入库', desc: '仓库收货、PA 审核，审核通过生成库存批次', icon: <InboxOutlined />, table: 'goods_receipt' },
      { docType: 'SHIPMENT', title: '发货出库', desc: '财务放行、包装贴标、拣货复检和销售出库', icon: <TruckOutlined />, table: 'shipment_request' },
      { docType: 'SALES_RETURN', title: '客户退货', desc: '退货通知、物流收货、退货入库和红字处理入口', icon: <TruckOutlined />, table: 'sales_return' },
      { docType: 'INVENTORY', title: '库存管理', desc: '实仓库存、批次和出入库流水', icon: <InboxOutlined />, table: 'inventory' },
    ],
    data: [
      { table: 'inventory', title: '库存批次', icon: <InboxOutlined /> },
      { table: 'warehouse', title: '仓库', icon: <InboxOutlined /> },
      { table: 'warehouse_location', title: '库位', icon: <InboxOutlined /> },
      { table: 'label_template', title: '标签模板', icon: <FileTextOutlined /> },
    ],
  },
};

function Metric({ value }) {
  if (value == null) return <span style={{ color: '#bfbbb5' }}>暂无</span>;
  return <span>{Number(value).toLocaleString()} 条</span>;
}

export default function BusinessPortal({ type }) {
  const navigate = useNavigate();
  const cfg = DOMAIN[type] || DOMAIN.crm;
  const [workflows, setWorkflows] = useState([]);
  const [counts, setCounts] = useState({});
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const [{ data: wfData }, settled] = await Promise.all([
          getWorkflows(),
          Promise.allSettled(
            [...cfg.workflows, ...cfg.data]
              .filter((item, idx, arr) => arr.findIndex(x => x.table === item.table) === idx)
              .map(item => aggregate(item.table, 'id', 'COUNT').then(r => [item.table, r.data.value]))
          ),
        ]);
        if (!alive) return;
        const map = {};
        settled.forEach(r => {
          if (r.status === 'fulfilled') map[r.value[0]] = r.value[1];
        });
        setWorkflows(wfData || []);
        setCounts(map);
      } finally {
        if (alive) setLoading(false);
      }
    })();
    return () => { alive = false; };
  }, [cfg]);

  const workflowByDocType = useMemo(() => {
    const map = {};
    workflows.forEach(w => { map[w.doc_type] = w; });
    return map;
  }, [workflows]);

  if (loading) return <Spin size="large" style={{ display: 'block', margin: '80px auto' }} />;

  return (
    <div>
      <div style={{ marginBottom: 24 }}>
        <Tag style={{
          border: 'none',
          background: cfg.bg,
          color: cfg.color,
          fontWeight: 500,
          marginBottom: 10,
        }}>
          {cfg.title}
        </Tag>
        <h2 style={{
          margin: 0,
          color: '#000',
          fontSize: 28,
          fontWeight: 300,
          lineHeight: 1.15,
          letterSpacing: 0,
        }}>
          {cfg.subtitle}
        </h2>
      </div>

      <div style={{ marginBottom: 26 }}>
        <div style={{ fontSize: 13, fontWeight: 500, color: '#777169', marginBottom: 12 }}>
          流程入口
        </div>
        <Row gutter={[16, 16]}>
          {cfg.workflows.map(item => {
            const wf = workflowByDocType[item.docType];
            return (
              <Col xs={24} md={12} xl={8} key={item.docType}>
                <Card
                  hoverable={!!wf}
                  onClick={() => wf && navigate(`/actions/${wf.id}`)}
                  style={{
                    borderRadius: 8,
                    border: 'none',
                    height: '100%',
                    boxShadow: CARD_SHADOW,
                    cursor: wf ? 'pointer' : 'default',
                    opacity: wf ? 1 : 0.65,
                  }}
                  styles={{ body: { padding: 18 } }}
                >
                  <div style={{ display: 'flex', gap: 12, alignItems: 'flex-start' }}>
                    <div style={{
                      width: 36,
                      height: 36,
                      borderRadius: 8,
                      background: cfg.bg,
                      color: cfg.color,
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      fontSize: 17,
                      flexShrink: 0,
                    }}>
                      {item.icon}
                    </div>
                    <div style={{ minWidth: 0, flex: 1 }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10 }}>
                        <div style={{ color: '#000', fontWeight: 500, fontSize: 15 }}>{item.title}</div>
                        <span style={{ color: '#777169', fontSize: 12, whiteSpace: 'nowrap' }}>
                          <Metric value={counts[item.table]} />
                        </span>
                      </div>
                      <div style={{ color: '#777169', fontSize: 12, lineHeight: '18px', marginTop: 6 }}>
                        {item.desc}
                      </div>
                      {!wf && <div style={{ marginTop: 10 }}><Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="流程未启用" /></div>}
                    </div>
                  </div>
                </Card>
              </Col>
            );
          })}
        </Row>
      </div>

      <div>
        <div style={{ fontSize: 13, fontWeight: 500, color: '#777169', marginBottom: 12 }}>
          常用数据
        </div>
        <Row gutter={[12, 12]}>
          {cfg.data.map(item => (
            <Col xs={12} md={6} key={item.table}>
              <Button
                block
                onClick={() => navigate(`/data/${item.table}`)}
                style={{
                  height: 54,
                  borderRadius: 8,
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  borderColor: 'rgba(0,0,0,0.08)',
                }}
              >
                <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <span style={{ color: cfg.color }}>{item.icon}</span>
                  <span>{item.title}</span>
                </span>
                <CheckSquareOutlined style={{ color: '#bfbbb5' }} />
              </Button>
            </Col>
          ))}
        </Row>
      </div>
    </div>
  );
}
