"""Small command registry for cross-module write actions."""

from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass

from services.command_context import CommandContext

CommandHandler = Callable[[CommandContext, dict], Awaitable[dict]]


@dataclass(frozen=True)
class CommandMetadata:
    name: str
    module: str = "GENERAL"
    title: str = ""
    description: str = ""
    affected_tables: tuple[str, ...] = ()
    supports_retry: bool = False
    supports_rollback: bool = False
    supports_preview: bool = False

    def as_dict(self) -> dict:
        data = asdict(self)
        data["affected_tables"] = list(self.affected_tables)
        return data


_COMMANDS: dict[str, CommandHandler] = {}
_METADATA: dict[str, CommandMetadata] = {}
_loaded = False


def register_command(
    name: str,
    *,
    module: str = "GENERAL",
    title: str = "",
    description: str = "",
    affected_tables: tuple[str, ...] = (),
    supports_retry: bool = False,
    supports_rollback: bool = False,
    supports_preview: bool = False,
):
    def decorator(func: CommandHandler) -> CommandHandler:
        _COMMANDS[name] = func
        _METADATA[name] = CommandMetadata(
            name=name,
            module=module,
            title=title or name,
            description=description,
            affected_tables=tuple(affected_tables),
            supports_retry=supports_retry,
            supports_rollback=supports_rollback,
            supports_preview=supports_preview,
        )
        return func

    return decorator


def load_commands() -> None:
    global _loaded
    if _loaded:
        return
    import services.finance_commands  # noqa: F401
    import services.wms_commands  # noqa: F401
    import services.workflow_commands  # noqa: F401
    # 段0b 后端基础设施命令
    import services.numbering  # noqa: F401
    import services.cosign  # noqa: F401
    import services.kingdee_outbox  # noqa: F401
    import services.notifications  # noqa: F401
    # 段0c 标签/单据模板渲染命令
    import services.template_render  # noqa: F401
    # 段4a 报关域命令（顺丰物流框架壳 OFF / 资料清单导出壳）
    import services.customs_commands  # noqa: F401
    # 总账·第一波（finance-gl）：红冲命令 finance.red_reversal
    import services.finance_posting  # noqa: F401
    # 总账·第四波（finance-gl wave-4）：凭证批量工作台命令
    #   finance.batch_voucher_transition / create_voucher_from_model / check_voucher_gaps / renumber_vouchers
    import services.finance_batch  # noqa: F401
    # 总账·第六波（finance-gl wave-6）：现金流量归集命令 finance.assign_cashflow
    import services.finance_cashflow  # noqa: F401
    # 总账·第六波（finance-gl wave-6）：定期凭证生成命令 finance.generate_recurring_voucher（自动转账/摊销/预提）
    import services.finance_recurring  # noqa: F401

    _loaded = True


def get_command_handler(name: str) -> CommandHandler | None:
    load_commands()
    return _COMMANDS.get(name)


def get_command_metadata(name: str) -> CommandMetadata:
    load_commands()
    return _METADATA.get(name) or CommandMetadata(name=name, title=name)


def list_command_metadata() -> list[dict]:
    load_commands()
    return [
        meta.as_dict()
        for meta in sorted(_METADATA.values(), key=lambda item: (item.module, item.name))
    ]
