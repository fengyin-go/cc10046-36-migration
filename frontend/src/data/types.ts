/** 纯前端数据层的公共类型：与全栈版后端返回的结构保持一致，换回后端时页面不用改。 */

export type EntryRow = {
  id: number
  status: string
  pending: boolean
  abnormal: boolean
  [field: string]: string | number | boolean | string[]
}

/** 字段迁移明细：与后端 field_migration 明细结构对应，按原任务行回查。 */
export type MigrationDetail = {
  task_id: number
  任务标识: string
  来源批次: string
  switch_status: string
  legacy_text: string
  ordered_fields: string[]
  evidence: string
  confirmed_by: string
  confirmed_at: string
}

export type ConfirmResult = {
  ok: boolean
  applied: boolean
  message: string
  detail?: MigrationDetail
}

export type ModuleMeta = {
  key: string
  name: string
  entity: string
  desc: string
  fields: string[]
  statuses: string[]
  actions: string[]
  actionTargets: Record<string, string>
  metrics: string[]
}

export type PageResult = {
  items: EntryRow[]
  total: number
  page: number
  size: number
}

export type ActionResult = {
  ok: boolean
  message: string
}

export type OverviewResult = {
  cards: { label: string; value: number }[]
  modules: { name: string; created: number; pending: number; abnormal: number }[]
}
