"""字段筛选迁移：保序字段记录、迁移明细、新版台账与采集审计规则测试。

覆盖题面要求：
- 旧逗号文本不自动拆分，无法认定次序的旧任务留待核对；
- 新版登记/交付流水线保存原字段次序；
- 新版台账读取迁移明细，可核对字段顺序与切换状态；旧版下载列与单元格值不变；
- 字段确认按任务行处理、重复确认只生效一回、只写一条审计；纯下载不产生审计；
- 甲（两列，含名为「尺寸,外径」的字段）与乙（三列）旧文本相同但次序各自独立。
"""
import csv
import io
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient

from app.main import app
from app.store import store
from app.services import field_migration as migration
from app.services.export_channel import ExportChannelService

client = TestClient(app)


def _audit_count_for(task_ids):
    return sum(
        1 for row in store.rows("crawl_audit")
        if row.get("操作类型") == migration.OPERATION_CONFIRM
        and int(row.get("关联任务ID", -1)) in set(task_ids)
    )


def _parse_csv(response):
    assert response.status_code == 200
    text = response.content.decode("utf-8-sig")
    reader = csv.reader(io.StringIO(text))
    rows = list(reader)
    return rows[0], rows[1:]


def _create_old_task(task_key, batch, legacy_text):
    """模拟上线前的旧任务：只有逗号文本，没有保序字段记录。"""
    response = client.post("/api/export_channel", json={
        "values": {
            "任务标识": task_key,
            "来源批次": batch,
            "导出格式": "csv",
            "目标路径": f"/exports/{batch}.csv",
            "字段筛选": legacy_text,
            "导出状态": "排队中",
            "文件大小": "0",
            "完成时间": "",
        }
    })
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    return payload["entry"]


def test_seed_legacy_tasks_become_pending_without_splitting():
    migration.ensure_migration_ledger()
    details = migration.list_migration_details()
    seed_ids = {row["id"] for row in store.rows("export_channel") if row["id"] <= 3}
    seed_details = [d for d in details if d["task_id"] in seed_ids]
    assert seed_details, "种子导出任务应生成迁移明细"
    for detail in seed_details:
        assert detail["switch_status"] == migration.SWITCH_PENDING
        # 旧文本原样保留，有序字段留空——绝不自动按逗号拆分
        assert detail["ordered_fields"] == []
        assert detail["legacy_text"] != ""
    task = store.find("export_channel", 1)
    assert task["切换状态"] == migration.SWITCH_PENDING
    assert task["有序字段"] == []


def test_new_registration_saves_ordered_fields_and_keeps_duplicates():
    response = client.post("/api/export_channel", json={
        "values": {
            "任务标识": "EXPORT-NEW-ORDER",
            "来源批次": "BATCH-NEW-ORDER",
            "导出格式": "csv",
            "有序字段": ["尺寸", "外径", "尺寸", "单位"],
        }
    })
    entry = response.json()["entry"]
    assert entry["有序字段"] == ["尺寸", "外径", "尺寸", "单位"]
    assert entry["切换状态"] == migration.SWITCH_NATIVE
    # 旧列保留兼容文本
    assert entry["字段筛选"] == "尺寸,外径,尺寸,单位"

    detail = migration.find_migration(int(entry["id"]))
    assert detail["switch_status"] == migration.SWITCH_NATIVE
    assert detail["ordered_fields"] == ["尺寸", "外径", "尺寸", "单位"]


def test_delivery_pipeline_preserves_field_order():
    svc = ExportChannelService()
    entry = svc.domain_export("BATCH-CHAIN-ORDER", "csv", ["单位", "外径", "尺寸"])
    assert entry["有序字段"] == ["单位", "外径", "尺寸"]
    assert entry["切换状态"] == migration.SWITCH_NATIVE
    detail = migration.find_migration(int(entry["id"]))
    assert detail["ordered_fields"] == ["单位", "外径", "尺寸"]


