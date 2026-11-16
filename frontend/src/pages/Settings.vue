<script setup>
import { computed, onMounted, ref } from 'vue'
import { getJSON, postJSON } from '../api'

const LABEL = {
  default_sample_rate: '默认采样率',
  require_checklist_pass: '放行须清单全过',
  sample_mode: '采样模式',
  release_run_policy: '放行可用运行策略',
  release_run_policy_label: '策略说明',
}

function displayValue(k, v) {
  if (k === 'require_checklist_pass') {
    return v === '1' || v === 1 || v === true || v === 'true' ? '是' : '否'
  }
  if (k === 'sample_mode') {
    return ({ deterministic: '确定性抽样', random: '随机抽样' })[v] || v
  }
  if (k === 'release_run_policy') {
    return ({ latest_only: '仅最近一次且全过', any_passed: '历史任一次全过' })[v] || v
  }
  return v
}

const settings = ref({})
const rules = ref([])
const policy = ref('latest_only')
const newCode = ref('')
const newTitle = ref('')
const err = ref('')
const notice = ref('')
const busy = ref(false)

const baseSettings = computed(() =>
  Object.fromEntries(
    Object.entries(settings.value).filter(([k]) => k !== 'release_run_policy_label')
  )
)

async function refresh() {
  settings.value = await getJSON('/api/settings')
  policy.value = settings.value.release_run_policy || 'latest_only'
  rules.value = await getJSON('/api/rules')
}

onMounted(async () => {
  try { await refresh() } catch (e) { err.value = String(e.message || e) }
})

async function savePolicy() {
  err.value = ''
  busy.value = true
  try {
    await postJSON('/api/settings/release-policy', { release_run_policy: policy.value })
    await refresh()
  } catch (e) {
    err.value = String(e.message || e)
  } finally {
    busy.value = false
  }
}

async function createRule() {
  err.value = ''
  notice.value = ''
  busy.value = true
  try {
    const rule = await postJSON('/api/rules', {
      code: newCode.value,
      title: newTitle.value,
      payload: {},
    })
    newCode.value = ''
    newTitle.value = ''
    notice.value = `已创建规则版本 ${rule.code}（尚未晋升）`
    await refresh()
  } catch (e) {
    err.value = String(e.message || e)
  } finally {
    busy.value = false
  }
}

async function promote(rule) {
  err.value = ''
  notice.value = ''
  busy.value = true
  try {
    await postJSON(`/api/rules/${rule.id}/promote`)
    notice.value = `规则版本 ${rule.code} 已晋升；此前的历史运行作废，不可再用于放行`
    await refresh()
  } catch (e) {
    err.value = String(e.message || e)
  } finally {
    busy.value = false
  }
}
</script>
<template>
  <div class="page">
    <h1>设置</h1>
    <p class="muted">放行可用运行策略二选一；规则版本晋升后，旧运行即作废。</p>
    <p v-if="err" class="tag danger">{{ err }}</p>
    <p v-if="notice" class="tag ok">{{ notice }}</p>
    <div class="panel">
      <h3>放行可用运行策略</h3>
      <div class="row">
        <div class="field">
          <label>策略</label>
          <select v-model="policy" :disabled="busy">
            <option value="latest_only">仅允许绑定该包最近一次且全过的运行</option>
            <option value="any_passed">
              允许绑定该包历史上任一次全过运行（晋升后旧运行作废）
            </option>
          </select>
        </div>
        <button :disabled="busy" @click="savePolicy">保存策略</button>
      </div>
      <p class="muted">
        当前：<span class="tag">{{ settings.release_run_policy_label || '—' }}</span>
      </p>
    </div>
    <div class="panel">
      <h3>规则版本</h3>
      <table>
        <thead>
          <tr>
            <th>版本号</th>
            <th>标题</th>
            <th>状态</th>
            <th>晋升序号</th>
            <th>晋升时间</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="r in rules" :key="r.id">
            <td class="mono">{{ r.code }}</td>
            <td>{{ r.title }}</td>
            <td>
              <span class="tag" :class="r.active ? 'ok' : ''">
                {{ r.active ? '生效中' : '未生效' }}
              </span>
            </td>
            <td class="mono">{{ r.promotion_seq ?? '—' }}</td>
            <td class="mono">{{ r.promoted_at || '—' }}</td>
            <td>
              <button v-if="!r.active" class="ghost" :disabled="busy" @click="promote(r)">
                晋升
              </button>
            </td>
          </tr>
        </tbody>
      </table>
      <div class="row" style="margin-top:0.85rem">
        <div class="field">
          <label>新版本号</label>
          <input v-model="newCode" placeholder="例如 RULES-V2" />
        </div>
        <div class="field">
          <label>标题</label>
          <input v-model="newTitle" placeholder="例如 基础校验规则 v2" />
        </div>
        <button class="ghost" :disabled="busy || !newCode" @click="createRule">创建规则版本</button>
      </div>
    </div>
    <div class="panel">
      <h3>底座配置</h3>
      <table>
        <thead>
          <tr>
            <th>配置项</th>
            <th>取值</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(v, k) in baseSettings" :key="k">
            <td>{{ LABEL[k] || k }}</td>
            <td><span class="tag">{{ displayValue(k, v) }}</span></td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
