<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import DataStreamPanel from './components/DataStreamPanel.vue'
import LatencyEventsPanel from './components/LatencyEventsPanel.vue'

const BLOCKS = [
  { id: 'rokoko_receiver', title: 'Rokoko 接收', kind: '业务节点', description: '接收手套 UDP 数据' },
  { id: 'hand_retargeting', title: '手部重定向', kind: '业务节点', description: '人体动作 → 软目标' },
  { id: 'omnihand_o10_control', title: 'O10 控制', kind: '业务节点', description: '安全复核与最终命令' },
  { id: 'hcan_provider', title: 'HCAN 真机 Provider', kind: '业务节点', description: '连接真实 OmniHand' },
  { id: 'sim_provider', title: 'Sim Provider', kind: '工具', description: '软件反馈替身' },
  { id: 'synthetic_input', title: '合成输入源', kind: '工具', description: '确定性假帧 UDP' },
  { id: 'recorder', title: '录制器', kind: '工具', description: '保存本次 run 证据' },
]
const TEMPLATES = {
  real: { label: '真机', blocks: ['rokoko_receiver', 'hand_retargeting', 'omnihand_o10_control', 'hcan_provider'] },
  data: { label: '数据链路', blocks: ['rokoko_receiver', 'hand_retargeting'] },
  sim: { label: '全链路 sim', blocks: ['rokoko_receiver', 'hand_retargeting', 'omnihand_o10_control', 'sim_provider'] },
}

const state = ref({ config: { blocks: [], side: 'both', profile: 'default', label: '' }, nodes: {}, validation: { errors: [], warnings: [], confirmations: [] }, events: [] })
const draft = ref({ blocks: [], side: 'both', profile: 'default', label: '', udp_port: 9000, actor: 0, can_channel: 'can0' })
const running = ref(false)
const busy = ref(false)
const notice = ref('')
const modal = ref(null)
const runs = ref([])
let socket
let pollTimer

const selectedBlocks = computed(() => draft.value.blocks)
const validation = computed(() => state.value.validation || { errors: [], warnings: [], confirmations: [] })
const hasErrors = computed(() => validation.value.errors?.length > 0)
const hasDanger = computed(() => validation.value.confirmations?.length > 0)
const allExpected = computed(() => BLOCKS.some(({ id }) => state.value.nodes?.[id]?.expected))

function applySnapshot(snapshot) {
  state.value = snapshot
  const config = snapshot.config || draft.value
  draft.value = { ...draft.value, ...config, blocks: [...(config.blocks || [])] }
  running.value = Object.values(snapshot.nodes || {}).some((node) => node.actual === 'stopping' || node.actual === 'starting' || node.actual === 'running' || node.actual === 'crashed' || (node.pid && node.actual !== 'cleanup_failed'))
}

async function api(path, options = {}) {
  const response = await fetch(path, { headers: { 'Content-Type': 'application/json' }, ...options })
  const body = await response.json()
  if (!response.ok) throw new Error(body.detail || body.message || `请求失败（${response.status}）`)
  return body
}

async function refresh() {
  try { applySnapshot(await api('/api/state')) } catch (error) { notice.value = error.message }
}

async function validate() {
  try { state.value.validation = await api('/api/validate', { method: 'POST', body: JSON.stringify({ blocks: draft.value.blocks, confirmation: false }) }) } catch (error) { notice.value = error.message }
}

function chooseTemplate(name) {
  draft.value.blocks = [...TEMPLATES[name].blocks]
  draft.value.template = name
  notice.value = `已预点亮「${TEMPLATES[name].label}」模板，可继续自由增删方块。`
  validate()
}

function formatBytes(value) {
  if (!value) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB']
  let size = value
  let index = 0
  while (size >= 1024 && index < units.length - 1) { size /= 1024; index += 1 }
  return `${size.toFixed(index ? 1 : 0)} ${units[index]}`
}

function formatRunTime(value) {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString()
}

async function refreshRuns() {
  try { runs.value = (await api('/api/runs')).runs || [] } catch (error) { notice.value = error.message }
}

function askDeleteRun(run) { modal.value = { type: 'delete-run', run } }

async function confirmDeleteRun() {
  const run = modal.value.run
  modal.value = null
  busy.value = true
  try {
    await api(`/api/runs/${encodeURIComponent(run.id)}`, { method: 'DELETE' })
    notice.value = `已删除 run「${run.id}」。`
    await refreshRuns()
  } catch (error) { notice.value = error.message } finally { busy.value = false }
}

async function toggleBlock(block) {
  if (running.value) {
    const node = state.value.nodes?.[block.id]
    await nodeAction(block.id, node?.expected ? 'stop' : 'start')
    return
  }
  draft.value.template = 'custom'
  const index = draft.value.blocks.indexOf(block.id)
  if (index >= 0) draft.value.blocks.splice(index, 1)
  else draft.value.blocks.push(block.id)
  await validate()
}

async function saveConfig(confirmation = false) {
  busy.value = true
  try {
    const result = await api('/api/config', { method: 'POST', body: JSON.stringify({ ...draft.value, confirmation }) })
    applySnapshot(result)
    notice.value = '配置已保存。'
    return true
  } catch (error) { notice.value = error.message; return false } finally { busy.value = false }
}

