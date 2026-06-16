/**
 * wmsShared —— WMS 入库/库存页共用 React 组件（仅组件，纯函数在 wmsHelpers.js）
 *
 *  - StatusPill       状态药丸（淡底深字；引擎真实 state code，扩态自动落默认色）
 *  - LabelPrintModal  62×29mm 入仓编号标签批量预览 + "功能已就绪·待打印机对接"占位（14 律留口子）
 */
import { Modal, Empty } from 'antd';
import { PrinterOutlined } from '@ant-design/icons';
import { StatusPillInline } from './StatusPill';

const MONO = 'ui-monospace, SFMono-Regular, Menlo, monospace';

export function StatusPill({ value }) {
  return <StatusPillInline value={value} />;
}

// 纯 SVG 模拟一维条码（视觉占位；真实条码渲染由后端 build_label_payload 命令出，14 律留口子）
function FakeBarcode({ text }) {
  const bars = [];
  let x = 0;
  for (let i = 0; i < (text || '').length * 3 + 12; i++) {
    const w = ((text.charCodeAt(i % text.length) || 50) % 3) + 1;
    if (i % 2 === 0) bars.push(<rect key={i} x={x} y={0} width={w} height={28} fill="#000" />);
    x += w + 1;
  }
  return (
    <svg width="100%" height="28" viewBox={`0 0 ${x} 28`} preserveAspectRatio="none"
      style={{ display: 'block' }}>{bars}</svg>
  );
}

/** 62×29mm 标签预览卡（按 96dpi 约 234×110px 等比展示） */
function LabelPreview({ code }) {
  return (
    <div style={{
      width: 234, height: 110, border: '1px solid rgba(0,0,0,0.18)', borderRadius: 4,
      padding: '8px 10px', display: 'flex', flexDirection: 'column', justifyContent: 'space-between',
      background: '#fff', boxShadow: 'rgba(0,0,0,0.04) 0 1px 2px',
    }}>
      <div style={{ fontSize: 11, color: '#777169' }}>62 × 29 mm</div>
      <div style={{ fontFamily: MONO, fontSize: 17, fontWeight: 600, letterSpacing: '0.02em', color: '#000' }}>
        {code}
      </div>
      <div style={{ height: 30 }}><FakeBarcode text={String(code || ' ')} /></div>
    </div>
  );
}

/**
 * LabelPrintModal —— 选中 N 个入仓编号 → 批量 62×29mm 标签预览 + 占位打印。
 */
export function LabelPrintModal({ open, onClose, codes = [] }) {
  return (
    <Modal
      open={open}
      onCancel={onClose}
      title={(
        <span><PrinterOutlined style={{ marginRight: 8, color: '#777169' }} />
          打印入仓编号标签 · 62×29mm
        </span>
      )}
      width={640}
      footer={null}
    >
      {codes.length === 0 ? (
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="未选中任何入仓编号" />
      ) : (
        <>
          <div style={{
            background: 'rgba(245, 242, 239, 0.6)', border: '1px solid rgba(0,0,0,0.05)',
            borderRadius: 10, padding: '10px 14px', marginBottom: 16, fontSize: 13, color: '#4e4e4e',
          }}>
            已选 <strong>{codes.length}</strong> 个入仓编号 · 每个生成 1 张 62×29mm 条码标签（文本 + 一维条码）。
            <div style={{ marginTop: 6, color: '#b8860b' }}>
              功能已就绪 · 待打印机对接（ZPL/EPL 驱动现场确认，条码由后端标签命令渲染）。
            </div>
          </div>
          <div style={{
            display: 'flex', flexWrap: 'wrap', gap: 14, maxHeight: 360, overflow: 'auto', padding: 4,
          }}>
            {codes.slice(0, 60).map((c, i) => <LabelPreview key={`${c}-${i}`} code={c} />)}
          </div>
          {codes.length > 60 && (
            <div style={{ textAlign: 'center', color: '#777169', fontSize: 12, marginTop: 12 }}>
              … 仅预览前 60 张，实际将打印全部 {codes.length} 张
            </div>
          )}
        </>
      )}
    </Modal>
  );
}