def test_ledger_download_marks_pending_and_creates_no_audit():
    before = len(store.rows("crawl_audit"))
    response = client.get("/api/export_channel/ledger.csv")
    header, rows = _parse_csv(response)
    after = len(store.rows("crawl_audit"))
    assert before == after, "只下载新版台账不应生成审核记录"

    expected_columns = [
        "任务行ID", "任务标识", "来源批次", "导出格式", "目标路径", "字段筛选",
        "切换状态", "字段数", "字段次序明细", "确认有序字段", "补交依据",
        "确认人", "确认时间", "导出状态", "文件大小", "完成时间",
    ]
    assert header == expected_columns

    pending_row = next(r for r in rows if r[6] == migration.SWITCH_PENDING)
    # 待核任务：旧逗号文本仍在「字段筛选」列，但确认有序字段为空、字段数为 0
    assert pending_row[5] != ""
    assert pending_row[7] == "0"
    assert pending_row[8] == ""
    assert pending_row[9] == ""


def test_legacy_download_keeps_original_columns_and_cell_values():
    task = _create_old_task("EXPORT-LEGACY-CHECK", "BATCH-LEGACY-CHECK", "尺寸,外径,单位")
    response = client.get("/api/export_channel/export", params={"来源批次": "BATCH-LEGACY-CHECK"})
    header, rows = _parse_csv(response)
    # 旧版台账列结构原样不变
    assert header == [
        "id", "任务标识", "来源批次", "导出格式", "目标路径",
        "字段筛选", "导出状态", "文件大小", "完成时间", "status",
    ]
    row = next(r for r in rows if r[0] == str(task["id"]))
    assert row[5] == "尺寸,外径,单位", "旧版下载单元格值必须与旧文本一致"
    assert "切换状态" not in header and "有序字段" not in header


