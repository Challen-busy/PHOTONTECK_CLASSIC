/**
 * ReportDrawer - 报表抽屉组件
 * 支持: trial_balance / account_balance / aging_analysis
 * 其他报表 key 显示"即将上线"占位
 */

import { useEffect, useState } from 'react';
import { Drawer, Table, Select, Spin, Tag, Empty, Typography } from 'antd';
import api from '../api';

const { Text } = Typography;

const NUM = (v) => (v ?? 0).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });

// 试算平衡表列
const trialCols = [
  { title: '科目编码', dataIndex: 'account_code', width: 100 },
  { title: '科目名称', dataIndex: 'account_name', width: 150 },
  { title: '期初借方', dataIndex: 'opening_debit', align: 'right', render: NUM },
  { title: '期初贷方', dataIndex: 'opening_credit', align: 'right', render: NUM },
  { title: '本期借方', dataIndex: 'period_debit', align: 'right', render: NUM },
  { title: '本期贷方', dataIndex: 'period_credit', align: 'right', render: NUM },
  { title: '期末借方', dataIndex: 'closing_debit', align: 'right', render: NUM },
  { title: '期末贷方', dataIndex: 'closing_credit', align: 'right', render: NUM },
];

// 科目余额表列
const balanceCols = [
  { title: '科目编码', dataIndex: 'account_code', width: 100 },
  { title: '科目名称', dataIndex: 'account_name', width: 150 },
  { title: '类型', dataIndex: 'account_type', width: 80 },
  { title: '期初借方', dataIndex: 'opening_debit', align: 'right', render: NUM },
  { title: '期初贷方', dataIndex: 'opening_credit', align: 'right', render: NUM },
  { title: '本期借方', dataIndex: 'period_debit', align: 'right', render: NUM },
  { title: '本期贷方', dataIndex: 'period_credit', align: 'right', render: NUM },
  { title: '期末余额', dataIndex: 'net_balance', align: 'right', render: NUM },
  { title: '方向', dataIndex: 'direction_label', width: 60, align: 'center' },
];

// 账龄分析列
const agingCols = [
  { title: '客户', dataIndex: 'customer_name', width: 160 },
  { title: '发票号', dataIndex: 'invoice_number', width: 120 },
  { title: '金额', dataIndex: 'amount', align: 'right', render: NUM },
  { title: '已收', dataIndex: 'paid_amount', align: 'right', render: NUM },
  { title: '未清', dataIndex: 'outstanding', align: 'right', render: NUM },
  { title: '到期日', dataIndex: 'due_date', width: 100 },
  { title: '逾期天数', dataIndex: 'overdue_days', width: 80, align: 'right' },
  {
    title: '账龄', dataIndex: 'bucket', width: 90, align: 'center',
    render: (b) => {
      const map = { current: '未到期', d1_30: '1-30天', d31_60: '31-60天', d61_90: '61-90天', d90_plus: '90+天' };
      const color = { current: 'green', d1_30: 'gold', d31_60: 'orange', d61_90: 'red', d90_plus: 'magenta' };
      return <Tag color={color[b]}>{map[b]}</Tag>;
    },
  },
  { title: '币种', dataIndex: 'currency', width: 60 },
];

// 已实现的报表 key
const IMPLEMENTED = new Set(['trial_balance', 'account_balance', 'aging_analysis']);

