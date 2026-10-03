<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Check, Delete, EditPen, Refresh, VideoPause } from '@element-plus/icons-vue'

import {
  apiErrorMessage,
  deleteQuestion,
  listKnowledgeBases,
  listQuestions,
  setQuestionStatus,
  updateQuestion,
} from '@/api'
import type { KnowledgeBase, Question, QuestionType } from '@/api/types'
import { questionTypeLabel } from '@/utils/format'

const loading = ref(false)
const bases = ref<KnowledgeBase[]>([])
const questions = ref<Question[]>([])
const total = ref(0)
const route = useRoute()
const filters = ref({ knowledge_base_id: typeof route.query.knowledge_base_id === 'string' ? route.query.knowledge_base_id : '', status: '', question_type: '' })
const detail = ref<Question | null>(null)
const editVisible = ref(false)
const saving = ref(false)
const deletingIds = ref(new Set<string>())
const editForm = ref({ stem: '', answers: '', explanation: '', difficulty: 1 })
const questionTypes: QuestionType[] = ['single_choice', 'fill_blank', 'true_false']

const activeCount = computed(() => questions.value.filter((item) => item.status === 'active').length)
const draftCount = computed(() => questions.value.filter((item) => item.status === 'draft').length)

const statusMap: Record<string, { label: string; type: 'success' | 'warning' | 'danger' | 'info' }> = {
  active: { label: '已启用', type: 'success' },
  draft: { label: '待审核', type: 'warning' },
  disabled: { label: '已停用', type: 'info' },
  rejected: { label: '已拒绝', type: 'danger' },
}

async function load() {
  loading.value = true
  try {
    const params: Record<string, string> = {}
    for (const [key, value] of Object.entries(filters.value)) if (value) params[key] = value
    const page = await listQuestions(params)
    questions.value = page.items
    total.value = page.total
  } catch (error) {
    ElMessage.error(apiErrorMessage(error))
  } finally {
    loading.value = false
  }
}

function answerText(value: unknown): string {
  if (Array.isArray(value)) return value.join('、')
  return String(value ?? '')
}

function openEdit(question: Question) {
  detail.value = question
  editForm.value = {
    stem: question.stem,
    answers: answerText(question.correct_answer),
    explanation: question.explanation,
    difficulty: question.difficulty,
  }
  editVisible.value = true
}

async function saveEdit() {
  if (!detail.value) return
  saving.value = true
  try {
    const updated = await updateQuestion(detail.value.id, {
      stem: editForm.value.stem,
      correct_answers: editForm.value.answers.split(/[、,，]/).map((item) => item.trim()).filter(Boolean),
      explanation: editForm.value.explanation,
      difficulty: editForm.value.difficulty,
    })
    detail.value = updated
    editVisible.value = false
    await load()
    ElMessage.success('题目已保存；已启用题目编辑后会自动退回待审核')
  } catch (error) {
    ElMessage.error(apiErrorMessage(error))
  } finally {
    saving.value = false
  }
}

async function toggleStatus(question: Question) {
  try {
    const updated = await setQuestionStatus(question.id, question.status !== 'active')
    if (detail.value?.id === updated.id) detail.value = updated
    await load()
    ElMessage.success(updated.status === 'active' ? '题目已启用' : '题目已停用')
  } catch (error) {
    ElMessage.error(apiErrorMessage(error))
  }
}

