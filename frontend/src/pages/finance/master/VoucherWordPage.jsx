/**
 * VoucherWordPage —— 凭证字主数据维护（finance-gl wave-3 配账基础资料）
 *
 * 凭证字 = 记 / 收 / 付 / 转。restrict_multi_dc 收付字限借贷只一方（资金类凭证一借一贷专用字）。
 *
 * 纯复用主数据通用壳 MasterDataPage（schema 驱动台账 → 详情抽屉 → /api/transition 唯一写入），
 * 与 master/customers、master/suppliers 同壳同范式：
 *   - 台账列由 /api/schema(voucher_word) 自动生成；
 *   - 建档(doc_id=null) / 改档(有 id) 抽屉提交走引擎唯一写入路径 /api/transition，doc_type=VOUCHER_WORD；
 *   - VOUCHER_WORD 须有「活跃 WorkflowDefinition」（seed 单态 ACTIVE + 自环编辑）才可写，
 *     否则 MasterDataPage 自动降级只读 + TODO 横幅，绝不伪造写。
 */
import MasterDataPage from '../../master/MasterDataPage';

export default function VoucherWordPage() {
  return (
    <MasterDataPage
      table="voucher_word"
      title="凭证字"
      domain="财务 / 总账 · 基础资料"
      docType="VOUCHER_WORD"
      writable
      primaryCols={['code', 'name']}
      todoNote="凭证字（记 / 收 / 付 / 转）建档 / 改档走 /api/transition（VOUCHER_WORD 状态机，单态 ACTIVE + 自环编辑）；restrict_multi_dc=收付字限借贷只一方。若引擎报「没有活跃的流程定义」，需后端为 VOUCHER_WORD 种最小 WorkflowDefinition（参照 CUSTOMER/SUPPLIER）。"
    />
  );
}
