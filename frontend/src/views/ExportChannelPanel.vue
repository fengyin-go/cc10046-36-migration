<template>
  <section class="migration-panel" data-testid="field-migration-panel">
    <header class="migration-head">
      <div>
        <h3>字段迁移明细</h3>
        <p class="page-desc">
          旧版逗号文本不自动拆分；无法认定次序的旧任务留待核对，按任务行补交清单确认。
          下载新版台账只读取明细，不生成审核记录。
        </p>
      </div>
      <div class="page-actions">
        <select v-model="statusFilter" data-testid="migration-status-filter" @change="loadDetails">
          <option value="">全部切换状态</option>
          <option value="原生存序">原生存序</option>
          <option value="待核对">待核对</option>
          <option value="已确认">已确认</option>
        </select>
        <button class="btn primary" data-testid="download-ledger" type="button" @click="downloadLedger">
          下载新版台账 CSV
        </button>
      </div>
    </header>
    <p v-if="errorMessage" class="error-text" data-testid="migration-error">{{ errorMessage }}</p>

    <table class="data-table migration-table">
      <thead>
        <tr>
          <th>任务行ID</th>
          <th>任务标识</th>
          <th>来源批次</th>
          <th>原字段文本</th>
          <th>确认后的有序字段</th>
          <th>切换状态</th>
          <th>补交依据</th>
          <th>确认人/时间</th>
          <th>核对操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="detail in details" :key="detail.task_id" :data-testid="`migration-row-${detail.task_id}`">
          <td>{{ detail.task_id }}</td>
          <td>{{ detail.任务标识 }}</td>
          <td>{{ detail.来源批次 }}</td>
          <td class="legacy-text">{{ detail.legacy_text || '—' }}</td>
          <td>
            <ol v-if="detail.ordered_fields.length" class="ordered-fields">
              <li v-for="(name, index) in detail.ordered_fields" :key="`${detail.task_id}-${index}`">
                {{ name }}
              </li>
            </ol>
            <span v-else class="hint">待核，未自动拆分</span>
          </td>
          <td>
            <span class="status-tag" :data-status="detail.switch_status">{{ detail.switch_status }}</span>
          </td>
          <td>{{ detail.evidence || '—' }}</td>
          <td>
            <template v-if="detail.confirmed_at">
              {{ detail.confirmed_by }}<br />{{ detail.confirmed_at }}
            </template>
            <span v-else>—</span>
          </td>
          <td>
            <button
              v-if="detail.switch_status === '待核对'"
              class="link"
              type="button"
              :data-testid="`open-confirm-${detail.task_id}`"
              @click="openConfirm(detail)"
            >
              补交清单确认
            </button>
            <span v-else class="hint">无需重复确认</span>
          </td>
        </tr>
        <tr v-if="!details.length">
          <td colspan="9" class="empty-state">当前筛选下没有字段迁移明细</td>
        </tr>
      </tbody>
    </table>

    <div v-if="confirmTarget" class="modal-backdrop" data-testid="confirm-modal">
      <form class="modal" @submit.prevent="submitConfirm">
        <h3>按任务行确认字段次序</h3>
        <p class="page-desc">
          任务 {{ confirmTarget.任务标识 }}（行 {{ confirmTarget.task_id }}）；
          原字段文本：<strong>{{ confirmTarget.legacy_text }}</strong>
        </p>
        <label class="create-field">
          <span>有序字段（每行一个，按导出列顺序，名称含逗号也不拆分）</span>
          <textarea
            v-model="confirmText"
            rows="6"
            data-testid="confirm-fields-input"
            placeholder="尺寸&#10;外径&#10;单位"
            required
          ></textarea>
        </label>
        <label class="create-field">
          <span>补交依据</span>
          <input v-model="confirmEvidence" data-testid="confirm-evidence-input" required />
        </label>
        <label class="create-field">
          <span>确认人</span>
          <input v-model="confirmOperator" data-testid="confirm-operator-input" />
        </label>
        <div class="page-actions">
          <button class="btn" type="button" @click="closeConfirm">取消</button>
          <button class="btn primary" data-testid="submit-confirm" type="submit" :disabled="submitting">
            {{ submitting ? '提交中…' : '确认字段次序' }}
          </button>
        </div>
        <p v-if="errorMessage" class="error-text" data-testid="confirm-error">{{ errorMessage }}</p>
      </form>
    </div>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import {
  confirmExportFields,
  downloadExportLedger,
  listMigrationDetails,
} from '@/api/backend-service'
import type { MigrationDetail } from '@/data/types'

