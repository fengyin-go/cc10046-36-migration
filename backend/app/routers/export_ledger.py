"""导出通道字段迁移专用接口。

- GET  /api/export_channel/ledger.csv          新版导出任务台账（含字段迁移明细）
- GET  /api/export_channel/migration-details   字段迁移明细查询
- POST /api/export_channel/{task_id}/confirm-fields  按任务行补交清单确认字段次序

注意：本路由必须在通用资源路由之前注册，否则 ledger.csv / migration-details
会被 /api/{module}/{entry_id} 的整型路径参数拦截。
新版台账下载只读不写，不产生采集审计记录；只有字段确认会写审计。
"""
from __future__ import annotations

import csv
import io

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.services import field_migration as migration

router = APIRouter(prefix="/api/export_channel", tags=["导出通道字段迁移"])

LEDGER_COLUMNS = [
    "任务行ID",
    "任务标识",
    "来源批次",
    "导出格式",
    "目标路径",
    "字段筛选",
    "切换状态",
    "字段数",
    "字段次序明细",
    "确认有序字段",
    "补交依据",
    "确认人",
    "确认时间",
    "导出状态",
    "文件大小",
    "完成时间",
]


class ConfirmFieldsPayload(BaseModel):
    ordered_fields: list[str] = Field(default_factory=list)
    evidence: str = ""
    operator: str = "值班员"


@router.get("/ledger.csv")
def download_ledger(
    keyword: str | None = Query(default=None),
    switch_status: str | None = Query(default=None),
) -> StreamingResponse:
    """新版台账：值班员核对字段顺序与切换状态；下载本身不生成审核记录。"""
    rows = migration.ledger_rows(keyword=keyword, switch_status=switch_status)
    output = io.StringIO()
    output.write("\ufeff")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(LEDGER_COLUMNS)
    for row in rows:
        writer.writerow([
            row["id"],
            row["任务标识"],
            row["来源批次"],
            row["导出格式"],
            row["目标路径"],
            row["字段筛选"],
            row["切换状态"],
            row["字段数"],
            row["字段次序明细"],
            ",".join(row["有序字段"]),
            row["补交依据"],
            row["确认人"],
            row["确认时间"],
            row["导出状态"],
            row["文件大小"],
            row["完成时间"],
        ])
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="export_channel_ledger.csv"'},
    )


@router.get("/migration-details")
def get_migration_details(
    switch_status: str | None = Query(default=None),
) -> dict[str, object]:
    """字段迁移明细：按原任务行回查切换状态、原文本、依据与确认次序。"""
    items = migration.list_migration_details(switch_status=switch_status)
    return {"items": items, "total": len(items)}


@router.post("/{task_id}/confirm-fields")
def confirm_fields(task_id: int, payload: ConfirmFieldsPayload) -> dict[str, object]:
    """按任务行确认有序字段；重复确认幂等，只生效一回、只写一条审计。"""
    detail, message, applied = migration.confirm_fields(
        task_id=task_id,
        ordered_fields=payload.ordered_fields,
        evidence=payload.evidence,
        operator=payload.operator or "值班员",
    )
    if detail is None:
        raise HTTPException(status_code=400, detail=message)
    return {"ok": applied, "message": message, "applied": applied, "detail": detail}
