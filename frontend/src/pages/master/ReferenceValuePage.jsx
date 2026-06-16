/**
 * ReferenceValuePage —— "字典型"主数据派生视图（无独立引擎表时的诚实占位）
 *
 * 背景（守"引擎不认业务术语"/不造端点）：PRD 02 规划的 4 个主数据
 *   产品代码 product_code / 产线 product_line / HS 编码 hs_code / 计量单位 unit_of_measure
 * 在当前引擎里**还没有独立表**——它们目前是事务/物料表上的**列**：
 *   - 产线 = material.product_line（String 列）
 *   - 计量单位 = material.unit（String 列）
 *   - 产品代码 = material.sku（型号即代码，尚无"一型号多 code"独立表）
 *   - HS 编码 = inventory/单据行上的 hs_code 列（无字典表）
 *
 * 段0b 不能在前端造表/造端点，故本页用 /api/aggregate(group_by=该列) 把**实际在用的取值**
 * 聚成一张"字典快照"台账（值 + 引用条数），让用户看见现状；同时显著标 TODO：
 * 真正的可维护字典表是后端扩展（EXT-02-DICT），届时本页替换为 MasterDataPage。
 */

import { useCallback, useMemo } from 'react';
import { Alert, App, Tag } from 'antd';
import { BizTable } from '../../components/biz';
import { aggregate } from '../../api';

/**
 * @param {string} title       中文标题
 * @param {string} sourceTable 派生来源真实表（如 material）
 * @param {string} sourceField 派生来源列（如 product_line / unit / sku / hs_code）
 * @param {string} todoNote    TODO 横幅说明
 */
export default function ReferenceValuePage({ title, sourceTable, sourceField, todoNote }) {
  const { message } = App.useApp();

  const request = useCallback(async () => {
    try {
      const { data } = await aggregate(sourceTable, sourceField, 'COUNT', { group_by: sourceField });
      const rows = (data?.data || [])
        .filter((r) => r.group && r.group !== 'None')
        .map((r, i) => ({ id: i, value: r.group, usage: r.value }))
        .sort((a, b) => b.usage - a.usage);
      return { data: rows, success: true, total: rows.length };
    } catch (e) {
      message.error(e.response?.data?.detail || `加载 ${title} 失败`);
      return { data: [], success: false, total: 0 };
    }
  }, [sourceTable, sourceField, title, message]);

  const columns = useMemo(() => [
    {
      title: '取值', dataIndex: 'value', fixed: 'left', width: 240,
      render: (v) => <span style={{ fontWeight: 500 }}>{v}</span>,
    },
    {
      title: '引用条数', dataIndex: 'usage', width: 140, align: 'right', search: false,
      sorter: (a, b) => a.usage - b.usage,
      render: (v) => <span style={{ fontFamily: 'ui-monospace, monospace' }}>{Number(v).toLocaleString()}</span>,
    },
    {
      title: '来源', dataIndex: '_src', width: 220, search: false, hideInSetting: true,
      render: () => <Tag style={{ background: '#f5f2ef', color: '#777169', border: 'none' }}>{sourceTable}.{sourceField}</Tag>,
    },
  ], [sourceTable, sourceField]);

  return (
    <div>
      <div style={{ marginBottom: 16 }}>
        <h2 style={{ fontSize: 26, fontWeight: 300, letterSpacing: '-0.01em', color: '#000', margin: 0, lineHeight: 1.2 }}>
          {title}
        </h2>
        <span style={{ color: '#777169', fontSize: 13 }}>
          主数据 · 派生自 <code>{sourceTable}.{sourceField}</code>（字典表待后端建）
        </span>
      </div>

      <Alert
        type="warning" showIcon style={{ marginBottom: 16, borderRadius: 12 }}
        message="字典表尚未在引擎建立 —— 当前为派生快照"
        description={todoNote}
      />

      <BizTable
        headerTitle={`${title}（在用取值快照）`}
        rowKey="id"
        columns={columns}
        request={request}
        rowSelection={false}
        search={false}
        pagination={{ pageSize: 50 }}
        scroll={{ x: 'max-content', y: 'calc(100vh - 360px)' }}
      />
    </div>
  );
}
