/**
 * BizEditableTable —— 明细网格标准壳（包 AntD Pro EditableProTable）
 *
 * 落 UX 律 14 §3 录单效率（对"爱表格"群体最关键）：
 *  - 可编辑网格 inline edit：Tab/Enter 在格间走（EditableProTable 原生）
 *  - 数字列右对齐 + 等宽字体（valueType=digit 列自动右对齐，本壳再加 align/font 兜底）
 *  - 多行录入一律用网格（对应引擎 SubTableEditor 的 PO/SO/入库批次/盘点明细 等子表）
 *  - 乐观 UI：保存即写入 value，失败由调用方就地标红（红线⑦ 禁 magic pushbutton）
 *
 * 数字列约定：调用方在 column 上写 valueType:'digit' 或 _numeric:true，本壳统一右对齐+等宽。
 *
 * 用法：
 *   <BizEditableTable
 *     value={lines} onChange={setLines}
 *     columns={[{title:'型号',dataIndex:'model'},{title:'数量',dataIndex:'qty',valueType:'digit'}]}
 *   />
 */

import { EditableProTable } from '@ant-design/pro-components';

const MONO = 'ui-monospace, SFMono-Regular, Menlo, monospace';

// 给数字列统一右对齐 + 等宽字体（UX §3）
function normalizeColumns(columns = []) {
  return columns.map((col) => {
    const isNumeric = col.valueType === 'digit' || col.valueType === 'money' || col._numeric;
    if (!isNumeric) return col;
    return {
      align: 'right',
      ...col,
      fieldProps: { style: { fontFamily: MONO, textAlign: 'right' }, ...col.fieldProps },
    };
  });
}

export default function BizEditableTable({
  value,
  onChange,
  columns,
  rowKey = 'id',
  recordCreatorProps,        // 传 false 关闭"添加一行"
  editableKeys,
  onEditableChange,
  scroll,
  ...rest
}) {
  // 非受控 editableKeys 时默认全部行可编辑（Excel 式整表可改）
  const allKeys = Array.isArray(value) ? value.map((r) => r[rowKey]) : [];

  return (
    <EditableProTable
      rowKey={rowKey}
      value={value}
      onChange={onChange}
      columns={normalizeColumns(columns)}
      controlled
      // 默认底部「+ 添加一行」（键盘流建下一行）；调用方可 false
      recordCreatorProps={
        recordCreatorProps === false
          ? false
          : {
              position: 'bottom',
              creatorButtonText: '添加一行',
              record: () => ({ id: `new_${Date.now()}` }),
              ...recordCreatorProps,
            }
      }
      editable={{
        type: 'multiple',
        editableKeys: editableKeys ?? allKeys,
        onChange: onEditableChange,
        // 编辑态保存即落 value（乐观 UI），保留默认保存/删除/取消
      }}
      scroll={{ x: 'max-content', ...scroll }}
      {...rest}
    />
  );
}
