<script setup>
import { onMounted, ref } from 'vue'
import { getJSON, postJSON } from '../api'

const batches = ref([])
const packs = ref([])
const batchId = ref(null)
const last = ref(null)
const err = ref('')
const busy = ref(false)

async function refresh() {
  batches.value = await getJSON('/api/samples')
  packs.value = await getJSON('/api/packs')
  if (!batchId.value && batches.value.length) batchId.value = batches.value[0].id
}

onMounted(async () => {
  try { await refresh() } catch (e) { err.value = String(e.message || e) }
})

async function build() {
  err.value = ''
  busy.value = true
  try {
    last.value = await postJSON('/api/packs/build', { batch_id: Number(batchId.value) })
    packs.value = await getJSON('/api/packs')
  } catch (e) {
    err.value = String(e.message || e)
  } finally {
    busy.value = false
  }
}
</script>
<template>
  <div class="page">
    <h1>证据包</h1>
    <p class="muted">由采样批次生成证据包：条目摘要、条数与包指纹。</p>
    <p v-if="err" class="tag danger">{{ err }}</p>
    <div class="panel">
      <h3>生成证据包</h3>
      <div class="row">
        <div class="field">
          <label>采样批次</label>
          <select v-model="batchId">
            <option v-for="b in batches" :key="b.id" :value="b.id">
              {{ b.batch_no }}（{{ b.subject_title }} · {{ b.sample_count }} 条）
            </option>
          </select>
        </div>
        <button :disabled="busy || !batchId" @click="build">生成证据包</button>
      </div>
      <div v-if="last" style="margin-top:0.75rem">
        <p>
          包号 <span class="mono">{{ last.pack_no }}</span>
          · 条目 <strong>{{ last.item_count }}</strong>
        </p>
        <p class="mono muted">指纹 {{ last.fingerprint }}</p>
      </div>
    </div>
    <div class="panel">
      <h3>证据包列表</h3>
      <table>
        <thead>
          <tr>
            <th>包号</th>
            <th>对象</th>
            <th>批次</th>
            <th>条目数</th>
            <th>指纹</th>
            <th>状态</th>
            <th>最近运行</th>
            <th>时间</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="p in packs" :key="p.id">
            <td class="mono">{{ p.pack_no }}</td>
            <td>{{ p.subject_title }}</td>
            <td>{{ p.batch_id }}</td>
            <td>{{ p.item_count }}</td>
            <td class="mono" style="max-width:12rem;overflow:hidden;text-overflow:ellipsis">{{ p.fingerprint }}</td>
            <td><span class="tag">{{ ({ built: '已生成', checked_ok: '校验通过', checked_fail: '校验未过', released: '已放行', rejected: '已驳回' })[p.status] || p.status }}</span></td>
            <td class="mono">
              <template v-if="p.latest_run_no">
                {{ p.latest_run_no }}
                <span class="tag" :class="p.latest_run_all_passed ? 'ok' : 'danger'">
                  {{ p.latest_run_all_passed ? '全过' : '未全过' }}
                </span>
              </template>
              <span v-else class="muted">—</span>
            </td>
            <td class="mono">{{ p.created_at }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
