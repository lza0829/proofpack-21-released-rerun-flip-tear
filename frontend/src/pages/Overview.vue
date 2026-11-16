<script setup>
import { onMounted, ref } from 'vue'
import { getJSON } from '../api'
const stats = ref(null)
const err = ref('')
onMounted(async () => {
  try { stats.value = await getJSON('/api/dashboard') } catch (e) { err.value = String(e.message || e) }
})
</script>
<template>
  <div class="page">
    <h1>总览</h1>
    <p class="muted">采样抽取 → 证据打包 → 校验清单 → 放行/驳回闭环。清单全过才可放行。</p>
    <p v-if="err" class="tag danger">{{ err }}</p>
    <div class="panel" v-if="stats">
      <div class="stat-grid">
        <div class="stat"><div class="stat-num">{{ stats.subject_count }}</div><div class="stat-label">举证对象</div></div>
        <div class="stat"><div class="stat-num">{{ stats.enabled_subjects }}</div><div class="stat-label">已启用</div></div>
        <div class="stat"><div class="stat-num">{{ stats.sample_batch_count }}</div><div class="stat-label">采样批次</div></div>
        <div class="stat"><div class="stat-num">{{ stats.pack_count }}</div><div class="stat-label">证据包</div></div>
        <div class="stat"><div class="stat-num">{{ stats.checklist_run_count }}</div><div class="stat-label">清单运行</div></div>
        <div class="stat"><div class="stat-num">{{ stats.passed_releases }}</div><div class="stat-label">已放行</div></div>
        <div class="stat"><div class="stat-num">{{ stats.rejected_releases }}</div><div class="stat-label">已驳回</div></div>
      </div>
      <p style="margin-top:1rem"><router-link to="/sample">去采样台跑一趟 →</router-link></p>
    </div>
  </div>
</template>
