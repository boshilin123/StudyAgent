<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { isAxiosError } from 'axios'
import { apiErrorMessage, listKnowledgeBases } from '@/api'
import {
  archiveTutorConversation, createTutorConversation, getTutorConversation, getTutorTurn,
  listTutorConversations, sendTutorMessage,
} from '@/api/tutoring'
import type {
  TutorConversation, TutorInput, TutorIntent, TutorMessage, TutorResponse,
} from '@/api/tutoring'
import type { ApiErrorBody, KnowledgeBase } from '@/api/types'
import CitationPanel from '@/components/tutor/CitationPanel.vue'

const ACTIVE_KEY = 'study-agent-tutor-conversation'
const PENDING_KEY = 'study-agent-tutor-pending-message'
type Pending = TutorInput & { conversation_id: string; turn_id?: string }
const route = useRoute()
const bases = ref<KnowledgeBase[]>([])
const knowledgeBaseId = ref('')
const conversations = ref<TutorConversation[]>([])
const conversation = ref<TutorConversation | null>(null)
const messages = ref<TutorMessage[]>([])
const messagePage = ref(1)
const totalMessages = ref(0)
const conversationPage = ref(1)
const totalConversations = ref(0)
const content = ref('')
const intent = ref<TutorIntent>('materials')
const loading = ref(false)
const busy = ref(false)
const notice = ref('')
const lastResponse = ref<TutorResponse | null>(null)
const failedInput = ref<TutorInput | null>(null)
const pending = ref<Pending | null>(readPending())
let timer: ReturnType<typeof setTimeout> | null = null
let disposed = false
const hasAnchor = computed(() => !!conversation.value?.answered_question_id)
const boundBaseName = computed(() => bases.value.find(
  base => base.id === conversation.value?.knowledge_base_id,
)?.name || '当前知识库')
const canSend = computed(() => !!conversation.value && conversation.value.status === 'active'
  && !busy.value && !pending.value && !!content.value.trim())
const anchorQuery = () => ({
  study_session_id: typeof route.query.study_session_id === 'string' ? route.query.study_session_id : undefined,
  answered_question_id: typeof route.query.answered_question_id === 'string' ? route.query.answered_question_id : undefined,
})

function readPending(): Pending | null {
  try {
    const value = JSON.parse(localStorage.getItem(PENDING_KEY) || 'null') as Pending | null
    return value?.conversation_id && value.client_message_id && typeof value.content === 'string'
      ? value : null
  } catch { localStorage.removeItem(PENDING_KEY); return null }
}
function savePending(value: Pending | null) {
  pending.value = value
  if (value) localStorage.setItem(PENDING_KEY, JSON.stringify(value))
  else localStorage.removeItem(PENDING_KEY)
}
function stopPolling() { if (timer) clearTimeout(timer); timer = null }

