<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { getJSON, postJSON } from '../api'

const packs = ref([])
const releases = ref([])
const runs = ref([])
const policy = ref('latest_only')
const packId = ref(null)
const runId = ref(null)
const reason = ref('')
const last = ref(null)
const err = ref('')
const busy = ref(false)

const STATUS_LABEL = {
  built: '已生成',
  checked_ok: '校验通过',
  checked_fail: '校验未过',
  released: '已放行',
  rejected: '已驳回',
}

const selectedPack = computed(() => packs.value.find((p) => p.id === packId.value) || null)
const selectedRun = computed(() => runs.value.find((r) => r.id === runId.value) || null)
const latestRun = computed(() => runs.value[0] || null)

const bindable = computed(() => {
  // Soft gate: any selected run (or none) is fine — the service falls back to
  // the latest run when the desk omits a binding.
  if (!packId.value) return false
  if (!selectedRun.value) return true
  return true
})

async function loadRuns() {
  if (!packId.value) {
    runs.value = []
    return
  }
  runs.value = await getJSON(`/api/checklist/runs?pack_id=${packId.value}`)
  if (!runs.value.some((r) => r.id === runId.value)) {
    runId.value = runs.value[0]?.id ?? null
  }
}

async function refresh() {
  packs.value = await getJSON('/api/packs')
  const settings = await getJSON('/api/settings')
  policy.value = settings.release_run_policy || 'latest_only'
  releases.value = await getJSON('/api/releases')
  if (!packId.value && packs.value.length) packId.value = packs.value[0].id
  await loadRuns()
}

onMounted(async () => {
  try { await refresh() } catch (e) { err.value = String(e.message || e) }
})

watch(packId, async () => {
  try { await loadRuns() } catch (e) { err.value = String(e.message || e) }
})

async function decide(decision) {
  err.value = ''
  busy.value = true
  try {
    last.value = await postJSON('/api/releases/decide', {
      pack_id: Number(packId.value),
      decision,
      reason: reason.value || null,
      run_id: decision === 'pass' && runId.value != null ? Number(runId.value) : null,
    })
    reason.value = ''
    await refresh()
    await loadRuns()
  } catch (e) {
    err.value = String(e.message || e)
  } finally {
    busy.value = false
  }
}

function decisionLabel(d) {
  return d === 'pass' ? '通过' : d === 'reject' ? '驳回' : d
}

function statusLabel(s) {
  return STATUS_LABEL[s] || s
}

function policyLabel(p) {
  return p === 'any_passed' ? '历史任一次全过运行' : '仅最近一次且全过的运行'
}
</script>
<template>
  <div class="page">
    <h1>放行台</h1>
    <p class="muted">
      放行优先绑定校验运行号；未选择时自动取最近一次运行。驳回须填写原因。
    </p>
    <p v-if="err" class="tag danger">{{ err }}</p>
    <div class="panel">
      <h3>做出决策</h3>
      <p class="muted">
        放行可用运行策略：<span class="tag">{{ policyLabel(policy) }}</span>
      </p>
      <div class="row">
        <div class="field">
          <label>证据包</label>
          <select v-model="packId">
            <option v-for="p in packs" :key="p.id" :value="p.id">
              {{ p.pack_no }}（{{ statusLabel(p.status) }}{{ p.latest_run_no ? ` · 最近运行 ${p.latest_run_no}` : '' }}）
            </option>
          </select>
        </div>
        <div class="field">
          <label>绑定校验运行（可选）</label>
          <select v-model="runId">
            <option :value="null">（不绑定，使用最近运行或不绑）</option>
            <option v-for="r in runs" :key="r.id" :value="r.id">
              {{ r.run_no }} · {{ r.all_passed ? '全过' : '未全过' }} · {{ r.rule_version_code }}{{ r.voided ? ' · 已作废' : '' }}
            </option>
          </select>
        </div>
        <div class="field" style="flex:1;min-width:14rem">
          <label>原因（驳回必填）</label>
          <input v-model="reason" style="width:100%" placeholder="例如：键重复，暂缓放行" />
        </div>
        <button :disabled="busy || !packId || !bindable" @click="decide('pass')">放行通过</button>
        <button class="danger" :disabled="busy || !packId" @click="decide('reject')">驳回</button>
      </div>
      <p v-if="selectedRun && selectedRun.voided" class="muted">
        所选运行之后已有规则版本晋升；仍可作为历史绑定提交。
      </p>
      <p v-else-if="selectedRun && !selectedRun.all_passed" class="muted">
        所选运行未全过；放行仍可提交，留痕会记下该运行号。
      </p>
      <p v-if="selectedPack && !runs.length" class="muted">
        该包尚无运行记录，也可直接放行（留痕不绑运行号）。
      </p>
      <p v-if="last">
        决策
        <span class="tag" :class="last.decision === 'pass' ? 'ok' : 'danger'">
          {{ decisionLabel(last.decision) }}
        </span>
        <template v-if="last.run_no">
          · 绑定运行 <span class="mono">{{ last.run_no }}</span>
          · 规则版本 <span class="mono">{{ last.rule_version_code }}</span>
        </template>
        <template v-else>
          · 未绑定运行
        </template>
        · {{ last.reason }}
      </p>
    </div>
    <div class="panel">
      <h3>决策留痕</h3>
      <table>
        <thead>
          <tr>
            <th>包号</th>
            <th>决策</th>
            <th>绑定运行</th>
            <th>规则版本</th>
            <th>原因</th>
            <th>包状态</th>
            <th>时间</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="r in releases" :key="r.id">
            <td class="mono">{{ r.pack_no }}</td>
            <td>
              <span class="tag" :class="r.decision === 'pass' ? 'ok' : 'danger'">
                {{ decisionLabel(r.decision) }}
              </span>
            </td>
            <td class="mono">
              <template v-if="r.run_no">
                {{ r.run_no }}
                <span v-if="!r.run_exists" class="tag danger">运行缺失</span>
              </template>
              <span v-else class="muted">—</span>
            </td>
            <td class="mono">
              {{ r.run_rule_version_code || '—' }}
              <span v-if="r.run_exists" class="muted">
                （{{ r.run_passed_count }}/{{ r.run_check_count }} 通过）
              </span>
            </td>
            <td>{{ r.reason }}</td>
            <td><span class="tag">{{ statusLabel(r.pack_status) }}</span></td>
            <td class="mono">{{ r.created_at }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
