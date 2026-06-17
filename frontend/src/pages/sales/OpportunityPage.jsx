/**
 * OpportunityPage —— 商机 / 项目台账（PRD 05-CRM前段 页面4 ⭐，核心阶段状态机）
 *
 * 售前漏斗第二级，产品负责人最想要的「项目跟进表」系统化载体（替代飞书群翻记录）：
 *   阶段 = 状态机（前期沟通 → 送样 → 小批量 → 批量 → 关闭赢/丢，含可回退「无进展」）。
 *   科研 vs 光通信分流：科研（SIO）必走 FAE 确认规格、需选细分市场 research_sub_market。
 *
 * 复用积木：PurchaseDocPage（台账 → 右抽屉不跳页 → 顶部动作按钮，全 schema 驱动；动作一律
 *   /api/transitions 按当前状态 + 角色过滤真实边 → /api/transition 唯一写入路径，不写死状态码）+
 *   子表网格 PurchaseLineGrid（跟进记录 opportunity_followup_line：日期/类型/联系人/内容/下一步，
 *   Excel 粘贴建行 + 录单增强 14 律 §3，schema 驱动列）。
 *
 * ★段2d-2 lineFk 教训：跟进记录子表父 FK 必须对准真列名 opportunity_id（QuotationLine 等子表父键
 *   命名各异，不可想当然）；派生 _ 展示列由 PurchaseDocPage.buildSubUpdates 提交前统一 strip。
 *
 * ★引擎实况：OPPORTUNITY doc_type / opportunity 表 / opportunity_followup_line 子表 / 7 态流程
 *   由后端段3b 注册（引擎现无 OPPORTUNITY，照段0c/段1 套路 ➕ 新建）。未注册时 PurchaseDocPage 显示
 *   「功能已就绪 · 待后端开通」占位（14 律 §8），注册后自动点亮。
 */
import PurchaseDocPage from '../purchase/PurchaseDocPage';

// 状态药丸候选（阶段=状态码；仅台账筛选提示，真实可走边以 /api/transitions 为准，不写死推进）
const STATUS_ENUM = [
  { text: '前期沟通 EARLY', value: 'EARLY' },
  { text: '送样 SAMPLING', value: 'SAMPLING' },
  { text: '小批量 SMALL_BATCH', value: 'SMALL_BATCH' },
  { text: '批量 MASS', value: 'MASS' },
  { text: '关闭赢 WON', value: 'WON' },
  { text: '关闭丢 LOST', value: 'LOST' },
  { text: '无进展 STALLED', value: 'STALLED' },
];

export default function OpportunityPage() {
  return (
    <PurchaseDocPage
      docType="OPPORTUNITY"
      table="opportunity"
      lineTable="opportunity_followup_line"
      lineFk="opportunity_id"
      title="商机 / 项目"
      subtitle="售前漏斗第二级 · 阶段状态机（前期沟通 → 送样 → 小批量 → 批量 → 关闭赢/丢，含无进展回退）"
      numberField="opportunity_number"
      statusEnum={STATUS_ENUM}
      editableStates={['EARLY', 'SAMPLING', 'SMALL_BATCH', 'MASS', 'STALLED']}
      lineTitle="跟进记录（日期 / 类型 / 联系人 / 内容 / 下一步 · 网格录入）"
      newLabel="新建商机"
      primaryToStates={['SAMPLING', 'SMALL_BATCH', 'MASS', 'WON', 'EARLY']}
      intro={{
        title: '一条商机 = 一个在跟项目，产品负责人按产线一看过去一季度多少咨询/谁在跟/怎么成交（替代飞书群翻记录）。阶段即状态机；科研（SIO）需选细分市场、必走 FAE 规格确认，光通信型号有限可快速推进',
        description: '推进/回退一律点顶部动作按钮（状态机后台跑、前端只显状态药丸）：前期沟通 → 送样（推进时 customer_id 必填、科研需 research_sub_market）→ 小批量 → 批量 → 关闭赢（提示可录 SO，SO 在 05b）/ 关闭丢；长期没动静走「无进展」、可回「前期沟通」重新激活。跟进记录在抽屉内按行网格追加（一行一条周更，下一步可回写商机 next_step）。前段无财务关卡、不推金蝶。动作按钮由引擎流程边生成（/api/transitions）→ /api/transition 唯一写入路径，不写死状态码。',
      }}
      todoNote="商机为 ➕ 新增 OPPORTUNITY doc_type（引擎现无 OPPORTUNITY，照段0c/段1 套路新建）。需后端段3b 建 opportunity 表（含 customer_id/product_line_id/project_name/product_model/business_unit/research_sub_market[科研必填]/grade/owner_sales_id/fae_id/expected_amount/expected_close_date/next_step/remark）+ opportunity_followup_line 子表（activity_date/activity_type/contact_id/content/next_step/owner_id，父 FK=opportunity_id）+ WorkflowDefinition（7 态含可回退 STALLED→EARLY：EARLY→SAMPLING→SMALL_BATCH→MASS→WON/LOST，节点级 allowed_roles 规避 D-02e 坑；SAMPLING 关卡 customer_id 必填、科研 research_sub_market 必填）+ 建单取号 effect（opportunity_number=OPP-{YYMM}-{NNN} 月度连号）+ 接收线索「转商机」回填（由 LEAD 派生 effect 写入）。注册后本页自动点亮。"
    />
  );
}