async function loadList() {
  if (!knowledgeBaseId.value) return
  try {
    const result = await listTutorConversations(knowledgeBaseId.value, conversationPage.value)
    conversations.value = result.items
    totalConversations.value = result.total
  } catch (error) { notice.value = apiErrorMessage(error) }
}
async function selectBase() {
  conversationPage.value = 1
  conversation.value = null
  messages.value = []
  totalMessages.value = 0
  lastResponse.value = null
  failedInput.value = null
  localStorage.removeItem(ACTIVE_KEY)
  await loadList()
}
async function refreshMessages() {
  if (!conversation.value) return
  const detail = await getTutorConversation(conversation.value.id, messagePage.value)
  conversation.value = detail.conversation
  messages.value = [...detail.messages].sort((a, b) => a.sequence - b.sequence)
  totalMessages.value = detail.total
}
async function selectConversation(id: string) {
  if (busy.value || (pending.value && pending.value.conversation_id !== id)) return
  loading.value = true
  notice.value = ''
  try {
    const detail = await getTutorConversation(id)
    conversation.value = detail.conversation
    knowledgeBaseId.value = detail.conversation.knowledge_base_id
    messages.value = [...detail.messages].sort((a, b) => a.sequence - b.sequence)
    totalMessages.value = detail.total
    messagePage.value = 1
    if (detail.total > 50) {
      messagePage.value = Math.ceil(detail.total / 50)
      await refreshMessages()
    }
    lastResponse.value = null
    failedInput.value = null
    intent.value = detail.conversation.answered_question_id ? 'answered_question' : 'materials'
    localStorage.setItem(ACTIVE_KEY, id)
    await loadList()
  } catch (error) { notice.value = apiErrorMessage(error) }
  finally { loading.value = false }
}
async function createConversation() {
  if (!knowledgeBaseId.value || pending.value || busy.value) return
  loading.value = true
  notice.value = ''
  try {
    const created = await createTutorConversation({ knowledge_base_id: knowledgeBaseId.value, ...anchorQuery() })
    conversation.value = created
    messages.value = []
    totalMessages.value = 0
    messagePage.value = 1
    lastResponse.value = null
    failedInput.value = null
    intent.value = created.answered_question_id ? 'answered_question' : 'materials'
    localStorage.setItem(ACTIVE_KEY, created.id)
    await loadList()
  } catch (error) { notice.value = apiErrorMessage(error) }
  finally { loading.value = false }
}
async function acceptResponse(response: TutorResponse) {
  lastResponse.value = response
  if (response.status === 'pending' || response.status === 'running') {
    if (pending.value) savePending({ ...pending.value, turn_id: response.turn_id })
    notice.value = '正在分析或检索，可刷新页面后继续查看。'
    schedulePoll()
    return
  }
  if (response.status === 'failed' || response.status === 'cancelled') {
    failedInput.value = pending.value ? {
      client_message_id: pending.value.client_message_id, content: pending.value.content,
      intent: pending.value.intent,
    } : null
    notice.value = response.error_message || '本次辅导未完成，可明确重新尝试。'
  } else {
    failedInput.value = null
    notice.value = response.answer_status === 'insufficient_evidence' ? '当前资料依据不足。' : ''
    content.value = ''
  }
  savePending(null)
  busy.value = false
  stopPolling()
  await refreshMessages()
  const latestPage = Math.max(1, Math.ceil(totalMessages.value / 50))
  if (messagePage.value !== latestPage) {
    messagePage.value = latestPage
    await refreshMessages()
  }
}
function schedulePoll() {
  stopPolling()
  if (!disposed) timer = setTimeout(() => { void checkPending() }, 2000)
}
async function checkPending() {
  const item = pending.value
  if (!item?.turn_id || disposed) return
  try {
    const turn = await getTutorTurn(item.conversation_id, item.turn_id)
    if (turn.response) await acceptResponse(turn.response)
    else if (turn.status === 'failed' || turn.status === 'cancelled') {
      failedInput.value = { client_message_id: item.client_message_id, content: item.content, intent: item.intent }
      notice.value = turn.error_message || '本次辅导未完成，可重新尝试。'
      savePending(null)
      busy.value = false
      await refreshMessages()
    } else schedulePoll()
  } catch (error) {
    notice.value = `暂时无法查询结果：${apiErrorMessage(error)}。可点击恢复待确认消息。`
    busy.value = false
    stopPolling()
  }
}
async function transmit(item: Pending) {
  busy.value = true
  notice.value = '正在分析或检索…'
  savePending(item)
  try {
    const response = await sendTutorMessage(item.conversation_id, {
      client_message_id: item.client_message_id, content: item.content, intent: item.intent,
    })
    await acceptResponse(response)
  } catch (error) {
    const code = isAxiosError(error) ? error.response?.status : undefined
    const errorCode = isAxiosError<ApiErrorBody>(error) ? error.response?.data.error?.code : undefined
    if (code && [400, 401, 404, 409, 422].includes(code)
      && errorCode !== 'TUTOR_THREAD_BUSY') savePending(null)
    notice.value = apiErrorMessage(error)
    busy.value = false
    // A timeout or server error can follow a committed result: retain its ID.
  }
}
async function send() {
  if (!canSend.value || !conversation.value) return
  failedInput.value = null
  await transmit({ conversation_id: conversation.value.id, client_message_id: crypto.randomUUID(),
    content: content.value.trim(), intent: intent.value })
}
async function recover() {
  if (!pending.value || busy.value) return
  if (pending.value.turn_id) { busy.value = true; await checkPending() }
  else await transmit(pending.value)
}
async function retryFailed() {
  if (!failedInput.value || !conversation.value || busy.value || pending.value) return
  const input = failedInput.value
  failedInput.value = null
  await transmit({ ...input, conversation_id: conversation.value.id, client_message_id: crypto.randomUUID() })
}
async function archive() {
  if (!conversation.value || busy.value || pending.value) return
  loading.value = true
  try {
    conversation.value = await archiveTutorConversation(conversation.value.id)
    notice.value = '会话已归档，历史仍可查看。请新建会话继续辅导。'
    await loadList()
  } catch (error) { notice.value = apiErrorMessage(error) }
  finally { loading.value = false }
}
async function changeMessagePage() {
  try { await refreshMessages() } catch (error) { notice.value = apiErrorMessage(error) }
}

