"""
Operation log for tracking all edits made to an ENI configuration.

Records structured operations for audit, undo potential, and future
AI features (e.g. "apply the same changes to another ENI file").
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Operation:
    op: str
    timestamp: float = field(default_factory=time.time)
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "op": self.op,
            "timestamp": self.timestamp,
            "details": self.details,
        }


class OperationLog:
    """Append-only log of operations performed on a loaded ENI config."""

    def __init__(self) -> None:
        self._operations: list[Operation] = []

    def record(self, op: str, **details: Any) -> None:
        self._operations.append(Operation(op=op, details=details))

    def log_remove_slave(self, slave_id: str, slave_name: str, position: int) -> None:
        self.record("remove_slave", slave_id=slave_id, name=slave_name, position=position)

    def log_reorder(self, new_order: list[str]) -> None:
        self.record("reorder", new_order=new_order)

    def log_toggle_slave(self, slave_id: str, slave_name: str, enabled: bool) -> None:
        self.record("toggle_slave", slave_id=slave_id, name=slave_name, enabled=enabled)

    def log_edit_slave_info(
        self, slave_id: str, field_name: str, old_value: Any, new_value: Any, slave_name: str = ""
    ) -> None:
        self.record(
            "edit_slave_info",
            slave_id=slave_id,
            slave_name=slave_name,
            field=field_name,
            old=old_value,
            new=new_value,
        )

    def log_edit_pdo_entry(
        self,
        slave_id: str,
        pdo_type: str,
        pdo_index: str,
        entry_idx: int,
        field_name: str,
        old_value: Any,
        new_value: Any,
        slave_name: str = "",
        entry_name: str = "",
    ) -> None:
        self.record(
            "edit_pdo_entry",
            slave_id=slave_id,
            slave_name=slave_name,
            pdo_type=pdo_type,
            pdo_index=pdo_index,
            entry_idx=entry_idx,
            entry_name=entry_name,
            field=field_name,
            old=old_value,
            new=new_value,
        )

    def log_add_pdo_entry(self, slave_id: str, pdo_type: str, pdo_index: str, slave_name: str = "", entry_name: str = "") -> None:
        self.record("add_pdo_entry", slave_id=slave_id, slave_name=slave_name, pdo_type=pdo_type, pdo_index=pdo_index, entry_name=entry_name)

    def log_remove_pdo_entry(
        self, slave_id: str, pdo_type: str, pdo_index: str, entry_idx: int, slave_name: str = "", entry_name: str = ""
    ) -> None:
        self.record(
            "remove_pdo_entry",
            slave_id=slave_id,
            slave_name=slave_name,
            pdo_type=pdo_type,
            pdo_index=pdo_index,
            entry_idx=entry_idx,
            entry_name=entry_name,
        )

    def log_duplicate_slave(self, source_id: str, new_id: str, slave_name: str = "") -> None:
        self.record("duplicate_slave", source_id=source_id, new_id=new_id, slave_name=slave_name)

    def log_load(self, filename: str, slave_count: int) -> None:
        self.record("load_file", filename=filename, slave_count=slave_count)

    def log_export(self, filename: str) -> None:
        self.record("export_file", filename=filename)

    def get_operations(self) -> list[dict]:
        return [op.to_dict() for op in self._operations]

    def get_summary(self) -> dict:
        """Summarize operations by type for quick overview."""
        summary: dict[str, int] = {}
        for op in self._operations:
            summary[op.op] = summary.get(op.op, 0) + 1
        return {
            "total_operations": len(self._operations),
            "by_type": summary,
        }

    def clear(self) -> None:
        self._operations.clear()
