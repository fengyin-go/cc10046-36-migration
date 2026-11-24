"""业务路由汇总：所有模块共用一套资源路由，由领域服务完成分派。"""
from __future__ import annotations

from app.routers import resource
from app.routers import chains
from app.routers import export_ledger

# export_ledger 的固定路径（ledger.csv、migration-details）必须先于
# 通用资源路由注册，避免被 /api/{module}/{entry_id} 动态路径抢先匹配。
ROUTERS = [export_ledger, resource, chains]
