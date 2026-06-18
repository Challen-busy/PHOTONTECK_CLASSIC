"""总账·第三波 smoke：配账主数据经引擎唯一写入 /execute_transition 可建档（验 __doc_types__+WorkflowDefinition 使能）。
跑法: cd backend && DATABASE_URL=postgresql+asyncpg://photonteck:photonteck@localhost:5433/photonteck python -m scripts.smoke_wave3
"""
import asyncio
from datetime import datetime

from sqlalchemy import select, func, delete as sa_delete

from core.database import get_session_factory
import models as m
from services.workflow import execute_transition


async def _u(db, name):
    return (await db.execute(select(m.UserAccount).where(m.UserAccount.username == name))).scalar_one_or_none()


async def main():
    factory = get_session_factory()
    ok, fail = [], []
    ts = datetime.now().strftime("%H%M%S")

    # 1) 验 12 个 GL 主数据 doc_type 都有「活跃 WorkflowDefinition」（否则 MasterDataPage 降级只读）
    GL_DOCTYPES = ["ACCOUNT", "VOUCHER_WORD", "AUX_DIMENSION", "CASHFLOW_ITEM", "EXCHANGE_RATE",
                   "CURRENCY", "SETTLEMENT_METHOD", "ACCOUNTING_POLICY", "ACCOUNTING_SYSTEM",
                   "SUMMARY_ENTRY", "MODEL_VOUCHER", "AUX_DIMENSION_VALUE"]
    async with factory() as db:
        for dt in GL_DOCTYPES:
            wf = (await db.execute(select(m.WorkflowDefinition).where(
                m.WorkflowDefinition.doc_type == dt, m.WorkflowDefinition.is_active == True))).scalars().first()
            (ok if wf else fail).append(f"WFD活跃:{dt}")

    # 2) 建档冒烟：CURRENCY / VOUCHER_WORD / SETTLEMENT_METHOD 各建一条（走唯一写入路径；每例独立 session + 合规短码 + rollback 不留脏）
    cases = [
        ("CURRENCY", {"company_id": 1, "code": "ZZ", "name": "测试币种", "symbol": "Z",
                      "is_base": False, "decimal_places": 2, "is_active": True}, m.Currency, "ZZ"),
        ("VOUCHER_WORD", {"company_id": 1, "code": "ZZ", "name": "测试凭证字",
                          "restrict_multi_dc": False, "is_active": True}, m.VoucherWord, "ZZ"),
        ("SETTLEMENT_METHOD", {"company_id": 1, "code": "ZZ", "name": "测试结算",
                               "method_type": "TRANSFER", "needs_settlement_no": True, "is_active": True}, m.SettlementMethod, "ZZ"),
    ]
    for dt, fields, model, code in cases:
        async with factory() as db:
            user = await _u(db, "finance")  # home company 1
            # execute_transition 会 commit，固定测试码 ZZ 跨 run 残留 → 先删保幂等
            await db.execute(sa_delete(model).where(model.company_id == 1, model.code == code))
            await db.commit()
            try:
                r = await execute_transition(db, dt, None, user, to_state="ACTIVE", field_updates=fields)
                row = (await db.execute(select(model).where(model.company_id == 1, model.code == code))).scalars().first()
                good = bool(r.get("success", True)) and row is not None
                print(f"  建档 {dt}: success={r.get('success')} 落库={bool(row)} err={str(r.get('error',''))[:60]}")
                (ok if good else fail).append(f"建档:{dt}")
            except Exception as e:
                print(f"  建档 {dt} 异常: {str(e)[:100]}")
                fail.append(f"建档:{dt}({str(e)[:40]})")
            await db.rollback()  # 冒烟不留脏数据

    # 3) 7 新表行数（seed 落库确认）
    async with factory() as db:
        for t, model in [("currency", m.Currency), ("settlement_method", m.SettlementMethod),
                         ("accounting_policy", m.AccountingPolicy), ("accounting_system", m.AccountingSystem),
                         ("summary_entry", m.SummaryEntry), ("model_voucher", m.ModelVoucher),
                         ("auxiliary_dimension_value", m.AuxiliaryDimensionValue)]:
            n = (await db.execute(select(func.count()).select_from(model))).scalar()
            print(f"  {t}: {n} 行")
            (ok if n and n > 0 else fail).append(f"seed有数据:{t}")

    print("\n==== WAVE-3 SMOKE 结果 ====")
    print("✅ 通过:", len(ok), ok if len(ok) <= 25 else f"{ok[:25]}...")
    print("❌ 失败:", fail if fail else "无")


if __name__ == "__main__":
    asyncio.run(main())