async function prepareAnd(action) {
  await validate()
  if (hasErrors.value) { notice.value = '存在硬阻止规则，请先修正方块组合。'; return }
  if (hasDanger.value) { modal.value = { type: 'danger', action }; return }
  await saveConfig(false)
  if (action === 'start') await run('/api/start', '已发出全启动请求。')
}

async function confirmDanger() {
  const action = modal.value.action
  modal.value = null
  if (!await saveConfig(true)) return
  if (action === 'start') await run('/api/start', '已确认并发出全启动请求。')
}

async function run(path, message) {
  busy.value = true
  try { applySnapshot(await api(path, { method: 'POST' })); notice.value = message } catch (error) { notice.value = error.message } finally { busy.value = false }
}

async function nodeAction(id, action) {
  if (action === 'stop' && state.value.nodes?.[id]?.expected) {
    const impact = state.value.nodes[id]
    if (impact?.downstream_impact?.length) { /* API carries impact; confirmation is shown after response. */ }
  }
  busy.value = true
  try {
    const result = await api(`/api/nodes/${id}/${action}`, { method: 'POST' })
    if (action === 'stop' && result.downstream_impact?.length) modal.value = { type: 'impact', node: id, impacts: result.downstream_impact }
    await refresh()
  } catch (error) { notice.value = error.message } finally { busy.value = false }
}

function statusFor(id) {
  const node = state.value.nodes?.[id] || {}
  if (node.actual === 'cleanup_failed') return 'dead'
  if (node.expected && ['crashed', 'stopped'].includes(node.actual)) return 'dead'
  if (node.actual === 'running') return 'ready'
  if (['starting', 'stopping'].includes(node.actual)) return 'alive'
  return 'off'
}

function statusText(id) {
  const node = state.value.nodes?.[id] || {}
  if (node.actual === 'cleanup_failed') return node.alert || '清理失败'
  if (statusFor(id) === 'dead') return node.alert || '进程已退出，未自动拉起'
  return { ready: '运行中', alive: node.actual === 'stopping' ? '停止中' : '启动中', off: '已停止' }[statusFor(id)] || '未启动'
}

async function preflight() {
  try {
    const result = await api('/api/preflight', { method: 'POST', body: JSON.stringify({ blocks: draft.value.blocks, side: draft.value.side }) })
    notice.value = result.passed ? '预检通过：已按当前方块集检查必要条件。' : '预检未通过，请检查下方提示。'
  } catch (error) { notice.value = error.message }
}