def test_full_jia_yi_confirmation_scenario():
    batch = "BATCH-JIA-YI"
    legacy = "尺寸,外径,单位"
    jia = _create_old_task("EXPORT-JIA", batch, legacy)
    yi = _create_old_task("EXPORT-YI", batch, legacy)
    jia_id, yi_id = int(jia["id"]), int(yi["id"])

    # 两笔旧记录文本相同，均待核，且未自动拆分
    for task_id in (jia_id, yi_id):
        detail = migration.find_migration(task_id)
        assert detail["switch_status"] == migration.SWITCH_PENDING
        assert detail["legacy_text"] == legacy
        assert detail["ordered_fields"] == []
    assert _audit_count_for([jia_id, yi_id]) == 0

    # 乙补齐前：空清单确认必须被拒，不能自动按逗号拆分
    bad = client.post(f"/api/export_channel/{yi_id}/confirm-fields", json={
        "ordered_fields": [], "evidence": "尝试自动拆分",
    })
    assert bad.status_code == 400
    # 缺补交依据同样拒绝
    bad2 = client.post(f"/api/export_channel/{yi_id}/confirm-fields", json={
        "ordered_fields": ["尺寸"], "evidence": "  ",
    })
    assert bad2.status_code == 400
    assert _audit_count_for([jia_id, yi_id]) == 0

    # 甲先确认：甲实际为两列，首列名称本身含逗号，系统不得拆分
    ok = client.post(f"/api/export_channel/{jia_id}/confirm-fields", json={
        "ordered_fields": ["尺寸,外径", "单位"],
        "evidence": "甲的原字段清单（两列）",
        "operator": "值班员甲",
    })
    assert ok.status_code == 200
    assert ok.json()["applied"] is True
    jia_detail = migration.find_migration(jia_id)
    assert jia_detail["switch_status"] == migration.SWITCH_CONFIRMED
    assert jia_detail["ordered_fields"] == ["尺寸,外径", "单位"]
    assert _audit_count_for([jia_id, yi_id]) == 1

    # 甲先行、乙待核时即可下载新版台账，乙被明确标记待核
    response = client.get("/api/export_channel/ledger.csv", params={"keyword": batch})
    _, rows = _parse_csv(response)
    assert len(rows) == 2
    by_id = {int(r[0]): r for r in rows}
    assert by_id[jia_id][6] == migration.SWITCH_CONFIRMED
    assert by_id[jia_id][7] == "2"
    assert by_id[jia_id][8] == "1.尺寸,外径；2.单位"
    assert by_id[yi_id][6] == migration.SWITCH_PENDING
    assert by_id[yi_id][9] == ""
    # 重复下载不增加确认记录
    client.get("/api/export_channel/ledger.csv")
    client.get("/api/export_channel/ledger.csv", params={"switch_status": migration.SWITCH_PENDING})
    assert _audit_count_for([jia_id, yi_id]) == 1

    # 重复确认甲：幂等，不生效、不新增审计、次序不变
    repeat = client.post(f"/api/export_channel/{jia_id}/confirm-fields", json={
        "ordered_fields": ["被篡改的次序"],
        "evidence": "重复提交",
    })
    assert repeat.json()["applied"] is False
    assert migration.find_migration(jia_id)["ordered_fields"] == ["尺寸,外径", "单位"]
    assert _audit_count_for([jia_id, yi_id]) == 1

    # 乙补齐：实际为三列
    ok2 = client.post(f"/api/export_channel/{yi_id}/confirm-fields", json={
        "ordered_fields": ["尺寸", "外径", "单位"],
        "evidence": "乙补交的原字段清单（三列）",
    })
    assert ok2.json()["applied"] is True
    assert _audit_count_for([jia_id, yi_id]) == 2

    # 两笔均按各自字段顺序下载新版台账
    response = client.get("/api/export_channel/ledger.csv", params={"keyword": batch})
    _, rows = _parse_csv(response)
    by_id = {int(r[0]): r for r in rows}
    assert by_id[jia_id][7] == "2" and by_id[yi_id][7] == "3"
    assert by_id[jia_id][8] == "1.尺寸,外径；2.单位"
    assert by_id[yi_id][8] == "1.尺寸；2.外径；3.单位"
    assert by_id[jia_id][9] == "尺寸,外径,单位" and by_id[yi_id][9] == "尺寸,外径,单位"
    # 原始拼接文本相同，靠字段数与编号明细区分
    assert by_id[jia_id][10] == "甲的原字段清单（两列）"
    assert by_id[yi_id][10] == "乙补交的原字段清单（三列）"

    # 旧入口下载同批：列与单元格值保持旧样，两笔的旧文本仍是原样
    response = client.get("/api/export_channel/export", params={"来源批次": batch})
    header, old_rows = _parse_csv(response)
    assert header == [
        "id", "任务标识", "来源批次", "导出格式", "目标路径",
        "字段筛选", "导出状态", "文件大小", "完成时间", "status",
    ]
    old_by_id = {int(r[0]): r for r in old_rows}
    assert old_by_id[jia_id][5] == legacy
    assert old_by_id[yi_id][5] == legacy

    # 采集审计按原任务行独立回查：每行含原字段文本、补交依据、确认后的有序字段
    audits = [
        row for row in store.rows("crawl_audit")
        if row.get("操作类型") == migration.OPERATION_CONFIRM
        and int(row.get("关联任务ID", -1)) in {jia_id, yi_id}
    ]
    audit_by_task = {int(row["关联任务ID"]): row for row in audits}
    assert audit_by_task[jia_id]["原字段文本"] == legacy
    assert audit_by_task[jia_id]["补交依据"] == "甲的原字段清单（两列）"
    assert audit_by_task[jia_id]["确认有序字段"] == ["尺寸,外径", "单位"]
    assert audit_by_task[yi_id]["原字段文本"] == legacy
    assert audit_by_task[yi_id]["确认有序字段"] == ["尺寸", "外径", "单位"]
    # 变更前值承载原字段文本，变更后值承载确认次序
    assert audit_by_task[yi_id]["变更前值"] == legacy
    assert audit_by_task[yi_id]["变更后值"] == "尺寸,外径,单位"

    # 迁移明细接口支持按切换状态筛选
    pending = client.get(
        "/api/export_channel/migration-details",
        params={"switch_status": migration.SWITCH_PENDING},
    )
    pending_ids = {item["task_id"] for item in pending.json()["items"]}
    assert jia_id not in pending_ids and yi_id not in pending_ids
    confirmed = client.get(
        "/api/export_channel/migration-details",
        params={"switch_status": migration.SWITCH_CONFIRMED},
    )
    confirmed_ids = {item["task_id"] for item in confirmed.json()["items"]}
    assert {jia_id, yi_id} <= confirmed_ids

    # 再次重复下载与重复确认，审计仍只有两笔
    client.get("/api/export_channel/ledger.csv")
    client.post(f"/api/export_channel/{yi_id}/confirm-fields", json={
        "ordered_fields": ["尺寸"], "evidence": "再次重复提交",
    })
    assert _audit_count_for([jia_id, yi_id]) == 2


def test_confirm_unknown_task_returns_400():
    response = client.post("/api/export_channel/999999/confirm-fields", json={
        "ordered_fields": ["a"], "evidence": "x",
    })
    assert response.status_code == 400