onMounted(async () => {
  loading.value = true
  try {
    bases.value = (await listKnowledgeBases({ status: 'active', page_size: 100 })).items
    knowledgeBaseId.value = typeof route.query.knowledge_base_id === 'string'
      ? route.query.knowledge_base_id : bases.value[0]?.id || ''
    if (pending.value) {
      await selectConversation(pending.value.conversation_id)
      await recover()
    } else if (!anchorQuery().answered_question_id && localStorage.getItem(ACTIVE_KEY)) {
      await selectConversation(localStorage.getItem(ACTIVE_KEY)!)
    } else await loadList()
  } catch (error) { notice.value = apiErrorMessage(error) }
  finally { loading.value = false }
})
onUnmounted(() => { disposed = true; stopPolling() })
</script>

<template>
  <div v-loading="loading" class="tutor-layout">
    <aside class="tutor-sidebar">
      <h2>学习辅导</h2>
      <el-select v-model="knowledgeBaseId" aria-label="辅导知识库" placeholder="选择知识库"
        :disabled="busy || !!pending" @change="selectBase">
        <el-option v-for="base in bases" :key="base.id" :label="base.name" :value="base.id" />
      </el-select>
      <p v-if="anchorQuery().answered_question_id" class="muted-text">新会话将绑定刚才已作答的题目。</p>
      <el-button type="primary" :disabled="!knowledgeBaseId || busy || !!pending" @click="createConversation">新建辅导会话</el-button>
      <nav aria-label="辅导会话">
        <button v-for="item in conversations" :key="item.id" type="button"
          :class="{ selected: conversation?.id === item.id }" :disabled="busy || !!pending"
          @click="selectConversation(item.id)">
          {{ item.answered_question_id ? '答后追问' : '资料辅导' }} · {{ new Date(item.created_at).toLocaleString('zh-CN') }}
          <small>{{ item.status === 'archived' ? '已归档' : '可继续' }}</small>
        </button>
      </nav>
      <el-pagination v-if="totalConversations > 20" v-model:current-page="conversationPage"
        :total="totalConversations" :page-size="20" layout="prev, next" @current-change="loadList" />
    </aside>
    <section class="tutor-chat">
      <div class="tutor-heading">
        <div><h2>{{ hasAnchor ? '围绕刚才的作答继续请教' : '结合资料和学习记录提问' }}</h2>
          <p v-if="conversation" class="muted-text">会话范围：{{ boundBaseName }}</p>
          <p class="muted-text">辅导建议供你参考。成绩、掌握度和复习计划由学习流程保存。</p></div>
        <el-button v-if="conversation?.status === 'active'" :disabled="busy || !!pending" @click="archive">归档会话</el-button>
      </div>
      <el-alert v-if="notice" :title="notice" :closable="false" type="info" show-icon />
      <div v-if="!conversation" class="tutor-intro">选择知识库并新建会话，即可提问。问题及必要的资料片段会发送给配置的模型服务。</div>
      <div v-else class="tutor-messages" aria-live="polite">
        <article v-for="message in messages" :key="message.id" :class="['tutor-message', message.role]">
          <strong>{{ message.role === 'user' ? '你' : '学习辅导助手' }}</strong>
          <p>{{ message.content }}</p>
          <CitationPanel :citations="message.citations || []" />
        </article>
        <p v-if="conversation && !messages.length" class="muted-text">可以问资料中的概念，也可以分析近期错题。</p>
      </div>
      <el-pagination v-if="totalMessages > 50" v-model:current-page="messagePage" :total="totalMessages"
        :page-size="50" layout="prev, pager, next" @current-change="changeMessagePage" />
      <div v-if="lastResponse?.suggestions.length" class="tutor-suggestions">
        <strong>复习建议</strong><ul><li v-for="suggestion in lastResponse.suggestions" :key="suggestion">{{ suggestion }}</li></ul>
      </div>
      <div v-if="lastResponse?.suggested_questions.length" class="tutor-followups">
        <el-button v-for="question in lastResponse.suggested_questions" :key="question" text
          :disabled="busy || !!pending" @click="content = question">{{ question }}</el-button>
      </div>
      <small v-if="lastResponse" class="muted-text">模型调用 {{ lastResponse.usage.model_calls ?? '不可用' }} 次 · 工具调用 {{ lastResponse.usage.tool_calls ?? '不可用' }} 次 ·
        Token {{ lastResponse.usage.known ? lastResponse.usage.total_tokens : '用量不可用' }}</small>
      <div v-if="pending" class="tutor-recovery">
        <p>待确认问题：{{ pending.content }}</p>
        <el-button :disabled="busy" @click="recover">恢复待确认消息</el-button>
      </div>
      <el-button v-if="failedInput" :disabled="busy || !!pending" @click="retryFailed">重新尝试本次问题</el-button>
      <form v-if="conversation?.status === 'active'" class="tutor-compose" @submit.prevent="send">
        <el-select v-model="intent" aria-label="辅导问题类型" :disabled="busy || !!pending">
          <el-option label="资料问答" value="materials" />
          <el-option v-if="hasAnchor" label="答后追问" value="answered_question" />
          <el-option label="学习进度与复习建议" value="progress" />
          <el-option label="近期错题分析" value="mistakes" />
          <el-option label="其他问题" value="general" />
        </el-select>
        <el-input v-model="content" type="textarea" :rows="3" :maxlength="2000" show-word-limit
          aria-label="辅导问题" placeholder="例如：结合最近错题，解释我容易混淆的概念并给出资料依据。"
          :disabled="busy || !!pending" />
        <el-button native-type="submit" type="primary" :loading="busy" :disabled="!canSend">发送问题</el-button>
      </form>
    </section>
  </div>
