"""Registry for domain-specific workflow transition extensions.

The workflow engine owns transition mechanics. Domain modules register
validators and effects here so the engine does not need to know WMS/ERP/CRM
business terms.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from importlib import import_module

from sqlalchemy.ext.asyncio import AsyncSession

import models as m


TransitionValidator = Callable[
    [AsyncSession, str, object, str | None, m.UserAccount],
    Awaitable[list[str]],
]
TransitionEffect = Callable[
    [AsyncSession, str, object, str | None, m.UserAccount, int | None],
    Awaitable[list[str]],
]


@dataclass(frozen=True)
class _TransitionExtension:
    name: str
    doc_type: str | None
    to_state: str | None
    auto: bool

    def matches(self, doc_type: str, to_state: str | None) -> bool:
        if self.doc_type and self.doc_type != doc_type:
            return False
        if self.to_state and self.to_state != to_state:
            return False
        return True


@dataclass(frozen=True)
class _ValidatorRegistration(_TransitionExtension):
    handler: TransitionValidator


@dataclass(frozen=True)
class _EffectRegistration(_TransitionExtension):
    handler: TransitionEffect


_VALIDATORS: list[_ValidatorRegistration] = []
_EFFECTS: list[_EffectRegistration] = []
_EXTENSION_MODULES = (
    "services.phase1_effects",
    "services.wms_workflow_extensions",
    # 段0b：会签集齐校验器 / 金蝶 outbox 适配器 / 通知派发 effect
    "services.cosign",
    "services.kingdee_outbox",
    "services.notifications",
    # 段0b·1：建单取号 effect（把引擎默认 UUID 号换成业务连号）
    "services.numbering_effect",
    # 段4a：报关域 validator/effect（合规五件套硬拦 / 香港退香港 / 单号回写 / 报关费分摊回写到岸成本）
    "services.customs",
    # 总账·第一波（finance-gl）：过账/反过账 effect + 借贷平衡/期间锁/职责分离 validator + 红冲命令
    "services.finance_posting",
    # 总账·第二波（finance-gl wave-2）：业财映射 effect（业务单→凭证，销售开票自动生成并过账）
    "services.finance_mapping",
    # 总账·第四波（finance-gl wave-4）：凭证批量工作台命令（批量推进/按模板建单/断号检测/重排号）
    "services.finance_batch",
    # 总账·第六波（finance-gl wave-6）：现金流量归集命令 finance.assign_cashflow
    "services.finance_cashflow",
    # 总账·第六波（finance-gl wave-6）：定期凭证生成命令 finance.generate_recurring_voucher
    "services.finance_recurring",
    # 总账·第八波（finance-gl wave-8）：应收款管理业财映射 effect（应收单/收款单→凭证）
    #   （占位：Phase1 模块为空 import-safe，effect 在 Phase2 在 services.ar_receivable 内 @register_transition_effect）
    "services.ar_receivable",
    # 总账·第八波（finance-gl wave-8）：★通用核销引擎（finance.writeoff / finance.unwriteoff，biz_type=AR/AP）。
    #   本模块只注册 @register_command（无 auto effect），登记此处保持「命令双注册」一致性、import-safe。
    "services.finance_writeoff",
    # 应付款管理（finance-gl 应付波）：应付单/付款单→凭证业财映射 effect（= ar_receivable 供应商侧镜像）。
    "services.ap_payable",
    # 信用管理（finance-gl 信用波）：信用检查 validator + 信用占用 effect（hook 应收单审核）。
    "services.finance_credit",
)
_loaded = False


def register_transition_validator(
    name: str,
    *,
    doc_type: str | None = None,
    to_state: str | None = None,
    auto: bool = True,
):
    def decorator(func: TransitionValidator) -> TransitionValidator:
        _VALIDATORS.append(_ValidatorRegistration(name, doc_type, to_state, auto, func))
        return func

    return decorator


def register_transition_effect(
    name: str,
    *,
    doc_type: str | None = None,
    to_state: str | None = None,
    auto: bool = True,
):
    def decorator(func: TransitionEffect) -> TransitionEffect:
        _EFFECTS.append(_EffectRegistration(name, doc_type, to_state, auto, func))
        return func

    return decorator


def load_workflow_extensions() -> None:
    global _loaded
    if _loaded:
        return
    for module_name in _EXTENSION_MODULES:
        import_module(module_name)

    _loaded = True


async def run_transition_validators(
    db: AsyncSession,
    doc_type: str,
    doc,
    *,
    to_state: str | None,
    user: m.UserAccount,
) -> list[str]:
    load_workflow_extensions()
    failures: list[str] = []
    for registration in _VALIDATORS:
        if registration.auto and registration.matches(doc_type, to_state):
            failures.extend(await registration.handler(db, doc_type, doc, to_state, user))
    return failures


async def run_transition_effects(
    db: AsyncSession,
    doc_type: str,
    doc,
    *,
    to_state: str | None,
    user: m.UserAccount,
    command_log_id: int | None = None,
    effect_names: list[str] | None = None,
) -> list[str]:
    load_workflow_extensions()
    logs: list[str] = []
    executed: set[str] = set()
    for effect_name in effect_names or []:
        registration = next((item for item in _EFFECTS if item.name == effect_name), None)
        if not registration:
            raise ValueError(f"未注册 workflow effect: {effect_name}")
        logs.extend(await registration.handler(db, doc_type, doc, to_state, user, command_log_id))
        executed.add(registration.name)
    for registration in _EFFECTS:
        if registration.name not in executed and registration.auto and registration.matches(doc_type, to_state):
            logs.extend(await registration.handler(db, doc_type, doc, to_state, user, command_log_id))
    return logs
