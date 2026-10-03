<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { isAxiosError } from 'axios'
import { apiErrorMessage, listKnowledgeBases } from '@/api'
import {
  archiveTutorConversation, createTutorConversation, getTutorConversation, getTutorTurn,
  listTutorConversations, sendTutorMessage,
  renameTutorConversation, deleteTutorConversation,
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
const renameTarget = ref<TutorConversation | null>(null)
const deleteTarget = ref<TutorConversation | null>(null)
const newTitle = ref('')
const managementBusy = ref(false)
const managementError = ref('')
const lastResponse = ref<TutorResponse | null>(null)
const failedInput = ref<TutorInput | null>(null)
const pending = ref<Pending | null>(readPending())
const messageViewport = ref<HTMLElement | null>(null)
const followLatest = ref(true)
const unreadReply = ref(false)
function onMessageScroll() {
  const viewport = messageViewport.value
  if (!viewport) return
  followLatest.value = viewport.scrollHeight - viewport.scrollTop - viewport.clientHeight < 64
  if (followLatest.value) unreadReply.value = false
}
async function positionMessages(position: 'latest' | 'start') {
  await nextTick()
  const viewport = messageViewport.value
  if (!viewport) return
  viewport.scrollTop = position === 'latest' ? viewport.scrollHeight : 0
  onMessageScroll()
  unreadReply.value = false
}
function onViewportResize() {
  if (followLatest.value) void positionMessages('latest')
}
let timer: ReturnType<typeof setTimeout> | null = null
let disposed = false
const hasAnchor = computed(() => !!conversation.value?.answered_question_id)
const boundBaseName = computed(() => bases.value.find(
  base => base.id === conversation.value?.knowledge_base_id,
)?.name || '当前知识库')
const canSend = computed(() => !!conversation.value && conversation.value.status === 'active'
  && !busy.value && !pending.value && !!content.value.trim())
const managementDisabled = computed(() => busy.value || !!pending.value || loading.value || managementBusy.value)
function conversationTitle(item: TutorConversation) {
  return item.title || `${item.answered_question_id ? '答后追问' : '资料辅导'} · ${new Date(item.created_at).toLocaleString('zh-CN')}`
}
function clearConversation() {
  conversation.value = null
  messages.value = []
  totalMessages.value = 0
  messagePage.value = 1
  lastResponse.value = null
  failedInput.value = null
  content.value = ''
  followLatest.value = true
  unreadReply.value = false
  localStorage.removeItem(ACTIVE_KEY)
}
function openRename(item: TutorConversation) {
  if (managementDisabled.value) return
  renameTarget.value = item
  newTitle.value = conversationTitle(item)
  managementError.value = ''
}
function openDelete(item: TutorConversation) {
  if (managementDisabled.value) return
  deleteTarget.value = item
  managementError.value = ''
}
async function confirmRename() {
  const item = renameTarget.value
  if (!item || !newTitle.value.trim() || managementDisabled.value) return
  managementBusy.value = true
  managementError.value = ''
  try {
    const updated = await renameTutorConversation(item.id, newTitle.value.trim())
    if (conversation.value?.id === item.id) conversation.value = updated
    conversations.value = conversations.value.map(row => row.id === item.id ? updated : row)
    renameTarget.value = null
    notice.value = '会话名称已更新。'
  } catch (error) { managementError.value = apiErrorMessage(error) }
  finally { managementBusy.value = false }
}
async function confirmDelete() {
  const item = deleteTarget.value
  if (!item || managementDisabled.value) return
  managementBusy.value = true
  managementError.value = ''
  try {
    await deleteTutorConversation(item.id)
    const wasSelected = conversation.value?.id === item.id
    if (wasSelected) clearConversation()
    else if (localStorage.getItem(ACTIVE_KEY) === item.id) localStorage.removeItem(ACTIVE_KEY)
    deleteTarget.value = null
    await loadList()
    const lastPage = Math.max(1, Math.ceil(totalConversations.value / 20))
    if (conversationPage.value > lastPage) {
      conversationPage.value = lastPage
      await loadList()
    }
    if (wasSelected && conversations.value[0]) await selectConversation(conversations.value[0].id)
    notice.value = '会话已删除。'
  } catch (error) { managementError.value = apiErrorMessage(error) }
  finally { managementBusy.value = false }
}
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
  followLatest.value = true
  unreadReply.value = false
  localStorage.removeItem(ACTIVE_KEY)
  await loadList()
}
async function refreshMessages(position: 'preserve' | 'latest' | 'start' = 'preserve') {
  if (!conversation.value) return
  const detail = await getTutorConversation(conversation.value.id, messagePage.value)
  const previousTop = messageViewport.value?.scrollTop || 0
  const shouldFollow = followLatest.value
  const previousLastId = messages.value.at(-1)?.id
  conversation.value = detail.conversation
  messages.value = [...detail.messages].sort((a, b) => a.sequence - b.sequence)
  totalMessages.value = detail.total
  await nextTick()
  if (position !== 'preserve') await positionMessages(position)
  else if (shouldFollow) await positionMessages('latest')
  else if (messageViewport.value) {
    messageViewport.value.scrollTop = previousTop
    if (previousLastId !== messages.value.at(-1)?.id) unreadReply.value = true
  }
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
    await positionMessages('latest')
  } catch (error) {
    notice.value = apiErrorMessage(error)
    if (isAxiosError(error) && error.response?.status === 404) {
      clearConversation()
      if (pending.value?.conversation_id === id) savePending(null)
      await loadList()
    }
  }
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
    await positionMessages('latest')
  } catch (error) { notice.value = apiErrorMessage(error) }
  finally { loading.value = false }
}
async function acceptResponse(response: TutorResponse) {
  // Capture before response controls resize the viewport and dispatch a layout scroll event.
  const shouldFollow = followLatest.value
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
  await refreshMessages(shouldFollow ? 'latest' : 'preserve')
  const latestPage = Math.max(1, Math.ceil(totalMessages.value / 50))
  if (messagePage.value !== latestPage) {
    messagePage.value = latestPage
    await refreshMessages('latest')
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
    if (isAxiosError(error) && error.response?.status === 404) {
      savePending(null)
      busy.value = false
      stopPolling()
      clearConversation()
      await loadList()
      notice.value = '辅导会话已不存在，请选择或新建会话。'
      return
    }
    notice.value = `暂时无法查询结果：${apiErrorMessage(error)}。可点击恢复待确认消息。`
    busy.value = false
    stopPolling()
  }
}
async function transmit(item: Pending) {
  busy.value = true
  notice.value = '正在分析或检索…'
  savePending(item)
  await positionMessages('latest')
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
  try { await refreshMessages('start') } catch (error) { notice.value = apiErrorMessage(error) }
}

