/**
 * 通知中心 —— 占位（PRD 00b 页面2）
 *
 * ⚠️ 引擎无原生通知子系统（00b EXT-00b-C 本模块最大扩展）：
 *  待办(todo)≠通知(notification)；退运180天/样品超期/应收到期等时间触发事件待办兜不住，
 *  须新增 notification 模型 + effect 派发 + 定时扫描 + 邮件适配器（后端 P 段 ➕）。
 *  本页为前端壳占位，后端通知模型就绪后接 /api/query(notification)。
 */

import { Alert } from 'antd';
import { BizTable } from '../components/biz';

const columns = [
  { title: '通知号', dataIndex: 'notification_number', width: 160, fixed: 'left' },
  { title: '事件类型', dataIndex: 'event_type', width: 130, valueType: 'select' },
  { title: '关联单据', dataIndex: 'doc_ref', ellipsis: true },
  { title: '渠道', dataIndex: 'channel', width: 110 },
  { title: '已读', dataIndex: 'is_read', width: 80, valueType: 'select' },
  { title: '时间', dataIndex: 'sent_at', width: 170, valueType: 'dateTime' },
];

export default function Notifications() {
  return (
    <div>
      <h2 style={{ fontSize: 26, fontWeight: 300, color: '#000', margin: '0 0 4px' }}>通知中心</h2>
      <span style={{ color: '#777169', fontSize: 13 }}>工作台</span>
      <Alert
        type="warning"
        showIcon
        style={{ margin: '16px 0', borderRadius: 12 }}
        message="通知子系统为后端扩展点（EXT-00b-C，待 P 段建造）"
        description="引擎无原生通知/消息子系统；进库/发货/到货/到期/退运180/样品超期/备货消单 等事件须新增 notification 模型 + effect/定时扫描派发 + 站内+邮件。本页为前端壳占位。"
      />
      <BizTable placeholder headerTitle="我的通知" columns={columns} rowSelection={{}} search={false} />
    </div>
  );
}