export default function ReportDrawer({ open, onClose, reportKey, reportName }) {
  const [loading, setLoading] = useState(false);
  const [data, setData] = useState(null);
  const [periods, setPeriods] = useState([]);
  const [periodId, setPeriodId] = useState(null);

  const needsPeriod = reportKey === 'trial_balance' || reportKey === 'account_balance';

  // 加载会计期间列表
  useEffect(() => {
    if (!open || !needsPeriod) return;
    api.get('/reports/periods').then(({ data: res }) => {
      const list = res.periods || [];
      setPeriods(list);
      if (list.length > 0 && !periodId) {
        // 默认选当前月份的期间
        const now = new Date();
        const current = list.find(p => p.period_number === now.getMonth() + 1) || list[0];
        setPeriodId(current.id);
      }
    });
  }, [open, needsPeriod]);

  // 加载报表数据
  useEffect(() => {
    if (!open || !reportKey || !IMPLEMENTED.has(reportKey)) return;
    if (needsPeriod && !periodId) return;

    setLoading(true);
    let url = `/reports/${reportKey}`;
    if (needsPeriod) url += `?period_id=${periodId}`;

    api.get(url)
      .then(({ data: res }) => setData(res))
      .catch(() => setData(null))
      .finally(() => setLoading(false));
  }, [open, reportKey, periodId]);

  // 关闭时清理
  const handleClose = () => {
    setData(null);
    setPeriodId(null);
    onClose();
  };

  const renderContent = () => {
    if (!IMPLEMENTED.has(reportKey)) {
      return <Empty description={`[${reportName}] 即将上线`} />;
    }
    if (loading) return <Spin size="large" style={{ display: 'block', margin: '60px auto' }} />;
    if (!data) return <Empty description="暂无数据" />;

    if (reportKey === 'trial_balance') {
      return (
        <>
          {data.data?.length > 0 && (
            <Table
              dataSource={data.data}
              columns={trialCols}
              rowKey="account_code"
              size="small"
              pagination={false}
              bordered
              summary={() => (
                <Table.Summary fixed>
                  <Table.Summary.Row style={{ fontWeight: 700, background: '#fafafa' }}>
                    <Table.Summary.Cell index={0} colSpan={2}>
                      合计 {data.balanced
                        ? <Tag color="green">借贷平衡</Tag>
                        : <Tag color="red">借贷不平衡</Tag>}
                    </Table.Summary.Cell>
                    <Table.Summary.Cell index={2} align="right"><Text strong>{NUM(data.totals?.opening_debit)}</Text></Table.Summary.Cell>
                    <Table.Summary.Cell index={3} align="right"><Text strong>{NUM(data.totals?.opening_credit)}</Text></Table.Summary.Cell>
                    <Table.Summary.Cell index={4} align="right"><Text strong>{NUM(data.totals?.period_debit)}</Text></Table.Summary.Cell>
                    <Table.Summary.Cell index={5} align="right"><Text strong>{NUM(data.totals?.period_credit)}</Text></Table.Summary.Cell>
                    <Table.Summary.Cell index={6} align="right"><Text strong>{NUM(data.totals?.closing_debit)}</Text></Table.Summary.Cell>
                    <Table.Summary.Cell index={7} align="right"><Text strong>{NUM(data.totals?.closing_credit)}</Text></Table.Summary.Cell>
                  </Table.Summary.Row>
                </Table.Summary>
              )}
            />
          )}
          {(!data.data || data.data.length === 0) && <Empty description="该期间暂无过账凭证，无余额数据" />}
        </>
      );
    }

    if (reportKey === 'account_balance') {
      return data.data?.length > 0
        ? <Table dataSource={data.data} columns={balanceCols} rowKey="account_code" size="small" pagination={false} bordered />
        : <Empty description="该期间暂无过账凭证，无余额数据" />;
    }

    if (reportKey === 'aging_analysis') {
      return (
        <>
          {data.data?.length > 0 ? (
            <Table
              dataSource={data.data}
              columns={agingCols}
              rowKey={(r) => r.invoice_number + r.customer_code}
              size="small"
              pagination={false}
              bordered
              summary={() => (
                <Table.Summary fixed>
                  <Table.Summary.Row style={{ fontWeight: 700, background: '#fafafa' }}>
                    <Table.Summary.Cell index={0} colSpan={4}>合计</Table.Summary.Cell>
                    <Table.Summary.Cell index={4} align="right"><Text strong>{NUM(data.total_outstanding)}</Text></Table.Summary.Cell>
                    <Table.Summary.Cell index={5} colSpan={4} />
                  </Table.Summary.Row>
                </Table.Summary>
              )}
            />
          ) : <Empty description="暂无未清应收款" />}
          {data.bucket_totals && (
            <div style={{ marginTop: 12, display: 'flex', gap: 16, flexWrap: 'wrap' }}>
              <Tag color="green">未到期: {NUM(data.bucket_totals.current)}</Tag>
              <Tag color="gold">1-30天: {NUM(data.bucket_totals.d1_30)}</Tag>
              <Tag color="orange">31-60天: {NUM(data.bucket_totals.d31_60)}</Tag>
              <Tag color="red">61-90天: {NUM(data.bucket_totals.d61_90)}</Tag>
              <Tag color="magenta">90+天: {NUM(data.bucket_totals.d90_plus)}</Tag>
            </div>
          )}
        </>
      );
    }
    return null;
  };

  return (
    <Drawer
      open={open}
      onClose={handleClose}
      title={reportName}
      width="85%"
      destroyOnClose
    >
      {needsPeriod && periods.length > 0 && (
        <div style={{ marginBottom: 16 }}>
          <span style={{ marginRight: 8 }}>会计期间:</span>
          <Select
            value={periodId}
            onChange={setPeriodId}
            style={{ width: 200 }}
            options={periods.map(p => ({ value: p.id, label: p.label }))}
          />
        </div>
      )}
      {renderContent()}
    </Drawer>
  );
}
