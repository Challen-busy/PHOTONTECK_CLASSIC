/**
 * ModulePlaceholder —— 业务模块占位页（壳已就绪，待 P 段建造）
 *
 * 落 UX 律 14 §8「未做功能 = 可见占位」+ 标准布局「单据类」骨架：
 *  顶部标题 + "功能已就绪 · 待开通" 提示 → BizTable 空壳（查询条/列配置/密度/批量已就位）。
 *  P 段建造时把本页替换为接 /api/query 的真实台账（request + columns + 行点击抽屉）。
 *
 * 用法：<Route path="..." element={<ModulePlaceholder title="采购订单 PO 总表" domain="采购 / 供应链" />} />
 */

import { Alert } from 'antd';
import { BizTable } from '../components/biz';

// 占位列：单号 / 摘要 / 状态 / 更新时间（真实页按单据替换）
const placeholderColumns = [
  { title: '单号', dataIndex: 'number', width: 180, fixed: 'left' },
  { title: '摘要', dataIndex: 'summary', ellipsis: true },
  { title: '状态', dataIndex: 'state', width: 120, valueType: 'select' },
  { title: '更新时间', dataIndex: 'updated_at', width: 170, valueType: 'dateTime' },
];

export default function ModulePlaceholder({ title, domain, columns }) {
  return (
    <div>
      <div style={{ marginBottom: 16 }}>
        <h2 style={{
          fontSize: 26, fontWeight: 300, letterSpacing: '-0.01em',
          color: '#000', margin: 0, lineHeight: 1.2,
        }}>
          {title}
        </h2>
        {domain && (
          <span style={{ color: '#777169', fontSize: 13 }}>{domain}</span>
        )}
      </div>

      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16, borderRadius: 12 }}
        title="功能已就绪 · 待开通"
        description="本页为前端壳占位（BizTable 台账壳：查询条 / 列配置 / 密度 / 批量已就位）。业务台账与录单抽屉将在 P 段按 PRD 对应模块建造。"
      />

      <BizTable
        placeholder
        headerTitle={title}
        columns={columns || placeholderColumns}
        rowSelection={{}}
        tableAlertOptionRender={() => null}
      />
    </div>
  );
}
