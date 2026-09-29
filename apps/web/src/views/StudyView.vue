<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ArrowRight, Clock, Close, RefreshRight } from '@element-plus/icons-vue'

import {
  apiErrorMessage,
  createStudySession,
  finishStudySession,
  getStudySession,
  listKnowledgeBases,
  submitAnswer,
} from '@/api'
import type {
  AnswerResult,
  KnowledgeBase,
  QuestionType,
  StudyMode,
  StudySession,
} from '@/api/types'
import { modeLabel, percentage, questionTypeLabel } from '@/utils/format'

const STORAGE_KEY = 'study-agent-active-session'
const loading = ref(false)
const submitting = ref(false)
const bases = ref<KnowledgeBase[]>([])
const session = ref<StudySession | null>(null)
const lastResult = ref<AnswerResult | null>(null)
const answer = ref('')
const questionStartedAt = ref(Date.now())
const difficultyRange = ref<[number, number]>([1, 5])
const form = ref({
  knowledge_base_id: '',
  mode: 'practice' as StudyMode,
  question_count: 5,
  question_types: ['single_choice', 'fill_blank', 'true_false'] as QuestionType[],
  difficulty_min: 1,
  difficulty_max: 5,
})

const currentQuestion = computed(() => session.value?.current_question || null)
const progress = computed(() => {
  if (!session.value?.planned_question_count) return 0
  return Math.round(
    (session.value.answered_question_count / session.value.planned_question_count) * 100,
  )
})
const completedAccuracy = computed(() => {
  if (!session.value?.answered_question_count) return '0%'
  return percentage(session.value.correct_count / session.value.answered_question_count)
})

async function loadBases() {
  try {
    bases.value = (await listKnowledgeBases({ page_size: 100, status: 'active' })).items
    if (!form.value.knowledge_base_id && bases.value.length) {
      form.value.knowledge_base_id = bases.value[0]!.id
    }
  } catch (error) {
    ElMessage.error(apiErrorMessage(error))
  }
}

async function startSession() {
  if (!form.value.knowledge_base_id) return ElMessage.warning('请选择知识库')
  if (!form.value.question_types.length) return ElMessage.warning('至少选择一种题型')
  loading.value = true
  try {
    form.value.difficulty_min = difficultyRange.value[0]
    form.value.difficulty_max = difficultyRange.value[1]
    session.value = await createStudySession(form.value)
    localStorage.setItem(STORAGE_KEY, session.value.id)
    lastResult.value = null
    answer.value = ''
    questionStartedAt.value = Date.now()
  } catch (error) {
    ElMessage.error(apiErrorMessage(error))
  } finally {
    loading.value = false
  }
}

async function restoreSession(id: string) {
  loading.value = true
  try {
    const restored = await getStudySession(id)
    session.value = restored
    if (restored.status !== 'active') localStorage.removeItem(STORAGE_KEY)
    questionStartedAt.value = Date.now()
  } catch (error) {
    localStorage.removeItem(STORAGE_KEY)
    ElMessage.warning(`上次会话无法恢复：${apiErrorMessage(error)}`)
  } finally {
    loading.value = false
  }
}

function normalizedAnswer(): string | boolean {
  if (currentQuestion.value?.question_type === 'true_false') return answer.value === 'true'
  return answer.value
}

async function sendAnswer() {
  if (!session.value || !currentQuestion.value || answer.value === '') {
    return ElMessage.warning('请先填写答案')
  }
  submitting.value = true
  try {
    const result = await submitAnswer(session.value.id, {
      submission_id: crypto.randomUUID(),
      question_id: currentQuestion.value.id,
      answer: normalizedAnswer(),
      elapsed_seconds: Math.max(0, Math.round((Date.now() - questionStartedAt.value) / 1000)),
    })
    lastResult.value = result
    session.value = result.session
    if (result.session.status !== 'active') localStorage.removeItem(STORAGE_KEY)
  } catch (error) {
    ElMessage.error(apiErrorMessage(error))
  } finally {
    submitting.value = false
  }
}

