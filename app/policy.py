from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class AdminPolicy:
    admin_user_ids: frozenset[str] = field(default_factory=frozenset)

    def is_admin(self, user_id: str) -> bool:
        return user_id in self.admin_user_ids