</template>

<style scoped>
.tutor-layout { display: grid; grid-template-columns: 270px minmax(0, 1fr); gap: 24px; }
.tutor-sidebar, .tutor-chat { background: var(--el-bg-color); border: 1px solid var(--el-border-color-light); border-radius: 12px; padding: 24px; }
.tutor-sidebar { display: flex; flex-direction: column; gap: 16px; align-self: start; }
h2 { font-size: 18px; margin: 0; }
.tutor-sidebar nav { display: flex; flex-direction: column; gap: 8px; }
.tutor-sidebar nav button { text-align: left; border: 1px solid var(--el-border-color); background: var(--el-fill-color-blank); color: var(--el-text-color-primary); padding: 12px; border-radius: 6px; cursor: pointer; }
.tutor-sidebar nav button.selected { border-color: var(--el-color-primary); }
.tutor-sidebar small { display: block; margin-top: 6px; color: var(--el-text-color-secondary); }
.tutor-heading { display: flex; justify-content: space-between; align-items: start; gap: 16px; margin-bottom: 20px; }
.tutor-intro { padding: 48px 0; color: var(--el-text-color-secondary); }
.tutor-messages { display: flex; flex-direction: column; gap: 16px; margin: 20px 0; }
.tutor-message { padding: 16px; border: 1px solid var(--el-border-color-light); border-radius: 8px; }
.tutor-message.user { background: var(--el-fill-color-light); }
.tutor-message p { white-space: pre-wrap; overflow-wrap: anywhere; line-height: 1.8; margin-bottom: 0; }
.tutor-compose { display: grid; gap: 12px; margin-top: 24px; }
.tutor-compose .el-button { justify-self: end; }
.tutor-recovery, .tutor-suggestions { padding: 12px 0; line-height: 1.7; }
.tutor-followups { display: flex; flex-wrap: wrap; margin-bottom: 12px; }
@media (max-width: 1000px) { .tutor-layout { grid-template-columns: 1fr; } }
</style>
