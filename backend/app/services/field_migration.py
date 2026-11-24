"""字段迁移领域服务。

把导出通道「字段筛选」从旧版逗号文本迁移成保序字段记录（有序字段），
并维护字段迁移明细。关键约束：

- 旧任务上线时只登记迁移明细并置为「待核对」，不自动按逗号拆分旧字段；
- 旧文本无法独立认定字段次序时，必须等待值班员按任务行补交清单确认；
- 确认按原任务行处理，重复确认只生效一回（幂等），且只产生一条审计；
- 新版只交付有证据的字段值：未确认的旧任务在新版台账中标记待核。
"""
from __future__ import annotations

from typing import Any

from app.store import store

MODULE = "export_channel"
MIGRATION_TABLE = "field_migration"
OPERATION_CONFIRM = "字段确认"

# 切换状态
SWITCH_NATIVE = "原生存序"      # 新版部署后登记的任务，保存了原字段次序
SWITCH_PENDING = "待核对"       # 旧任务，仅凭逗号文本无法认定次序
SWITCH_CONFIRMED = "已确认"     # 旧任务已按任务行补交清单并确认

SWITCH_ORDER = [SWITCH_NATIVE, SWITCH_PENDING, SWITCH_CONFIRMED]


def normalize_ordered_fields(ordered_fields: list[Any]) -> list[str]:
    """规整保序字段记录：去空白、保次序、保留重复项，不做任何逗号拆分。"""
    result: list[str] = []
    for item in ordered_fields or []:
        name = str(item).strip()
        if name:
            result.append(name)
    return result


def find_migration(task_id: int) -> dict[str, Any] | None:
    """按原任务行读取字段迁移明细。"""
    for detail in store.rows(MIGRATION_TABLE):
        if int(detail.get("task_id", -1)) == int(task_id):
            return detail
    return None


def ensure_migration_ledger() -> None:
    """为存量导出任务补齐字段迁移明细，幂等。

    - 已带「有序字段」保序记录的任务：按原生存序登记，不拆分任何文本；
    - 只有旧版逗号文本的任务：登记待核，保留原字段文本，不自动拆分。
    """
    details = store.rows(MIGRATION_TABLE)
    known = {int(d["task_id"]) for d in details}
    for task in store.rows(MODULE):
        task_id = int(task.get("id", 0))
        if task_id in known:
            continue
        ordered = list(task.get("有序字段") or [])
        legacy_text = str(task.get("字段筛选", "") or "")
        if ordered:
            detail = {
                "task_id": task_id,
                "task_key": task.get("任务标识", ""),
                "switch_status": SWITCH_NATIVE,
                "legacy_text": legacy_text,
                "ordered_fields": list(ordered),
                "evidence": "新版登记时保存的原字段次序",
                "confirmed_by": "",
                "confirmed_at": "",
            }
            task["切换状态"] = SWITCH_NATIVE
        else:
            detail = {
                "task_id": task_id,
                "task_key": task.get("任务标识", ""),
                "switch_status": SWITCH_PENDING,
                "legacy_text": legacy_text,
                "ordered_fields": [],
                "evidence": "",
                "confirmed_by": "",
                "confirmed_at": "",
            }
            task["有序字段"] = []
            task["切换状态"] = SWITCH_PENDING
        details.append(detail)


def _audit_exists(task_id: int) -> bool:
    """同一任务行的字段确认审计是否已存在（重复确认只生效一回）。"""
    for audit in store.rows("crawl_audit"):
        if str(audit.get("关联任务ID", "")) == str(task_id) and audit.get("操作类型") == OPERATION_CONFIRM:
            return True
    return False


def _write_audit(task: dict[str, Any], detail: dict[str, Any],
                 evidence: str, operator: str) -> dict[str, Any]:
    """写采集审计：每行记录原字段文本、补交依据和确认后的有序字段。"""
    import time
    audit_rows = store.rows("crawl_audit")
    task_id = int(task.get("id", 0))
    ordered = list(detail["ordered_fields"])
    entry = {
        "id": max((int(r.get("id", 0)) for r in audit_rows), default=0) + 1,
        "记录标识": f"AUDIT-FIELD-{task_id}",
        "操作类型": OPERATION_CONFIRM,
        "操作对象": f"导出任务 {task.get('任务标识', task_id)}",
        "操作时间": time.strftime("%Y-%m-%d %H:%M:%S"),
        "操作人": operator,
        "变更前值": detail["legacy_text"],
        "变更后值": ",".join(ordered),
        "审计摘要": (
            f"按任务行确认字段次序；补交依据：{evidence}；"
            f"确认后的有序字段：{'、'.join(ordered)}"
        ),
        "status": "已记录",
        "pending": True,
        "abnormal": False,
        # 结构化回查字段，供按原任务行独立回查
        "关联任务ID": task_id,
        "原字段文本": detail["legacy_text"],
        "补交依据": evidence,
        "确认有序字段": ordered,
    }
    audit_rows.append(entry)
    return entry


