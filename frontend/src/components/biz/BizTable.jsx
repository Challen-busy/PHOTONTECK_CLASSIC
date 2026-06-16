/**
 * BizTable —— 业务台账标准壳（包 AntD Pro ProTable）
 *
 * 落 UX 律 14 §1/§4/§5：
 *  - 顶部查询条（ProTable search）+ 分页 + 排序 + 列配置（columnsState）+ 密度切换（density）
 *  - rowSelection 多选 + 选中后顶部 alert 条挂批量动作（tableAlertRender / tableAlertOptionRender）
 *  - 冻结列（单号/客户左冻结、操作列右冻结，由调用方在 columns 上标 fixed）
 *  - 表头吸顶（sticky）、ISO 时间/金额千分位由调用方列 render 决定
 *  - 禁斑马纹（继承全局 theme，无 zebra）
 *
 * 默认走 request(params) 让调用方对接后端 /api/query；也可直接传 dataSource 做占位空壳。
 * 占位用法：<BizTable placeholder columns={cols} title="采购订单 PO 总表" />
 */

import { ProTable } from '@ant-design/pro-components';
import { Empty } from 'antd';

const EMPTY_HINT = '功能已就绪 · 待开通（待 P 段建造）';

export default function BizTable({
  columns,
  request,
  dataSource,
  rowKey = 'id',
  headerTitle,
  toolBarRender,
  rowSelection,            // 传 {} 即开启多选；传 false 关闭
  tableAlertRender,        // 批量选中提示
  tableAlertOptionRender,  // 批量动作按钮
  scroll,
  placeholder = false,     // 占位空壳模式：不发请求、显示"待开通"
  search,
  options,
  pagination,
  ...rest
}) {
  // 占位模式：不发请求、给"待 P 段建造"空状态
  const effectiveRequest = placeholder
    ? async () => ({ data: [], success: true, total: 0 })
    : request;

  return (
    <ProTable
      columns={columns}
      rowKey={rowKey}
      headerTitle={headerTitle}
      request={dataSource ? undefined : effectiveRequest}
      dataSource={dataSource}
      cardBordered
      // 查询条：默认折叠展开 + labelWidth 自适应（UX §1 顶部查询条）
      search={
        search === false
          ? false
          : { labelWidth: 'auto', defaultCollapsed: false, ...search }
      }
      // 列配置 / 密度 / 刷新 / 全屏（UX §5 密度可控 + 列配置）
      options={{ density: true, fullScreen: true, setting: true, reload: true, ...options }}
      // rowSelection 默认开多选（UX §4 批量标配），调用方可关
      rowSelection={rowSelection === false ? undefined : { ...rowSelection }}
      tableAlertRender={tableAlertRender}
      tableAlertOptionRender={tableAlertOptionRender}
      // 表头吸顶 + 横向滚动（冻结列需要）
      sticky
      scroll={{ x: 'max-content', ...scroll }}
      pagination={{ pageSize: 20, showSizeChanger: true, ...pagination }}
      dateFormatter="string"
      toolBarRender={toolBarRender}
      // 禁斑马纹：不设 rowClassName 交替色；hover 由全局 theme 接管
      locale={{
        emptyText: (
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description={placeholder ? EMPTY_HINT : '暂无数据'}
          />
        ),
      }}
      {...rest}
    />
  );
}
