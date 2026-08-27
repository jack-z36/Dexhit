<script setup>
import { computed } from 'vue'

const props = defineProps({
  stream: { type: Object, default: () => ({ sides: {} }) },
  side: { type: String, default: 'both' },
})

const FINGERS = ['拇指', '食指', '中指', '无名指', '小指']
const PHASES = {
  0: '初始化', 1: '采集指长', 2: '等待首个有效 IK', 3: '跟踪',
  4: '输入过期', 5: '恢复确认', 6: '恢复中', 7: '模型错误',
}
const IK = { 0: '未初始化', 1: '有效', 2: '输入无效', 3: '手侧无效', 4: '残差超限', 5: '求解器错误', 6: '未运行', 7: '输入过期' }

const visibleSides = computed(() => props.side === 'both' ? ['left', 'right'] : [props.side])
function dataFor(side) { return props.stream?.sides?.[side] || { joints: {}, states: [], latest: {} } }
function points(side, kind, name) {
  return (dataFor(side).joints?.[kind] || []).map(point => point.values?.[name]).filter(value => value !== null && value !== undefined)
}
function path(values) {
  if (!values.length) return ''
  const min = Math.min(...values); const max = Math.max(...values); const span = max - min || 1
  return values.map((value, index) => `${(index / Math.max(1, values.length - 1)) * 100},${100 - ((value - min) / span) * 90}`).join(' ')
}
function latestState(side) { const states = dataFor(side).states || []; return states[states.length - 1] || {} }
function statusClass(value) { return ['unknown', 'valid', 'bad', 'bad', 'bad', 'bad', 'unknown', 'unknown'][value] || 'unknown' }
</script>

<template>
  <section class="panel stream-panel">
    <div class="section-heading"><div><span class="section-kicker">06 / 数据流</span><h2>关节曲线与 IK 状态</h2></div><span class="mode-chip">约 {{ stream.sample_hz || 10 }} Hz 下采样</span></div>
    <div class="stream-sides">
      <article v-for="hand in visibleSides" :key="hand" class="stream-side">
        <div class="stream-side-heading"><h3>{{ hand === 'left' ? '左手' : '右手' }}</h3><span>10 个主动关节</span></div>
        <div class="stream-grid">
          <div class="stream-card"><strong>10 个主动关节：目标 / 反馈 / 限幅命令</strong><div class="chart" role="img" :aria-label="`${hand} 关节时间序列`"><svg viewBox="0 0 100 100" preserveAspectRatio="none"><template v-for="(name, index) in (dataFor(hand).joint_names || [])" :key="name"><polyline class="line target" :points="path(points(hand, 'target', name))" :style="{ opacity: 0.25 + index * 0.06 }" /><polyline class="line feedback" :points="path(points(hand, 'feedback', name))" :style="{ opacity: 0.25 + index * 0.06 }" /><polyline class="line command" :points="path(points(hand, 'joint_cmd', name))" :style="{ opacity: 0.25 + index * 0.06 }" /></template></svg></div><div class="chart-legend"><span class="target-dot">目标</span><span class="feedback-dot">反馈</span><span class="command-dot">限幅命令</span></div></div>
          <div class="stream-card"><div class="phase-row"><strong>phase 时间线</strong><span>{{ PHASES[latestState(hand).phase] || '无数据' }}</span></div><div class="phase-strip"><span v-for="(state, index) in (dataFor(hand).states || [])" :key="`${state.t}-${index}`" :class="`phase-${state.phase}`" :title="PHASES[state.phase] || state.phase"></span></div><strong>五指 IK 状态</strong><div class="ik-strip"><span v-for="(value, index) in (latestState(hand).ik_state || [])" :key="index" :class="statusClass(value)" :title="`${FINGERS[index]}：${IK[value] || value}`">{{ FINGERS[index] }}<small>{{ IK[value] || '—' }}</small></span></div><strong class="residual-title">归一化残差</strong><div class="residuals"><span v-for="(value, index) in (latestState(hand).normalized_residual || [])" :key="index" :class="statusClass(latestState(hand).ik_state?.[index])"><b>{{ FINGERS[index] }}</b>{{ value == null ? '—' : Number(value).toFixed(3) }}</span></div></div>
        </div>
        <p class="stream-note" v-if="!dataFor(hand).states?.length">尚未收到真实 RetargetingState；面板不会填充装饰数据。</p>
      </article>
    </div>
  </section>
</template>
