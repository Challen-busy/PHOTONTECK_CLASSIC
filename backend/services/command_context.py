"""Command execution context shared by ERP/WMS actions."""

from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

import models as m


@dataclass
class CommandContext:
    db: AsyncSession
    user: m.UserAccount
    command_log: m.CommandLog
    events: list[dict] = field(default_factory=list)
    logs: list[str] = field(default_factory=list)

    def add_event(self, event_type: str, payload: dict | None = None) -> None:
        self.events.append({"type": event_type, "payload": payload or {}})

    def add_log(self, message: str) -> None:
        self.logs.append(message)
