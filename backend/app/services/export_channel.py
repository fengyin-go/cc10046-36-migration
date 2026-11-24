"""导出通道领域服务。

字段筛选迁移后的规则：
- 旧版「字段筛选」逗号文本列原样保留，旧版下载的列和单元格值不变；
- 新增「有序字段」保序字段记录，新版登记任务时保存原字段次序；
- 旧任务没有保序记录时只标记「待核对」，不自动按逗号拆分；
- 字段迁移明细与确认流程见 app.services.field_migration。
"""
from __future__ import annotations

from typing import Any

from app.services.base import BaseModuleService
from app.services import field_migration as migration


class ExportChannelService(BaseModuleService):
    MODULE = "export_channel"
    ENTITY = "导出任务"
    OPERATION_TERM = "采集"
    LIST_FIELDS = ["任务标识", "来源批次", "导出格式", "目标路径", "字段筛选", "导出状态", "文件大小", "完成时间"]
    REQUIRED_FIELDS = ["任务标识", "来源批次", "导出格式"]
    STATUS_ORDER = ["排队中", "导出中", "已完成", "导出失败"]
    ACTION_RULES = {"启动导出": "排队中", "取消导出": "导出中"}
    NEGATIVE_ACTIONS = []

    def list_entries(self, **kwargs):  # type: ignore[override]
        migration.ensure_migration_ledger()
        return super().list_entries(**kwargs)

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        migration.ensure_migration_ledger()
        return super().get_entry(entry_id)

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        """登记导出任务：新版保存原字段次序，绝不拆分旧逗号文本。"""
        entry, missing = super().create_entry(values)
        if missing:
            return None, missing
        ordered = migration.normalize_ordered_fields(values.get("有序字段", []))
        assert entry is not None
        entry["有序字段"] = ordered
        if ordered:
            # 交付流水线/新版登记：保存原字段次序，逗号文本仅作旧列兼容
            entry["字段筛选"] = ",".join(ordered)
            entry["切换状态"] = migration.SWITCH_NATIVE
        else:
            # 没有随单提供有序字段：原样保留登记的文本，留待核对，不拆分
            entry["切换状态"] = migration.SWITCH_PENDING
        migration.ensure_migration_ledger()
        return entry, []

    def domain_export(self, batch_id: str, export_format: str = "csv",
                      fields: list[str] | None = None) -> dict:
        """交付流水线登记导出任务：保存原字段次序的保序字段记录。"""
        from app.store import store
        import time
        rows = store.rows(self.MODULE)
        now = time.strftime("%Y-%m-%d")
        ordered = migration.normalize_ordered_fields(fields or [])
        file_size = (len(batch_id) * 1024) + 512
        entry = {
            "id": max((int(r.get("id", 0)) for r in rows), default=0) + 1,
            "任务标识": f"EXPORT-{batch_id}",
            "来源批次": batch_id,
            "导出格式": export_format,
            "目标路径": f"/exports/{batch_id}.{export_format}",
            "字段筛选": ",".join(ordered),
            "有序字段": ordered,
            "切换状态": migration.SWITCH_NATIVE if ordered else migration.SWITCH_PENDING,
            "导出状态": "已完成",
            "文件大小": f"{file_size}",
            "完成时间": now,
            "status": "已完成",
            "pending": False,
            "abnormal": False,
        }
        rows.append(entry)
        migration.ensure_migration_ledger()
        return entry