def confirm_fields(task_id: int, ordered_fields: list[Any],
                   evidence: str, operator: str = "值班员",
                   ) -> tuple[dict[str, Any] | None, str, bool]:
    """按任务行确认旧任务的有序字段。

    返回 (迁移明细, 消息, 是否本次生效)。重复确认幂等：不更新、不写审计。
    新版只接受显式补交的清单，绝不从旧逗号文本自动拆分。
    """
    ensure_migration_ledger()
    task = store.find(MODULE, task_id)
    if task is None:
        return None, f"导出任务 {task_id} 不存在或已归档", False
    detail = find_migration(task_id)
    if detail is None:
        return None, f"导出任务 {task_id} 没有字段迁移明细", False
    if detail["switch_status"] != SWITCH_PENDING:
        # 已确认或原生记录：重复确认只生效一回
        return detail, f"导出任务 {task_id} 切换状态为{detail['switch_status']}，无需重复确认", False

    fields = normalize_ordered_fields(ordered_fields)
    basis = str(evidence or "").strip()
    if not fields:
        return None, "确认失败：必须补交非空的有序字段清单，不能从旧逗号文本自动拆分", False
    if not basis:
        return None, "确认失败：必须填写补交依据", False

    detail["ordered_fields"] = fields
    detail["evidence"] = basis
    detail["confirmed_by"] = operator
    import time
    detail["confirmed_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    detail["switch_status"] = SWITCH_CONFIRMED

    task["有序字段"] = list(fields)
    task["切换状态"] = SWITCH_CONFIRMED

    audit: dict[str, Any] | None = None
    if not _audit_exists(task_id):
        audit = _write_audit(task, detail, basis, operator)
    message = f"导出任务 {task_id} 字段次序已确认，审计记录 {audit['记录标识'] if audit else '已存在'}"
    return detail, message, True


def list_migration_details(switch_status: str | None = None) -> list[dict[str, Any]]:
    """字段迁移明细：关联任务标识与来源批次，供台账下载与人工核对。"""
    ensure_migration_ledger()
    tasks = {int(row.get("id", 0)): row for row in store.rows(MODULE)}
    result: list[dict[str, Any]] = []
    for detail in store.rows(MIGRATION_TABLE):
        if switch_status and detail["switch_status"] != switch_status:
            continue
        task = tasks.get(int(detail["task_id"]), {})
        result.append({
            "task_id": detail["task_id"],
            "任务标识": task.get("任务标识", detail.get("task_key", "")),
            "来源批次": task.get("来源批次", ""),
            "switch_status": detail["switch_status"],
            "legacy_text": detail["legacy_text"],
            "ordered_fields": list(detail["ordered_fields"]),
            "evidence": detail["evidence"],
            "confirmed_by": detail["confirmed_by"],
            "confirmed_at": detail["confirmed_at"],
        })
    result.sort(key=lambda item: int(item["task_id"]))
    return result


def ledger_rows(keyword: str | None = None,
                switch_status: str | None = None) -> list[dict[str, Any]]:
    """新版导出任务台账行：读取字段迁移明细，附字段次序与切换状态。

    只交付有证据的字段值：待核任务的「确认有序字段」留空并明确标记待核，
    绝不用旧逗号文本拆分填充。
    """
    ensure_migration_ledger()
    details = {int(item["task_id"]): item for item in list_migration_details(switch_status)}
    rows: list[dict[str, Any]] = []
    for task in store.rows(MODULE):
        task_id = int(task.get("id", 0))
        detail = details.get(task_id)
        if detail is None:
            continue
        if keyword and keyword.casefold() not in str(task.get("任务标识", "")).casefold() \
                and keyword.casefold() not in str(task.get("来源批次", "")).casefold():
            continue
        ordered = list(detail["ordered_fields"])
        rows.append({
            "id": task_id,
            "任务标识": task.get("任务标识", ""),
            "来源批次": task.get("来源批次", ""),
            "导出格式": task.get("导出格式", ""),
            "目标路径": task.get("目标路径", ""),
            "字段筛选": task.get("字段筛选", ""),
            "切换状态": detail["switch_status"],
            "有序字段": ordered,
            "字段次序明细": "；".join(f"{index}.{name}" for index, name in enumerate(ordered, start=1)),
            "字段数": len(ordered),
            "补交依据": detail["evidence"],
            "确认人": detail["confirmed_by"],
            "确认时间": detail["confirmed_at"],
            "导出状态": task.get("status", ""),
            "文件大小": task.get("文件大小", ""),
            "完成时间": task.get("完成时间", ""),
        })
    return rows