async function removeQuestion(question: Question) {
  try {
    await ElMessageBox.confirm(
      '删除后该题将退出题库，不再用于练习；已有作答和学习历史会保留。确认删除吗？',
      '删除题目', { confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning' },
    )
  } catch { return }
  deletingIds.value.add(question.id)
  try {
    await deleteQuestion(question.id)
    if (detail.value?.id === question.id) {
      detail.value = null
      editVisible.value = false
    }
    await load()
    ElMessage.success('题目已删除，已有学习历史保留')
  } catch (error) {
    ElMessage.error(apiErrorMessage(error))
  } finally {
    deletingIds.value.delete(question.id)
  }
}

onMounted(async () => {
  try {
    bases.value = (await listKnowledgeBases({ page_size: 100 })).items
  } catch (error) {
    ElMessage.error(apiErrorMessage(error))
  }
  await load()
})
</script>

<template>
  <div class="page-stack">
    <section class="metric-grid metric-grid-four compact-metrics">
      <article class="metric-card"><span>当前结果</span><strong>{{ total }}</strong><small>符合筛选条件</small></article>
      <article class="metric-card"><span>本页已启用</span><strong>{{ activeCount }}</strong><small>可进入学习会话</small></article>
      <article class="metric-card"><span>本页待审核</span><strong>{{ draftCount }}</strong><small>核对后再启用</small></article>
      <article class="metric-card"><span>质量原则</span><strong>可溯源</strong><small>启用题必须绑定原文</small></article>
    </section>

    <section class="panel-card filter-bar">
      <el-select v-model="filters.knowledge_base_id" clearable placeholder="全部知识库" @change="load">
        <el-option v-for="base in bases" :key="base.id" :label="base.name" :value="base.id" />
      </el-select>
      <el-select v-model="filters.status" clearable placeholder="全部状态" @change="load">
        <el-option label="待审核" value="draft" /><el-option label="已启用" value="active" />
        <el-option label="已停用" value="disabled" /><el-option label="已拒绝" value="rejected" />
      </el-select>
      <el-select v-model="filters.question_type" clearable placeholder="全部题型" @change="load">
        <el-option v-for="type in questionTypes" :key="type" :label="questionTypeLabel[type]" :value="type" />
      </el-select>
      <el-button :icon="Refresh" @click="load">刷新</el-button>
    </section>

    <section class="question-grid" v-loading="loading">
      <article v-for="question in questions" :key="question.id" class="question-card" @click="detail = question">
        <div class="row-between">
          <div class="row-inline">
            <el-tag size="small">{{ questionTypeLabel[question.question_type] }}</el-tag>
            <span class="difficulty-dots" :aria-label="`难度 ${question.difficulty}`">
              <i v-for="value in 5" :key="value" :class="{ filled: value <= question.difficulty }" />
            </span>
          </div>
          <el-tag :type="statusMap[question.status]?.type" size="small">{{ statusMap[question.status]?.label }}</el-tag>
        </div>
        <h3>{{ question.stem }}</h3>
        <div v-if="question.options" class="mini-options">
          <span v-for="option in question.options" :key="option.key"><b>{{ option.key }}</b>{{ option.text }}</span>
        </div>
        <div class="question-footer">
          <span>{{ question.sources.length }} 条原文引用</span>
          <div class="row-inline" @click.stop>
            <el-button text :icon="EditPen" @click="openEdit(question)">编辑</el-button>
            <el-button
              text
              :type="question.status === 'active' ? 'warning' : 'success'"
              :icon="question.status === 'active' ? VideoPause : Check"
              @click="toggleStatus(question)"
            >{{ question.status === 'active' ? '停用' : '启用' }}</el-button>
            <el-button text type="danger" :icon="Delete" :loading="deletingIds.has(question.id)" @click="removeQuestion(question)">删除</el-button>
          </div>
        </div>
      </article>
      <el-empty v-if="!questions.length && !loading" class="wide-empty" description="没有符合条件的题目" />
    </section>
  </div>

  <el-drawer :model-value="Boolean(detail)" :with-header="false" size="520px" @close="detail = null">
    <template v-if="detail">
      <div class="drawer-heading">

        <h2>{{ questionTypeLabel[detail.question_type] }}</h2>
        <el-tag :type="statusMap[detail.status]?.type">{{ statusMap[detail.status]?.label }}</el-tag>
      </div>
      <section class="detail-block"><label>题目</label><p>{{ detail.stem }}</p></section>
      <section v-if="detail.options" class="detail-block option-detail">
        <label>选项</label><p v-for="option in detail.options" :key="option.key"><b>{{ option.key }}</b>{{ option.text }}</p>
      </section>
      <section class="detail-block answer-block"><label>标准答案</label><p>{{ answerText(detail.correct_answer) }}</p></section>
      <section class="detail-block"><label>解析</label><p>{{ detail.explanation }}</p></section>
      <section class="detail-block">
        <label>原文证据</label>
        <blockquote v-for="source in detail.sources" :key="source.chunk_id">{{ source.quote }}<small>chunk {{ source.chunk_id.slice(0, 8) }}</small></blockquote>
      </section>
      <div class="drawer-actions">
        <el-button :icon="EditPen" @click="openEdit(detail)">编辑题目</el-button>
        <el-button :type="detail.status === 'active' ? 'warning' : 'success'" @click="toggleStatus(detail)">{{ detail.status === 'active' ? '停用' : '审核通过并启用' }}</el-button>
        <el-button type="danger" :icon="Delete" :loading="deletingIds.has(detail.id)" @click="removeQuestion(detail)">删除题目</el-button>
      </div>
    </template>
  </el-drawer>

  <el-dialog v-model="editVisible" title="编辑题目" width="640px">
    <el-form label-position="top">
      <el-form-item label="题干"><el-input v-model="editForm.stem" type="textarea" :rows="3" /></el-form-item>
      <el-form-item label="标准答案（多个答案用逗号分隔）"><el-input v-model="editForm.answers" /></el-form-item>
      <el-form-item label="难度"><el-rate v-model="editForm.difficulty" :max="5" /></el-form-item>
      <el-form-item label="解析"><el-input v-model="editForm.explanation" type="textarea" :rows="5" /></el-form-item>
    </el-form>
    <template #footer><el-button @click="editVisible = false">取消</el-button><el-button type="primary" :loading="saving" @click="saveEdit">保存</el-button></template>
  </el-dialog>
</template>
