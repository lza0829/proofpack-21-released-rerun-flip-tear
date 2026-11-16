<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { getJSON, postJSON } from '../api'

const packs = ref([])
const packId = ref(null)
const runs = ref([])
const selectedRunId = ref(null)
const detail = ref(null)
const result = ref(null)
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

// 终局包仍可复跑：已放行包只追加审计运行、状态不动；已驳回包可重新走闭环。
const canRerun = computed(() => Boolean(packId.value) && !busy.value)

async function loadRuns() {
  if (!packId.value) {
    runs.value = []
    return
  }
  runs.value = await getJSON(`/api/checklist/runs?pack_id=${packId.value}`)
  if (runs.value.length && !runs.value.some((r) => r.id === selectedRunId.value)) {
    selectedRunId.value = runs.value[0].id
  }
  if (!runs.value.length) {
    selectedRunId.value = null
  }
}

async function loadDetail() {
  if (!selectedRunId.value) {
    detail.value = null
    return
  }
  detail.value = await getJSON(`/api/checklist/runs/${selectedRunId.value}`)
}

async function refresh() {
  packs.value = await getJSON('/api/packs')
  if (!packId.value && packs.value.length) packId.value = packs.value[0].id
  await loadRuns()
  await loadDetail()
}

onMounted(async () => {
  try { await refresh() } catch (e) { err.value = String(e.message || e) }
})

watch(selectedRunId, async () => {
  try { await loadDetail() } catch (e) { err.value = String(e.message || e) }
})

async function run() {
  err.value = ''
  busy.value = true
  try {
    result.value = await postJSON('/api/checklist/run', { pack_id: Number(packId.value) })
    selectedRunId.value = result.value.run_id
    packs.value = await getJSON('/api/packs')
    await loadRuns()
    await loadDetail()
  } catch (e) {
    err.value = String(e.message || e)
  } finally {
    busy.value = false
  }
}

async function onPackChange() {
  result.value = null
  selectedRunId.value = null
  await loadRuns()
  await loadDetail()
}
</script>
<template>
  <div class="page">
    <h1>校验清单</h1>
    <p class="muted">
      基础项：条数一致、键唯一、必填非空。每次执行都生成独立运行号且永不覆盖。已放行包复跑只追加审计运行，包状态保持已放行、原放行绑定持续有效；已驳回包复跑后回到校验结论，可重新绑定全过运行再放行。
    </p>
    <p v-if="err" class="tag danger">{{ err }}</p>
    <div class="panel">
      <h3>执行校验</h3>
      <div class="row">
        <div class="field">
          <label>证据包</label>
          <select v-model="packId" @change="onPackChange">
            <option v-for="p in packs" :key="p.id" :value="p.id">
              {{ p.pack_no }}（{{ p.item_count }} 条 · {{ STATUS_LABEL[p.status] || p.status }}）
            </option>
          </select>
        </div>
        <button :disabled="!canRerun" @click="run">跑校验清单</button>
      </div>
      <p v-if="selectedPack && selectedPack.status === 'released'" class="muted">
        当前包已放行：复跑只会追加一条新运行供审计，包状态与原放行绑定保持有效，不会被改写。
      </p>
      <p v-else-if="selectedPack && selectedPack.status === 'rejected'" class="muted">
        当前包已驳回：复跑会追加新运行并把包状态带回校验通过/未过，可重新绑定全过运行后再放行。
      </p>
      <p v-if="result">
        新运行 <span class="mono">{{ result.run_no }}</span>
        · 规则版本 <span class="mono">{{ result.rule_version_code }}</span>
        · 条目 <strong>{{ result.item_count }}</strong>
        ·
        <span class="tag" :class="result.all_passed ? 'ok' : 'danger'">
          {{ result.all_passed ? '全部通过' : '存在未通过项' }}
        </span>
        <template v-if="result.pack_status">
          <template v-if="result.status_changed">
            · 包状态现为 <span class="tag">{{ STATUS_LABEL[result.pack_status] || result.pack_status }}</span>
          </template>
          <template v-else>
            · 包状态保持 <span class="tag">{{ STATUS_LABEL[result.pack_status] || result.pack_status }}</span>（复跑仅追加审计运行）
          </template>
        </template>
      </p>
    </div>
    <div class="panel">
      <h3>运行记录</h3>
      <p v-if="!runs.length" class="muted">该包尚无运行记录。</p>
      <table v-else>
        <thead>
          <tr>
            <th>运行号</th>
            <th>规则版本</th>
            <th>各项结果</th>
            <th>是否全过</th>
            <th>时间</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="r in runs" :key="r.id" :style="r.id === selectedRunId ? 'background:#e7f0ec' : ''">
            <td class="mono">{{ r.run_no }}</td>
            <td class="mono">{{ r.rule_version_code }}</td>
            <td>{{ r.passed_count }}/{{ r.check_count }} 通过</td>
            <td>
              <span class="tag" :class="r.all_passed ? 'ok' : 'danger'">
                {{ r.all_passed ? '全过' : '未全过' }}
              </span>
              <span v-if="r.voided" class="tag warn">已作废</span>
            </td>
            <td class="mono">{{ r.created_at }}</td>
            <td><button class="ghost" @click="selectedRunId = r.id">查看</button></td>
          </tr>
        </tbody>
      </table>
    </div>
    <div class="panel" v-if="detail">
      <h3>
        运行明细 <span class="mono">{{ detail.run_no }}</span>
      </h3>
      <p class="muted">
        规则版本 <span class="mono">{{ detail.rule_version_code }}</span>
        · 执行于 <span class="mono">{{ detail.created_at }}</span>
      </p>
      <table>
        <thead>
          <tr>
            <th>校验项</th>
            <th>结果</th>
            <th>说明</th>
            <th>时间</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="r in detail.results" :key="r.id">
            <td>{{ r.check_title }}</td>
            <td>
              <span class="tag" :class="r.passed ? 'ok' : 'danger'">
                {{ r.passed ? '通过' : '未通过' }}
              </span>
            </td>
            <td>{{ r.detail }}</td>
            <td class="mono">{{ r.created_at }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