function goNext() {
  lastResult.value = null
  answer.value = ''
  questionStartedAt.value = Date.now()
}

async function finish() {
  if (!session.value) return
  try {
    await ElMessageBox.confirm('确定提前结束本轮学习吗？已完成的作答会保留。', '结束学习', {
      type: 'warning',
    })
    session.value = await finishStudySession(session.value.id)
    localStorage.removeItem(STORAGE_KEY)
  } catch (error) {
    if (error !== 'cancel') ElMessage.error(apiErrorMessage(error))
  }
}

function resetWorkspace() {
  session.value = null
  lastResult.value = null
  answer.value = ''
  localStorage.removeItem(STORAGE_KEY)
}

onMounted(async () => {
  await loadBases()
  const saved = localStorage.getItem(STORAGE_KEY)
  if (saved) await restoreSession(saved)
})
</script>

<template>
  <div v-loading="loading" class="study-shell">
    <section v-if="!session" class="setup-card">
      <div class="setup-intro">
        <span class="section-kicker">ADAPTIVE SESSION</span>
        <h2>开始一轮真正会调整的练习</h2>
        <p>选择模式和范围。系统会根据掌握度、复习到期、历史题目和难度动态决定下一题。</p>
        <div class="mode-explain">
          <span><b>诊断</b>覆盖不同知识点</span><span><b>练习</b>优先补弱</span>
          <span><b>复习</b>只练到期内容</span><span><b>模拟考试</b>固定题序</span>
        </div>
      </div>
      <el-form class="setup-form" label-position="top">
        <el-form-item label="知识库" required>
          <el-select v-model="form.knowledge_base_id" placeholder="选择学习主题">
            <el-option v-for="base in bases" :key="base.id" :label="base.name" :value="base.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="学习模式">
          <el-segmented v-model="form.mode" :options="[
            { label: '诊断', value: 'diagnostic' }, { label: '练习', value: 'practice' },
            { label: '复习', value: 'review' }, { label: '模拟', value: 'mock_exam' },
          ]" />
        </el-form-item>
        <el-form-item label="题目数量"><el-input-number v-model="form.question_count" :min="1" :max="30" /></el-form-item>
        <el-form-item label="题型">
          <el-checkbox-group v-model="form.question_types">
            <el-checkbox value="single_choice">单选</el-checkbox>
            <el-checkbox value="fill_blank">填空</el-checkbox>
            <el-checkbox value="true_false">判断</el-checkbox>
          </el-checkbox-group>
        </el-form-item>
        <el-form-item label="难度范围">
          <el-slider v-model="difficultyRange" range :min="1" :max="5" />
          <span class="muted-text">当前范围 {{ difficultyRange[0] }}–{{ difficultyRange[1] }}</span>
        </el-form-item>
        <el-button type="primary" size="large" class="full-button" @click="startSession">开始学习</el-button>
      </el-form>
    </section>

    <template v-else>
      <section class="study-toolbar">
        <div>
          <span class="section-kicker">{{ modeLabel[session.mode] }}</span>
          <strong>第 {{ Math.min(session.answered_question_count + 1, session.planned_question_count) }} / {{ session.planned_question_count }} 题</strong>
        </div>
        <el-progress :percentage="progress" :stroke-width="8" />
        <el-button v-if="session.status === 'active'" text type="danger" :icon="Close" @click="finish">提前结束</el-button>
      </section>

      <section v-if="session.status === 'completed' && !lastResult" class="completion-card">
        <span class="completion-mark">✓</span>
        <span class="section-kicker">SESSION COMPLETED</span>
        <h2>本轮学习完成</h2>
        <div class="completion-stats">
          <div><strong>{{ session.answered_question_count }}</strong><span>已答题</span></div>
          <div><strong>{{ completedAccuracy }}</strong><span>正确率</span></div>
          <div><strong>{{ session.total_score }}</strong><span>总得分</span></div>
        </div>
        <div class="row-inline"><el-button type="primary" @click="resetWorkspace">开始新一轮</el-button><RouterLink class="el-button" to="/progress">查看学习进度</RouterLink></div>
      </section>

      <section v-else-if="lastResult" class="result-card" :class="lastResult.verdict">
        <div class="result-heading">
          <span class="result-icon">{{ lastResult.verdict === 'correct' ? '✓' : '×' }}</span>
          <div><span class="section-kicker">ANSWER FEEDBACK</span><h2>{{ lastResult.feedback }}</h2></div>
          <strong>{{ lastResult.score }} / {{ lastResult.max_score }}</strong>
        </div>
        <div class="explanation-grid">
          <div class="explanation-copy">
            <label>结论</label><p>{{ lastResult.rag_explanation.conclusion }}</p>
            <label>理解差距</label><p>{{ lastResult.rag_explanation.gap }}</p>
            <small>讲解来源：{{ lastResult.rag_explanation.provider === 'langchain' ? 'LangChain 原文讲解' : '题库解析' }}</small>
          </div>
          <div class="evidence-panel">
            <label>原文证据</label>
            <blockquote v-for="evidence in lastResult.rag_explanation.evidence" :key="evidence.chunk_id">
              {{ evidence.quote }}<small>chunk {{ evidence.chunk_id.slice(0, 8) }}</small>
            </blockquote>
            <p v-if="!lastResult.rag_explanation.evidence.length" class="muted-text">暂无引用</p>
          </div>
        </div>
        <div class="result-footer">
          <span>当前掌握度 <b>{{ percentage(lastResult.mastery.mastery_score) }}</b> · 下次复习 {{ new Date(lastResult.review_task.due_at).toLocaleDateString('zh-CN') }}</span>
          <el-button v-if="session.status === 'active'" type="primary" :icon="ArrowRight" @click="goNext">下一题</el-button>
          <el-button v-else type="primary" @click="goNext">查看本轮总结</el-button>
        </div>
      </section>

      <section v-else-if="currentQuestion" class="practice-card">
        <div class="question-meta">
          <div class="row-inline"><el-tag>{{ questionTypeLabel[currentQuestion.question_type] }}</el-tag><span>难度 {{ currentQuestion.difficulty }}/5</span></div>
          <span><el-icon><Clock /></el-icon> 建议认真思考后作答</span>
        </div>
        <h2>{{ currentQuestion.stem }}</h2>
        <div v-if="currentQuestion.selection_reason" class="selection-note">
          <el-icon><RefreshRight /></el-icon><span><b>为什么选这题：</b>{{ currentQuestion.selection_reason.message }}</span>
        </div>

        <el-radio-group v-if="currentQuestion.question_type === 'single_choice'" v-model="answer" class="answer-options">
          <el-radio v-for="option in currentQuestion.options" :key="option.key" :value="option.key" border>
            <b>{{ option.key }}</b><span>{{ option.text }}</span>
          </el-radio>
        </el-radio-group>
        <el-radio-group v-else-if="currentQuestion.question_type === 'true_false'" v-model="answer" class="answer-options two-options">
          <el-radio value="true" border><b>✓</b><span>正确</span></el-radio>
          <el-radio value="false" border><b>×</b><span>错误</span></el-radio>
        </el-radio-group>
        <el-input v-else v-model="answer" size="large" placeholder="请输入答案" @keyup.enter="sendAnswer" />

        <div class="practice-footer">
          <span>提交后会立即判分，并根据结果选择下一题</span>
          <el-button type="primary" size="large" :loading="submitting" :disabled="answer === ''" @click="sendAnswer">提交答案</el-button>
        </div>
      </section>

      <section v-else class="completion-card">
        <span class="section-kicker">SESSION RECOVERY</span>
        <h2>当前会话暂时没有可作答题目</h2>
        <p>题库可能已停用或会话状态需要重新同步。你可以结束本轮并重新选择范围。</p>
        <div class="row-inline">
          <el-button v-if="session.status === 'active'" type="primary" @click="finish">结束本轮</el-button>
          <el-button @click="resetWorkspace">返回学习设置</el-button>
        </div>
      </section>
    </template>
  </div>
</template>