onMounted(() => {
  refresh()
  refreshRuns()
  pollTimer = window.setInterval(refresh, 2500)
  try {
    socket = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws`)
    socket.onmessage = (event) => applySnapshot(JSON.parse(event.data))
  } catch { /* HTTP 轮询仍可工作 */ }
})
onUnmounted(() => { window.clearInterval(pollTimer); socket?.close() })
</script>

<template>
  <main class="page-shell">
    <header class="topbar">
      <div><p class="eyebrow">ROKOKO · OMNIHAND O10</p><h1>Launchpad 控制面</h1><p class="lede">一张方块网格管理一次遥操作会话</p></div>
      <div class="connection"><span class="status-dot"></span>控制面在线 <small>本机 · 端口 8710</small></div>
    </header>

    <section class="panel templates-panel">
      <div class="section-heading"><div><span class="section-kicker">01 / 快速开始</span><h2>选择启动模板</h2></div><span class="mode-chip">{{ running ? '运行中 · 点击方块启停' : '配置中 · 点击方块增删' }}</span></div>
      <div class="template-buttons"><button v-for="(template, name) in TEMPLATES" :key="name" class="template-button" :class="{ active: template.blocks.every((id) => draft.blocks.includes(id)) && draft.blocks.length === template.blocks.length }" @click="chooseTemplate(name)"><strong>{{ template.label }}</strong><span>{{ template.blocks.length }} 个方块</span></button></div>
    </section>

    <section class="panel config-panel">
      <div class="section-heading"><div><span class="section-kicker">02 / 方块网格</span><h2>期望状态与实际状态</h2></div><div class="legend"><span><i class="legend-dot expected"></i>期望亮</span><span><i class="legend-dot actual"></i>实际运行</span><span><i class="legend-dot danger"></i>异常</span></div></div>
      <div class="block-grid">
        <button v-for="block in BLOCKS" :key="block.id" class="block" :class="[`kind-${block.kind === '工具' ? 'tool' : 'business'}`, { selected: draft.blocks.includes(block.id), flashing: statusFor(block.id) === 'dead' }]" :aria-pressed="draft.blocks.includes(block.id)" @click="toggleBlock(block)">
          <span class="block-top"><span class="block-icon">{{ block.kind === '工具' ? '◇' : '◆' }}</span><span class="kind-label">{{ block.kind }}</span><span class="state-light" :class="statusFor(block.id)"></span></span>
          <strong>{{ block.title }}</strong><small>{{ block.description }}</small><span class="block-status">{{ statusText(block.id) }}</span>
        </button>
      </div>
      <p class="helper">方块亮起代表“期望运行”。启动后，点击方块会调用现有 API 启动或停止该进程；期望亮但进程死亡时会红闪，且不会自动拉起。</p>
    </section>

    <section class="two-column">
      <div class="panel settings-panel"><div class="section-heading"><div><span class="section-kicker">03 / 会话配置</span><h2>侧别与关键参数</h2></div></div>
        <div class="form-grid"><label>侧别<select v-model="draft.side"><option value="both">双侧</option><option value="left">仅左</option><option value="right">仅右</option></select></label><label>参数档案<select v-model="draft.profile"><option value="default">默认真机基线</option><option value="diagnostic">诊断档案</option></select></label><label>UDP 端口<input v-model.number="draft.udp_port" type="number" min="1" max="65535" /></label><label>Actor 序号<input v-model.number="draft.actor" type="number" min="0" /></label><label>CAN 通道<input v-model="draft.can_channel" /></label><label>本次 Label<input v-model="draft.label" placeholder="例如：左手握持测试" /></label></div>
        <p class="muted">仅暴露常用关键参数；完整业务调参仍由预设档案负责。</p>
      </div>
      <div class="panel action-panel"><div class="section-heading"><div><span class="section-kicker">04 / 控制</span><h2>会话操作</h2></div></div><button class="primary" :disabled="busy" @click="prepareAnd('start')">▶ {{ running ? '重新启动全部' : '启动选中方块' }}</button><div class="action-row"><button :disabled="busy || !running" @click="run('/api/stop', '已发出全停请求。')">■ 全停</button><button :disabled="busy || !running" @click="run('/api/restart', '已发出重启请求。')">↻ 重启</button><button :disabled="busy" @click="preflight">⌁ 运行预检</button></div><p class="safety-note">网页不提供 arm / disarm / clear_fault。真机授权仍须由操作者在终端显式完成。</p></div>
    </section>

    <section v-if="validation.errors?.length || validation.warnings?.length || validation.confirmations?.length" class="messages"><div v-for="item in validation.errors" :key="item" class="message hard"><strong>硬阻止</strong>{{ item }}</div><div v-for="item in validation.confirmations" :key="item" class="message danger"><strong>危险组合</strong>{{ item }} · 启动需要二次确认</div><div v-for="item in validation.warnings" :key="item" class="message warning"><strong>提示</strong>{{ item }}</div></section>
    <p v-if="notice" class="toast" role="status">{{ notice }}</p>
    <DataStreamPanel :stream="state.data_stream" :side="draft.side" />
    <LatencyEventsPanel :model="state.latency_events" :events="state.events" :side="draft.side" />
    <section class="panel history-panel"><div class="section-heading"><div><span class="section-kicker">05 / 历史</span><h2>Run 历史</h2></div><button class="refresh-button" @click="refreshRuns">↻ 刷新</button></div><p v-if="!runs.length" class="muted">暂无 run 目录。</p><div v-else class="run-list"><article v-for="run in runs" :key="run.id" class="run-card"><div class="run-heading"><div><strong>{{ formatRunTime(run.created_at) }}</strong><span class="run-id">{{ run.id }}</span></div><button class="delete-button" :disabled="busy" @click="askDeleteRun(run)">删除</button></div><div class="run-meta"><span>模板：{{ run.template || 'custom' }}</span><span>Label：{{ run.label || '—' }}</span><span>大小：{{ formatBytes(run.size_bytes) }}</span></div><div class="artifact-list"><span v-for="artifact in run.artifacts" :key="artifact.name" class="artifact-chip">{{ artifact.kind }} · {{ formatBytes(artifact.size_bytes) }}</span></div></article></div></section>
    <div v-if="modal" class="modal-backdrop"><div class="modal"><span class="modal-icon">{{ modal.type === 'danger' ? '!' : modal.type === 'delete-run' ? '×' : '↘' }}</span><h2>{{ modal.type === 'danger' ? '确认危险组合' : modal.type === 'delete-run' ? '确认删除 run' : '停止后的下游影响' }}</h2><p v-if="modal.type === 'danger'">合成输入源与 HCAN 真机 Provider 同时运行，确定性假帧可能驱动真实硬件。请确认这是有意的诊断操作。</p><p v-else-if="modal.type === 'delete-run'">将永久删除「{{ modal.run.id }}」及其中的 metadata、events、sysmon、日志和 MCAP 产物。此操作不可恢复，且不会自动清理其他 run。</p><p v-else>停止「{{ modal.node }}」后，以下下游节点仍期望运行，可能进入超时或无输入状态：</p><ul v-if="modal.type === 'impact'"><li v-for="item in modal.impacts" :key="item">{{ item }}</li></ul><div class="modal-actions"><button @click="modal = null">取消</button><button v-if="modal.type === 'danger'" class="danger-button" @click="confirmDanger">确认继续</button><button v-else-if="modal.type === 'delete-run'" class="danger-button" @click="confirmDeleteRun">确认删除</button><button v-else class="primary" @click="modal = null">知道了</button></div></div></div>
  </main>
</template>
