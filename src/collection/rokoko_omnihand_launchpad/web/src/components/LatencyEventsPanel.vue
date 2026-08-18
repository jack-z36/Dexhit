<script setup>
import { computed } from 'vue'

const props = defineProps({
  model: { type: Object, default: () => ({ sides: {} }) },
  events: { type: Array, default: () => [] },
  side: { type: String, default: 'both' },
})
const labels = { source_timestamp: 'source', receive: 'receive', input: 'input', solve: 'solve', command: 'command', joint_cmd: 'joint_cmd', joint_states: 'joint_states' }
const topics = { raw_hand: 'raw_hand', retargeting_state: 'retargeting', command: 'command', control_state: 'O10 state', joint_cmd: 'joint_cmd', joint_states: 'joint_states' }
const visibleSides = computed(() => props.side === 'both' ? ['left', 'right'] : [props.side])
function dataFor(side) { return props.model?.sides?.[side] || { rates: {}, hops: [], fault: {} } }
function rate(side, name) { const value = dataFor(side).rates?.[name]?.frequency_hz; return value ? `${value.toFixed(1)} Hz` : '—' }
function latency(value) { return value == null ? '缺失' : `${Number(value).toFixed(1)} ms` }
function faultText(side) { const fault = dataFor(side).fault || {}; if (!fault.available) return '缺失'; return fault.fault_latched ? `FAULT · mask ${fault.fault_reason_mask ?? '—'}` : '无 fault' }
</script>

<template>
  <section class="panel latency-events-panel">
    <div class="section-heading"><div><span class="section-kicker">07 / 诊断</span><h2>频率、延迟与事件</h2></div><span class="mode-chip">约 10 Hz 更新 · 缺失不猜测</span></div>
    <div class="diagnostic-sides">
      <article v-for="hand in visibleSides" :key="hand" class="diagnostic-side">
        <div class="stream-side-heading"><h3>{{ hand === 'left' ? '左手' : '右手' }}</h3><strong :class="{ faulted: dataFor(hand).fault?.fault_latched }">{{ faultText(hand) }}</strong></div>
        <div class="rate-grid"><div v-for="(label, name) in topics" :key="name"><small>{{ label }}</small><b>{{ rate(hand, name) }}</b></div></div>
        <div class="hop-list"><div v-for="hop in dataFor(hand).hops" :key="`${hop.from}-${hop.to}`"><span>{{ labels[hop.from] }} → {{ labels[hop.to] }}</span><b :class="{ missing: !hop.available }">{{ latency(hop.latency_ms) }}</b></div></div>
      </article>
    </div>
    <div class="event-stream"><strong>实时事件流（T07 events.jsonl）</strong><p v-if="!events.length" class="muted">暂无事件或尚未建立 run。</p><ol v-else><li v-for="(event, index) in events.slice(-40)" :key="`${event.timestamp}-${index}`"><time>{{ event.timestamp || '—' }}</time><b>{{ event.type || 'event' }}</b><span>{{ event.label || event.message || event.node || '' }}</span></li></ol></div>
  </section>
</template>
