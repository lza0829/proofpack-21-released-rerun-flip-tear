<script setup>
import { onMounted, ref } from 'vue'
import { getJSON, postJSON } from '../api'

const subjects = ref([])
const batches = ref([])
const subjectId = ref(null)
const rate = ref(0.3)
const seed = ref('核证匣-默认种子')
const last = ref(null)
const err = ref('')
const busy = ref(false)

async function refresh() {
  subjects.value = await getJSON('/api/subjects')
  batches.value = await getJSON('/api/samples')
  if (!subjectId.value && subjects.value.length) subjectId.value = subjects.value[0].id
}

onMounted(async () => {
  try { await refresh() } catch (e) { err.value = String(e.message || e) }
})

async function run() {
  err.value = ''
  busy.value = true
  try {
    last.value = await postJSON('/api/samples/run', {
      subject_id: Number(subjectId.value),
      rate: Number(rate.value),
      seed: seed.value,
    })
    batches.value = await getJSON('/api/samples')
  } catch (e) {
    err.value = String(e.message || e)
  } finally {
    busy.value = false
  }
}
</script>
<template>
  <div class="page">
    <h1>采样台</h1>
    <p class="muted">按固定种子对举证对象做确定性抽样，落采样批次与样本行。</p>
    <p v-if="err" class="tag danger">{{ err }}</p>
    <div class="panel">
      <h3>执行采样</h3>
      <div class="row">
        <div class="field">
          <label>举证对象</label>
          <select v-model="subjectId">
            <option v-for="s in subjects" :key="s.id" :value="s.id">{{ s.title }}</option>
          </select>
        </div>
        <div class="field">
          <label>采样率</label>
          <input type="number" min="0" max="1" step="0.05" v-model.number="rate" />
        </div>
        <div class="field">
          <label>种子</label>
          <input v-model="seed" class="mono" style="min-width:12rem" />
        </div>
        <button :disabled="busy || !subjectId" @click="run">执行采样</button>
      </div>
      <div v-if="last" style="margin-top:0.75rem">
        <p>
          批次 <span class="mono">{{ last.batch_no }}</span>
          · 源 <strong>{{ last.source_count }}</strong>
          · 样本 <strong>{{ last.sample_count }}</strong>
          · 种子 <span class="tag">{{ last.seed }}</span>
        </p>
      </div>
    </div>
    <div class="panel">
      <h3>采样批次</h3>
      <table>
        <thead>
          <tr>
            <th>批次号</th>
            <th>对象</th>
            <th>种子</th>
            <th>采样率</th>
            <th>源条数</th>
            <th>样本数</th>
            <th>状态</th>
            <th>时间</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="b in batches" :key="b.id">
            <td class="mono">{{ b.batch_no }}</td>
            <td>{{ b.subject_title }}</td>
            <td class="mono">{{ b.seed }}</td>
            <td>{{ b.rate }}</td>
            <td>{{ b.source_count }}</td>
            <td>{{ b.sample_count }}</td>
            <td><span class="tag">{{ { ready: '就绪' }[b.status] || b.status }}</span></td>
            <td class="mono">{{ b.created_at }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
