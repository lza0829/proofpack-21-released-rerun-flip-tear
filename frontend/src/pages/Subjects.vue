<script setup>
import { onMounted, ref } from 'vue'
import { getJSON } from '../api'

const DOMAIN = { store: '门店', channel: '渠道', price: '价目' }
const CODE = {
  store_dayend: '门店日结',
  channel_settle: '渠道结算',
  price_change: '价目变更',
}

const rows = ref([])
const err = ref('')
onMounted(async () => {
  try { rows.value = await getJSON('/api/subjects') } catch (e) { err.value = String(e.message || e) }
})
</script>
<template>
  <div class="page">
    <h1>举证对象</h1>
    <p class="muted">本地夹具对应的核证范围；选其一进入采样台。</p>
    <p v-if="err" class="tag danger">{{ err }}</p>
    <div class="panel">
      <table>
        <thead>
          <tr>
            <th>编号</th>
            <th>名称</th>
            <th>业务域</th>
            <th>数据来源</th>
            <th>默认采样率</th>
            <th>状态</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="r in rows" :key="r.id">
            <td>{{ CODE[r.code] || r.code }}</td>
            <td>{{ r.title }}</td>
            <td>{{ DOMAIN[r.domain] || r.domain }}</td>
            <td>本地夹具</td>
            <td>{{ r.sample_rate_default }}</td>
            <td><span class="tag" :class="r.enabled ? 'ok' : 'warn'">{{ r.enabled ? '启用' : '停用' }}</span></td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
