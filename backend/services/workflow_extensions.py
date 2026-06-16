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