const emit = defineEmits<{ (event: 'changed'): void }>()

const details = ref<MigrationDetail[]>([])
const statusFilter = ref('')
const errorMessage = ref('')
const confirmTarget = ref<MigrationDetail | null>(null)
const confirmText = ref('')
const confirmEvidence = ref('')
const confirmOperator = ref('值班员')
const submitting = ref(false)

async function loadDetails() {
  errorMessage.value = ''
  try {
    const payload = await listMigrationDetails(statusFilter.value || undefined)
    details.value = payload.items
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '字段迁移明细读取失败'
  }
}

async function downloadLedger() {
  errorMessage.value = ''
  try {
    const filters: Record<string, string> = {}
    if (statusFilter.value) filters.switch_status = statusFilter.value
    await downloadExportLedger(filters)
    // 纯下载不产生确认记录，仅刷新本地明细状态
    await loadDetails()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '新版台账下载失败'
  }
}

function openConfirm(detail: MigrationDetail) {
  confirmTarget.value = detail
  confirmText.value = ''
  confirmEvidence.value = ''
  confirmOperator.value = '值班员'
  errorMessage.value = ''
}

function closeConfirm() {
  confirmTarget.value = null
}

async function submitConfirm() {
  if (!confirmTarget.value) return
  submitting.value = true
  errorMessage.value = ''
  try {
    // 按行解析，绝不在前端按逗号拆分；名称本身含逗号时保留为一个字段
    const orderedFields = confirmText.value
      .split('\n')
      .map((line) => line.trim())
      .filter((line) => line.length > 0)
    const result = await confirmExportFields(
      confirmTarget.value.task_id,
      orderedFields,
      confirmEvidence.value.trim(),
      confirmOperator.value.trim() || '值班员',
    )
    if (!result.ok) throw new Error(result.message)
    closeConfirm()
    await loadDetails()
    emit('changed')
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '字段确认失败'
  } finally {
    submitting.value = false
  }
}

onMounted(loadDetails)
defineExpose({ reload: loadDetails })
</script>

<style scoped>
.migration-panel {
  margin: 16px 0 24px;
  padding: 16px;
  border: 1px solid var(--border, #d8dee6);
  border-radius: 10px;
  background: #fafbfc;
}

.migration-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 12px;
}

.migration-head h3 {
  margin: 0 0 4px;
}

.migration-table {
  margin-top: 8px;
}

.legacy-text {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  color: #5b6472;
}

.ordered-fields {
  margin: 0;
  padding-left: 20px;
}

.ordered-fields li {
  line-height: 1.6;
}

.status-tag {
  display: inline-block;
  padding: 2px 10px;
  border-radius: 999px;
  font-size: 12px;
  background: #eef1f5;
  color: #434d5c;
}

.status-tag[data-status='待核对'] {
  background: #fff3e0;
  color: #b26a00;
}

.status-tag[data-status='已确认'] {
  background: #e6f4ea;
  color: #1e7e34;
}

.status-tag[data-status='原生存序'] {
  background: #e8f0fe;
  color: #1a56c4;
}

.hint {
  color: #8a93a2;
  font-size: 12px;
}

textarea {
  width: 100%;
  resize: vertical;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
}
</style>
