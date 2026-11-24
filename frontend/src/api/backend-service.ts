import { request } from './client'
import { moduleMeta } from '@/data/modules'
import type {
  ActionResult,
  ConfirmResult,
  EntryRow,
  MigrationDetail,
  OverviewResult,
  PageResult,
} from '@/data/types'

export { moduleMeta }

export async function listEntries(
  key: string,
  filters: Record<string, string> = {},
): Promise<PageResult> {
  const query = new URLSearchParams(filters).toString()
  const response = await request(`/api/${key}?${query}`)
  if (!response.ok) throw new Error('业务数据读取失败')
  return await response.json()
}

export async function createEntry(
  key: string,
  values: Record<string, string | string[]>,
): Promise<ActionResult> {
  const response = await request(`/api/${key}`, {
    method: 'POST',
    body: JSON.stringify({ values }),
  })
  return await response.json()
}

export async function runAction(
  key: string,
  id: number,
  action: string,
): Promise<ActionResult> {
  const response = await request(`/api/${key}/${id}/actions`, {
    method: 'POST',
    body: JSON.stringify({ action }),
  })
  return await response.json()
}

export async function downloadEntries(
  key: string,
  filters: Record<string, string> = {},
): Promise<void> {
  const query = new URLSearchParams(filters).toString()
  const response = await request(`/api/${key}/export?${query}`)
  if (!response.ok) throw new Error('业务数据导出失败')
  const url = URL.createObjectURL(await response.blob())
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `${key}.csv`
  document.body.appendChild(anchor)
  anchor.click()
  document.body.removeChild(anchor)
  URL.revokeObjectURL(url)
}

export async function loadOverview(): Promise<OverviewResult> {
  const response = await request('/api/overview')
  if (!response.ok) throw new Error('运营概览读取失败')
  return await response.json()
}

async function triggerCsvDownload(response: Response, filename: string): Promise<void> {
  const url = URL.createObjectURL(await response.blob())
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  document.body.appendChild(anchor)
  anchor.click()
  document.body.removeChild(anchor)
  URL.revokeObjectURL(url)
}

/** 新版导出任务台账：读取字段迁移明细，下载本身不生成审核记录。 */
export async function downloadExportLedger(
  filters: Record<string, string> = {},
): Promise<void> {
  const query = new URLSearchParams(filters).toString()
  const suffix = query ? `?${query}` : ''
  const response = await request(`/api/export_channel/ledger.csv${suffix}`)
  if (!response.ok) throw new Error('新版导出任务台账下载失败')
  await triggerCsvDownload(response, 'export_channel_ledger.csv')
}

/** 字段迁移明细：值班员按原任务行核对切换状态、原文本与确认次序。 */
export async function listMigrationDetails(
  switchStatus?: string,
): Promise<{ items: MigrationDetail[]; total: number }> {
  const query = switchStatus ? `?switch_status=${encodeURIComponent(switchStatus)}` : ''
  const response = await request(`/api/export_channel/migration-details${query}`)
  if (!response.ok) throw new Error('字段迁移明细读取失败')
  return await response.json()
}

/** 按任务行补交清单确认字段次序；重复确认由后端幂等处理，只生效一回。 */
export async function confirmExportFields(
  taskId: number,
  orderedFields: string[],
  evidence: string,
  operator = '值班员',
): Promise<ConfirmResult> {
  const response = await request(`/api/export_channel/${taskId}/confirm-fields`, {
    method: 'POST',
    body: JSON.stringify({ ordered_fields: orderedFields, evidence, operator }),
  })
  if (response.status === 400) {
    const detail = (await response.json()).detail as string
    return { ok: false, applied: false, message: detail }
  }
  if (!response.ok) throw new Error('字段确认请求失败')
  return await response.json()
}
