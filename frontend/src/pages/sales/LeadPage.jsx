/**
 * LeadPage —— 线索台账（PRD 05-CRM前段 页面3 ⭐，售前漏斗第一级）
 *
 * 承接「飞书群分派」现状：专人盯网络/电话咨询 → 销售经理 @ 分派给某销售 → 销售 + FAE 跟进 →
 *   转商机 / 关闭丢失。线索客户可空（询价先于建档，访谈 09:172-196）；内容容一句话笼统需求。
 *
 * 复用积木：PurchaseDocPage（台账 → 右抽屉不跳页 → 顶部动作按钮，全 schema 驱动；动作一律
 *   /api/transitions 按当前状态 + 角色过滤真实边 → /api/transition 唯一写入路径，不写死状态码）。
 *   线索头无明细行（noLines）：头 schema 驱动 MasterFormFields（来源/内容/客户[可空]/未建档客户名/
 *   产线/分派销售/FAE/区域）。
 *
 * 头字段（schema 驱动，后端段3b 注册 lead 表后自动出列）：
 *   source(来源 百度/电话/网询/展会/转介) · content(内容,容一句话) · customer_id(客户,可空) ·
 *   customer_name_raw(未建档原始客户名) · product_line_id(产线) · assigned_sales_id(分派销售) ·
 *   assigned_fae_id(配合 FAE) · region(区域) · next_step(下一步)。
 *
 * 派生：「转商机」是跨单据派生 effect（线索→建 opportunity 草稿回填客户/产线/干系人，EXPLICIT）——
 *   由后端注册，前端只读 /api/transitions 真实边渲染动作按钮，不写死推进逻辑。
 *
 * ★引擎实况：LEAD doc_type / lead 表 / 轻量流程 / 转商机 effect 由后端段3b 注册（引擎现无 LEAD，
 *   照段0c/段1 套路 ➕ 新建）。未注册时 PurchaseDocPage 显示「功能已就绪 · 待后端开通」占位
 *   （14 律 §8），注册后自动点亮。
 */
import PurchaseDocPage from '../purchase/PurchaseDocPage';

// 状态药丸候选（仅台账筛选提示；真实可走边以 /api/transitions 为准，不写死状态码推进）
const STATUS_ENUM = [
  { text: '新建 NEW', value: 'NEW' },
  { text: '已分派 ASSIGNED', value: 'ASSIGNED' },
  { text: '跟进中 FOLLOWING', value: 'FOLLOWING' },
  { text: '已转商机 CONVERTED', value: 'CONVERTED' },
  { text: '已关闭 CLOSED', value: 'CLOSED' },
];

export default function LeadPage() {
  return (
    <PurchaseDocPage
      docType="LEAD"
      table="lead"
      noLines
      title="线索"
      subtitle="售前漏斗第一级 · 网询/电询登记 → 销售经理分派 → 销售+FAE 跟进 → 转商机 / 关闭"
      numberField="lead_number"
      statusEnum={STATUS_ENUM}
      editableStates={['NEW', 'ASSIGNED', 'FOLLOWING']}
      newLabel="新建线索"
      primaryToStates={['ASSIGNED', 'FOLLOWING', 'CONVERTED']}
      intro={{
        title: '一条线索 = 一次客户咨询（百度推广 / 电话 / 网询 / 展会 / 转介）——替代飞书群翻聊天记录。客户可空（询价常跑在建档前面），内容容一句话笼统需求（科研尤甚）',
        description: '流程：登记 → 销售经理分派给某销售（分派时 assigned_sales_id 必填）→ 销售 + FAE 跟进 → 转商机（派生建 opportunity 草稿并回填客户/产线/干系人）/ 关闭丢失。前段无财务关卡、不推金蝶。动作按钮一律由引擎流程边生成（/api/transitions 按当前状态 + 角色过滤）→ /api/transition 唯一写入路径，不写死状态码。',
      }}
      todoNote="线索为 ➕ 新增 LEAD doc_type（引擎现无 LEAD/OPPORTUNITY，照段0c/段1 套路新建）。需后端段3b 建 lead 表（含 source/content/customer_id[可空]/customer_name_raw/product_line_id/assigned_sales_id/assigned_fae_id/region/next_step）+ WorkflowDefinition（NEW→ASSIGNED→FOLLOWING→CONVERTED/CLOSED，节点级 allowed_roles 规避 D-02e 边级角色坑；ASSIGNED 关卡 assigned_sales_id 必填）+ 建单取号 effect（lead_number=LD-{YYMM}-{NNN} 月度连号）+ 转商机派生 effect（@register_transition_effect EXPLICIT：建 opportunity 草稿回填 customer_id/product_line_id/owner_sales_id/fae_id，命令发现需改 load_commands() import）。注册后本页自动点亮。"
    />
  );
}