onMounted(async () => {
  window.addEventListener('resize', onViewportResize)
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
onUnmounted(() => { disposed = true; stopPolling(); window.removeEventListener('resize', onViewportResize) })
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
        <div v-for="item in conversations" :key="item.id" class="conversation-item"
          :class="{ selected: conversation?.id === item.id }">
          <button type="button" class="conversation-select" :disabled="managementDisabled"
            @click="selectConversation(item.id)">
            {{ conversationTitle(item) }}
            <small>{{ item.status === 'archived' ? '已归档' : '可继续' }}</small>
          </button>
          <div class="conversation-actions">
            <el-button text size="small" :disabled="managementDisabled"
              :aria-label="`重命名会话 ${conversationTitle(item)}`" @click="openRename(item)">重命名</el-button>
            <el-button text type="danger" size="small" :disabled="managementDisabled"
              :aria-label="`删除会话 ${conversationTitle(item)}`" @click="openDelete(item)">删除</el-button>
          </div>
        </div>
      </nav>
      <p v-if="!conversations.length && !loading" class="muted-text">暂无辅导会话。</p>
      <el-pagination v-if="totalConversations > 20" v-model:current-page="conversationPage"
        :total="totalConversations" :page-size="20" layout="prev, next" @current-change="loadList" />
    </aside>
    <section class="tutor-chat">
      <div class="tutor-heading">
        <div><h2>{{ conversation?.title || (hasAnchor ? '围绕刚才的作答继续请教' : '结合资料和学习记录提问') }}</h2>
          <p v-if="conversation" class="muted-text">会话范围：{{ boundBaseName }}</p>
          <p class="muted-text">辅导建议供你参考。成绩、掌握度和复习计划由学习流程保存。</p></div>
        <el-button v-if="conversation?.status === 'active'" :disabled="busy || !!pending" @click="archive">归档会话</el-button>
      </div>
      <div ref="messageViewport" class="tutor-history" role="region" aria-label="辅导消息记录"
        tabindex="0" @scroll="onMessageScroll">
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
      </div>
      <el-button v-if="unreadReply" class="latest-reply" size="small" @click="positionMessages('latest')">查看最新回复</el-button>
      <div class="tutor-input-area">
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
        <el-input v-model="content" type="textarea" :rows="3" resize="none" :maxlength="2000" show-word-limit
          aria-label="辅导问题" placeholder="例如：结合最近错题，解释我容易混淆的概念并给出资料依据。"
          :disabled="busy || !!pending" />
        <el-button native-type="submit" type="primary" :loading="busy" :disabled="!canSend">发送问题</el-button>
      </form>
      </div>
    </section>
    <el-dialog :model-value="!!renameTarget" title="重命名会话" width="min(420px, 90vw)"
      :close-on-click-modal="!managementBusy" :close-on-press-escape="!managementBusy" :show-close="!managementBusy"
      @update:model-value="value => { if (!value) renameTarget = null }">
      <el-input v-model="newTitle" aria-label="会话名称" maxlength="100" show-word-limit
        :disabled="managementBusy" @keyup.enter="confirmRename" />
      <el-alert v-if="managementError" :title="managementError" type="error" :closable="false" />
      <template #footer>
        <el-button :disabled="managementBusy" @click="renameTarget = null">取消</el-button>
        <el-button type="primary" :loading="managementBusy" :disabled="!newTitle.trim()" @click="confirmRename">保存名称</el-button>
      </template>
    </el-dialog>
    <el-dialog :model-value="!!deleteTarget" title="删除辅导会话" width="min(420px, 90vw)"
      :close-on-click-modal="!managementBusy" :close-on-press-escape="!managementBusy" :show-close="!managementBusy"
      @update:model-value="value => { if (!value) deleteTarget = null }">
      <p>确定删除「{{ deleteTarget ? conversationTitle(deleteTarget) : '' }}」吗？</p>
      <p class="muted-text">删除后会话将从列表隐藏，无法继续查看或提问。知识库、题目和学习记录不受影响。</p>
      <el-alert v-if="managementError" :title="managementError" type="error" :closable="false" />
      <template #footer>
        <el-button :disabled="managementBusy" @click="deleteTarget = null">取消</el-button>
        <el-button type="danger" :loading="managementBusy" @click="confirmDelete">确认删除</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.tutor-layout { flex: 1; min-height: 0; display: grid; grid-template-columns: 270px minmax(0, 1fr); gap: 24px; }
.tutor-sidebar, .tutor-chat { background: var(--el-bg-color); border: 1px solid var(--el-border-color-light); border-radius: 12px; padding: 24px; }
.tutor-sidebar { display: flex; flex-direction: column; gap: 16px; min-height: 0; overflow: hidden; }
.tutor-sidebar > :not(nav) { flex-shrink: 0; }
.tutor-chat { display: flex; flex-direction: column; min-height: 0; min-width: 0; overflow: hidden; }
h2 { font-size: 18px; margin: 0; }
.tutor-sidebar nav { flex: 1; min-height: 0; overflow-y: auto; overscroll-behavior: contain; display: flex; flex-direction: column; gap: 8px; }
.conversation-item { flex-shrink: 0; border: 1px solid var(--el-border-color); border-radius: 6px; overflow: hidden; }
.conversation-item.selected { border-color: var(--el-color-primary); }
.conversation-select { display: block; width: 100%; text-align: left; border: 0; background: var(--el-fill-color-blank); color: var(--el-text-color-primary); padding: 12px; cursor: pointer; overflow-wrap: anywhere; }
.conversation-select:disabled { cursor: default; }
.conversation-actions { display: flex; justify-content: flex-end; padding: 0 8px 6px; }
.conversation-actions .el-button + .el-button { margin-left: 0; }
.tutor-sidebar small { display: block; margin-top: 6px; color: var(--el-text-color-secondary); }
.tutor-heading { flex-shrink: 0; display: flex; justify-content: space-between; align-items: start; gap: 16px; margin-bottom: 16px; }
.tutor-heading > div { min-width: 0; overflow-wrap: anywhere; }
.tutor-heading > .el-button { flex-shrink: 0; }
.tutor-history { flex: 1; min-height: 0; overflow-y: auto; overflow-x: hidden; overscroll-behavior: contain; scrollbar-gutter: stable; padding-right: 6px; margin-right: -6px; }
.tutor-input-area { flex-shrink: 0; padding-top: 12px; border-top: 1px solid var(--el-border-color-light); }
.tutor-input-area:empty { display: none; }
.latest-reply { align-self: center; flex-shrink: 0; margin: 8px 0; }
.tutor-intro { padding: 48px 0; color: var(--el-text-color-secondary); }
.tutor-messages { display: flex; flex-direction: column; gap: 16px; margin: 20px 0; }
.tutor-message { padding: 16px; border: 1px solid var(--el-border-color-light); border-radius: 8px; }
.tutor-message.user { background: var(--el-fill-color-light); }
.tutor-message p { white-space: pre-wrap; overflow-wrap: anywhere; line-height: 1.8; margin-bottom: 0; }
.tutor-compose { display: grid; gap: 10px; }
.tutor-compose .el-button { justify-self: end; }
.tutor-recovery, .tutor-suggestions { padding: 12px 0; line-height: 1.7; }
.tutor-recovery { padding-top: 0; }
.tutor-recovery p { max-height: 60px; overflow: auto; overflow-wrap: anywhere; margin: 0 0 8px; }
.tutor-followups { display: flex; flex-wrap: wrap; margin-bottom: 12px; }
@media (max-width: 1000px) {
  .tutor-layout { grid-template-columns: 1fr; grid-template-rows: minmax(0, 180px) minmax(0, 1fr); gap: 12px; }
  .tutor-sidebar { padding: 12px; gap: 8px; }
  .tutor-chat { padding: 16px; }
  .tutor-heading { margin-bottom: 10px; }
  .tutor-heading .muted-text:last-child { display: none; }
}
</style>
