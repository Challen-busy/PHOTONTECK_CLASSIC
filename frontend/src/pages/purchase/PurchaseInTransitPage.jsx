/**
 * PurchaseInTransitPage —— 采购在途台账（原厂 → 我方，人工跟踪 + 货期/到货提醒，PRD 04a-6）➕
 *
 * PA 跟「已下单未到货」的在途货（下 PO 后货期 20 周很常见）。现状痛点：系统无跟踪提醒，全靠刷飞书表/邮件催，
 * 人离职就跟丢。本页补这个洞：在途台账（只读聚合）+ 货期/到货提醒。
 *
 * 只读 BizTable over 聚合端点 /api/purchase/intransit（沿 PO_line received 聚合：订单/已收/在途=订单-已收/
 * 承诺ETA/最新ETA/跟踪状态/提醒标记）。在途台账无买价列（纯数量/ETA 跟踪），不涉 Q18 防火墙。
 *   - 按 PA 过滤（PA「只拉我的数据」，purchase_assistant_id = 当前用户；可切全部）。
 *   - 提醒标记 alert_flag 为红：超期未给货期 / 超期未发货（后端提醒命令扫出）。
 *   - 「刷新提醒」按钮调提醒扫描命令 /api/purchase/intransit/scan-alerts（手动触发轻量扫描，引擎无定时器，
 *     扫「承诺 ETA 过期且未发货」→ 经 services/notifications.dispatch 写站内提醒，复用通知中心）。
 *
 * ★引擎实况：引擎无在途模型、无提醒/定时器。后端段2c ➕ purchase_in_transit 聚合端点 + 提醒扫描命令。
 *   端点未就绪时显示「功能已就绪 · 待后端开通」占位（14 律 §8），就绪后自动点亮——不写死行/状态。
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { Alert, App, Button, Empty, Segmented, Space, Tag } from 'antd';
import { ReloadOutlined, BellOutlined } from '@ant-design/icons';
import { BizTable } from '../../components/biz';
import { useAuth } from '../../auth';
import { getPurchaseIntransit, scanPurchaseIntransitAlerts } from '../../api';
import { StatusPillInline } from '../wms/StatusPill';

const PA_ROLE = 'PRODUCT_ASSISTANT';
const MONO = 'ui-monospace, SFMono-Regular, Menlo, monospace';

// 跟踪状态候选（PRD 04a-6：待确认接单/已接单待货期/已给货期/已发货/部分到货/已到货）——筛选提示用。
function num(v) {
  return v == null ? <span style={{ color: '#bfbbb5' }}>—</span>
    : <span style={{ fontFamily: MONO }}>{Number(v).toLocaleString()}</span>;
}
function dateCell(v) {
  return v ? String(v).slice(0, 10) : <span style={{ color: '#bfbbb5' }}>—</span>;
}

export default function PurchaseInTransitPage() {
  const { user } = useAuth();
  const { message } = App.useApp();
  const isPA = user?.role === PA_ROLE;
  const [scope, setScope] = useState(isPA ? 'mine' : 'all');
  const [rows, setRows] = useState([]);
  const [ready, setReady] = useState(null);   // null=未知 true=就绪 false=端点未开通
  const [loading, setLoading] = useState(false);
  const [scanning, setScanning] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    const params = scope === 'mine' && user?.id ? { purchase_assistant_id: user.id } : {};
    try {
      const { data } = await getPurchaseIntransit(params);
      setRows(data?.rows || []);
      setReady(true);
    } catch {
      setRows([]);
      setReady(false);
    } finally {
      setLoading(false);
    }
  }, [scope, user]);

  useEffect(() => { load(); }, [load]);

  const scanAlerts = useCallback(async () => {
    setScanning(true);
    try {
      const { data } = await scanPurchaseIntransitAlerts();
      const n = data?.alerts ?? data?.count ?? data?.notified;
      message.success(typeof n === 'number' ? `提醒扫描完成 · 命中 ${n} 条（已写站内提醒，见通知中心）` : '提醒扫描完成（已写站内提醒，见通知中心）');
      load();
    } catch (e) {
      message.error(e.response?.data?.detail || '提醒扫描命令未就绪（待后端段2c 开通）');
    } finally {
      setScanning(false);
    }
  }, [message, load]);

  const columns = useMemo(() => [
    { title: 'PO 号', dataIndex: 'order_number', width: 150, fixed: 'left',
      render: (v) => v || <span style={{ color: '#bfbbb5' }}>—</span> },
    { title: '提醒', dataIndex: 'alert_flag', width: 130, fixed: 'left',
      filters: [
        { text: '超期未给货期', value: 'NO_ETA' },
        { text: '超期未发货', value: 'OVERDUE' },
      ],
      onFilter: (val, row) => row.alert_flag === val,
      render: (v) => {
        if (!v || v === 'OK') return <span style={{ color: '#bfbbb5' }}>—</span>;
        const text = v === 'NO_ETA' ? '超期未给货期' : v === 'OVERDUE' ? '超期未发货' : v;
        return <Tag color="error">{text}</Tag>;
      } },
    { title: '供应商', dataIndex: 'supplier_id', width: 110,
      render: (v) => (v != null ? `#${v}` : <span style={{ color: '#bfbbb5' }}>—</span>) },
    { title: '型号', dataIndex: 'material_id', width: 120,
      render: (v) => (v != null ? `#${v}` : <span style={{ color: '#bfbbb5' }}>—</span>) },
    { title: '订单数量', dataIndex: 'ordered_qty', width: 110, align: 'right', render: num },
    { title: '已到货', dataIndex: 'received_qty', width: 110, align: 'right', render: num },
    { title: '在途数量', dataIndex: 'in_transit_qty', width: 120, align: 'right',
      render: (v) => (Number(v) > 0
        ? <span style={{ fontFamily: MONO, fontWeight: 600 }}>{Number(v).toLocaleString()}</span>
        : num(v)) },
    { title: '原厂承诺货期', dataIndex: 'promised_eta', width: 130, render: dateCell },
    { title: '最新预计到货', dataIndex: 'latest_eta', width: 130, render: dateCell },
    { title: '跟踪状态', dataIndex: 'track_status', width: 150,
      render: (v) => (v ? <StatusPillInline value={v} /> : <span style={{ color: '#bfbbb5' }}>—</span>) },
  ], []);

  const PageHeader = () => (
    <div style={{ marginBottom: 16 }}>
      <h2 style={{ fontSize: 26, fontWeight: 300, letterSpacing: '-0.01em', color: '#000', margin: 0, lineHeight: 1.2 }}>
        采购在途
      </h2>
      <span style={{ color: '#777169', fontSize: 13 }}>
        采购 / 供应链 · 原厂 → 我方在途跟踪 + 货期/到货提醒（填「人离职就跟丢」洞，PRD 04a-6）
      </span>
    </div>
  );

  if (ready === false) {
    return (
      <div>
        <PageHeader />
        <Alert
          type="warning" showIcon style={{ marginBottom: 16, borderRadius: 12 }}
          title="功能已就绪 · 待后端开通"
          description="采购在途为只读聚合 + 提醒能力：引擎无在途模型、无提醒/定时器。后端段2c ➕ purchase_in_transit 聚合端点（/api/purchase/intransit，沿 PO_line received 聚合订单/已收/在途）+ 提醒扫描命令（扫「承诺 ETA 过期且未发货」→ 经 notifications.dispatch 写站内提醒）。端点就绪后本页自动点亮，不写死行/状态码。"
        />
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="采购在途聚合端点待后端开通" />
      </div>
    );
  }

  return (
    <div>
      <PageHeader />

      <Alert
        type="info" showIcon style={{ marginBottom: 16, borderRadius: 12 }}
        title="采购在途 = PO 已下单未到货的跟踪台账（订单 - 已收 = 在途）；超期未给货期/未发货 → 提醒标记红"
        description="PA「只拉我的数据」（默认按本人过滤，可切全部）；分批入库回填 received 后在途数量递减（消在途）。引擎无定时器 → 提醒为手动「刷新提醒」轻量扫描：扫「承诺 ETA 过期且未发货」→ 写站内提醒（见通知中心）。本台账纯数量/ETA 跟踪，无买价列。"
      />

      <BizTable
        headerTitle="采购在途台账"
        rowKey={(r) => r.purchase_order_line_id ?? `${r.purchase_order_id}-${r.material_id}`}
        columns={columns}
        dataSource={rows}
        loading={loading}
        rowSelection={false}
        search={false}
        pagination={{ pageSize: 20, showSizeChanger: true }}
        toolBarRender={() => [
          <Space key="bar" size={8}>
            {isPA && (
              <Segmented
                size="small"
                value={scope}
                onChange={setScope}
                options={[{ label: '我的', value: 'mine' }, { label: '全部', value: 'all' }]}
              />
            )}
            <Button icon={<ReloadOutlined />} onClick={load} loading={loading}>刷新</Button>
            <Button type="primary" icon={<BellOutlined />} onClick={scanAlerts} loading={scanning}>
              刷新提醒
            </Button>
          </Space>,
        ]}
        scroll={{ x: 'max-content', y: 'calc(100vh - 440px)' }}
      />
    </div>
  );
}
