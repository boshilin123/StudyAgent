<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Delete, DocumentAdd, Plus, Refresh, UploadFilled } from '@element-plus/icons-vue'

import {
  apiErrorMessage,
  createKnowledgeBase,
  createQuestionGenerationJob,
  deleteMaterial,
  deleteKnowledgeBase,
  getIngestionJob,
  listKnowledgeBases,
  listMaterials,
  listQuestionGenerationJobs,
  updateKnowledgeBase,
  uploadMaterial,
} from '@/api'
import type { Job, KnowledgeBase, Material, QuestionGenerationJob, QuestionType } from '@/api/types'
import { formatBytes, formatDate, questionTypeLabel } from '@/utils/format'

const loading = ref(false)
const materialLoading = ref(false)
const bases = ref<KnowledgeBase[]>([])
const selectedId = ref('')
const materials = ref<Material[]>([])
const createVisible = ref(false)
const createForm = ref({ name: '', description: '' })
const creating = ref(false)
const selectedFile = ref<File | null>(null)
const uploadTitle = ref('')
const uploading = ref(false)
const generatingIds = ref<Set<string>>(new Set())
const generationJobs = ref<Record<string, QuestionGenerationJob>>({})
const generationVisible = ref(false)
const rejectedJob = ref<QuestionGenerationJob | null>(null)
const generationMaterial = ref<Material | null>(null)
const generationForm = ref({ count: 6, types: ['single_choice', 'fill_blank', 'true_false'] as QuestionType[], difficulty: [1, 3] })
const deletingBase = ref(false)
const JOB_STORAGE_KEY = 'study-agent-ingestion-jobs'
const ingestionJobs = ref<Record<string, Job>>({})
const ingestionJobIds = ref<Record<string, string>>(loadSavedJobIds())
let refreshTimer: number | undefined

function loadSavedJobIds(): Record<string, string> {
  try {
    return JSON.parse(localStorage.getItem(JOB_STORAGE_KEY) || '{}') as Record<string, string>
  } catch {
    return {}
  }
}

function saveJobIds() {
  localStorage.setItem(JOB_STORAGE_KEY, JSON.stringify(ingestionJobIds.value))
}

const selectedBase = computed(() => bases.value.find((item) => item.id === selectedId.value))
const processing = computed(() =>
  materials.value.some((item) => ['pending', 'parsing'].includes(item.parse_status)) ||
  Object.values(ingestionJobs.value).some((job) => ['queued', 'running'].includes(job.status)),
  // Generation has a separate lifecycle from document ingestion.
)
const generationProcessing = computed(() =>
  Object.values(generationJobs.value).some((job) => ['pending', 'running', 'queued'].includes(job.status)),
)

const statusMap: Record<string, { label: string; type: 'success' | 'warning' | 'danger' | 'info' }> = {
  ready: { label: '已就绪', type: 'success' },
  pending: { label: '排队中', type: 'info' },
  parsing: { label: '处理中', type: 'warning' },
  partial: { label: '部分完成', type: 'warning' },
  failed: { label: '失败', type: 'danger' },
}

async function loadBases() {
  loading.value = true
  try {
    const page = await listKnowledgeBases({ page_size: 100 })
    bases.value = page.items
    if (!bases.value.some((item) => item.id === selectedId.value)) {
      selectedId.value = bases.value.find((item) => item.status === 'active')?.id || bases.value[0]?.id || ''
    }
  } catch (error) {
    ElMessage.error(apiErrorMessage(error))
  } finally {
    loading.value = false
  }
}

async function loadMaterials() {
  const baseId = selectedId.value
  if (!selectedId.value) {
    materials.value = []
    generationJobs.value = {}
    return
  }
  materialLoading.value = true
  try {
    const page = await listMaterials(baseId)
    if (baseId !== selectedId.value) return
    materials.value = page.items
    await Promise.all([refreshJobs(), refreshGenerationJobs()])
  } catch (error) {
    ElMessage.error(apiErrorMessage(error))
  } finally {
    materialLoading.value = false
  }
}

async function refreshLibrary() {
  await Promise.all([loadMaterials(), loadBases()])
}

async function refreshGenerationJobs() {
  const baseId = selectedId.value
  const results = await Promise.allSettled(materials.value.map(async (material) =>
    [material.id, (await listQuestionGenerationJobs(material.id))[0]] as const,
  ))
  if (baseId !== selectedId.value) return
  const next: Record<string, QuestionGenerationJob> = {}
  for (const result of results) {
    if (result.status === 'fulfilled' && result.value[1]) next[result.value[0]] = result.value[1]
  }
  generationJobs.value = next
}

function generationLabel(job: QuestionGenerationJob) {
  if (['pending', 'queued'].includes(job.status)) return '等待生成'
  if (job.status === 'running') return '正在生成'
  if (job.status === 'failed') return '生成失败'
  return job.generated_count < job.target_question_count ? '生成数量不足' : '生成完成'
}

async function refreshJobs() {
  const visibleIds = new Set(materials.value.map((item) => item.id))
  const entries = Object.entries(ingestionJobIds.value).filter(([materialId]) =>
    visibleIds.has(materialId),
  )
  if (!entries.length) return
  const results = await Promise.allSettled(
    entries.map(async ([materialId, jobId]) => [materialId, await getIngestionJob(jobId)] as const),
  )
  const nextJobs = { ...ingestionJobs.value }
  for (const result of results) {
    if (result.status !== 'fulfilled') continue
    const [materialId, job] = result.value
    nextJobs[materialId] = job
    if (['completed', 'failed'].includes(job.status)) delete ingestionJobIds.value[materialId]
  }
  ingestionJobs.value = nextJobs
  saveJobIds()
}

async function submitCreate() {
  if (!createForm.value.name.trim()) return ElMessage.warning('请输入知识库名称')
  creating.value = true
  try {
    const result = await createKnowledgeBase({
      name: createForm.value.name.trim(),
      description: createForm.value.description.trim() || undefined,
    })
    createVisible.value = false
    createForm.value = { name: '', description: '' }
    await loadBases()
    selectedId.value = result.id
    ElMessage.success('知识库已创建')
  } catch (error) {
    ElMessage.error(apiErrorMessage(error))
  } finally {
    creating.value = false
  }
}

function chooseFile(event: Event) {
  const target = event.target as HTMLInputElement
  selectedFile.value = target.files?.[0] || null
  if (selectedFile.value) uploadTitle.value = selectedFile.value.name.replace(/\.[^.]+$/, '')
}

async function submitUpload() {
  if (!selectedId.value || !selectedFile.value) return
  uploading.value = true
  try {
    const result = await uploadMaterial(selectedId.value, selectedFile.value, uploadTitle.value)
    ingestionJobs.value = { ...ingestionJobs.value, [result.material.id]: result.job }
    ingestionJobIds.value[result.material.id] = result.job.id
    saveJobIds()
    selectedFile.value = null
    uploadTitle.value = ''
    await Promise.all([loadMaterials(), loadBases()])
    ElMessage.success('资料已上传，后台正在解析与建立索引')
  } catch (error) {
    ElMessage.error(apiErrorMessage(error))
  } finally {
    uploading.value = false
  }
}

async function removeMaterial(material: Material) {
  try {
    await ElMessageBox.confirm(`确定删除资料“${material.title}”及其索引吗？`, '删除资料', {
      type: 'warning',
      confirmButtonText: '删除',
    })
    await deleteMaterial(material.id)
    await Promise.all([loadMaterials(), loadBases()])
    ElMessage.success('资料已删除')
  } catch (error) {
    if (error !== 'cancel') ElMessage.error(apiErrorMessage(error))
  }
}

function openGeneration(material: Material) {
  generationMaterial.value = material
  generationVisible.value = true
}

async function generateQuestions() {
  const material = generationMaterial.value
  if (!material) return
  if (!generationForm.value.types.length) return ElMessage.warning('请至少选择一种题型')
  if (!Number.isInteger(generationForm.value.count) || generationForm.value.count < 1 || generationForm.value.count > 100) return ElMessage.warning('题目数量应为 1–100 的整数')
  generatingIds.value = new Set(generatingIds.value).add(material.id)
  try {
    const job = await createQuestionGenerationJob(material.id, {
      target_question_count: generationForm.value.count,
      allowed_types: generationForm.value.types,
      difficulty_min: generationForm.value.difficulty[0]!,
      difficulty_max: generationForm.value.difficulty[1]!,
    })
    generationJobs.value = { ...generationJobs.value, [material.id]: job }
    generationVisible.value = false
    ElMessage.success(`已提交生成 ${job.target_question_count} 道题的任务，实际结果将在资料下方显示`)
  } catch (error) {
    ElMessage.error(apiErrorMessage(error))
  } finally {
    const next = new Set(generatingIds.value)
    next.delete(material.id)
    generatingIds.value = next
  }
}

async function removeKnowledgeBase(base: KnowledgeBase) {
  try {
    await ElMessageBox.confirm(`确定删除知识库“${base.name}”吗？删除后将移出知识库和题库列表，不能开始新的学习或辅导。已有资料、题目和历史记录保留。`, '删除知识库', {
      type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消',
    })
    deletingBase.value = true
    await deleteKnowledgeBase(base.id)
    generationJobs.value = {}
    await loadBases()
    await loadMaterials()
    ElMessage.success('知识库已删除，历史记录保留')
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') ElMessage.error(apiErrorMessage(error))
  } finally {
    deletingBase.value = false
  }
}

async function toggleArchive(base: KnowledgeBase) {
  try {
    await updateKnowledgeBase(base.id, { status: base.status === 'active' ? 'archived' : 'active' })
    await loadBases()
    ElMessage.success(base.status === 'active' ? '知识库已归档' : '知识库已恢复')
  } catch (error) {
    ElMessage.error(apiErrorMessage(error))
  }
}

watch(selectedId, loadMaterials)
onMounted(async () => {
  await loadBases()
  refreshTimer = window.setInterval(() => {
    if (processing.value || generationProcessing.value) {
      void Promise.all([loadMaterials(), loadBases()])
    }
  }, 3000)
})
onUnmounted(() => window.clearInterval(refreshTimer))
</script>

<template>
  <section class="content-grid knowledge-layout">
    <aside class="panel-card base-sidebar" v-loading="loading">
      <div class="row-between section-heading compact-heading">
        <div><h2>学习主题</h2></div>
        <el-button circle :icon="Plus" type="primary" aria-label="创建知识库" @click="createVisible = true" />
      </div>
      <button
        v-for="base in bases"
        :key="base.id"
        type="button"
        class="base-item"
        :class="{ active: base.id === selectedId }"
        @click="selectedId = base.id"
      >
        <span class="base-dot" :class="base.status" />
        <span><strong>{{ base.name }}</strong><small>{{ base.material_count }} 份资料 · {{ base.question_count }} 道题</small></span>
      </button>
      <el-empty v-if="!bases.length && !loading" description="先创建一个学习主题" :image-size="70" />
    </aside>

    <main class="page-stack">
      <section v-if="selectedBase" class="panel-card library-header">
        <div>
          <div class="row-inline">
            <el-tag :type="selectedBase.status === 'active' ? 'success' : 'info'" size="small">
              {{ selectedBase.status === 'active' ? '使用中' : '已归档' }}
            </el-tag>
          </div>
          <h2>{{ selectedBase.name }}</h2>
          <p>{{ selectedBase.description || '暂无描述，可以直接上传个人学习资料。' }}</p>
        </div>
        <div class="row-inline">
          <el-button :icon="Refresh" @click="refreshLibrary">刷新</el-button>
          <el-button @click="toggleArchive(selectedBase)">
            {{ selectedBase.status === 'active' ? '归档' : '恢复' }}
          </el-button>
          <el-button type="danger" plain :loading="deletingBase" @click="removeKnowledgeBase(selectedBase)">删除知识库</el-button>
        </div>
      </section>

      <section v-if="selectedBase?.status === 'active'" class="panel-card upload-panel">
        <div class="upload-icon"><el-icon><UploadFilled /></el-icon></div>
        <div class="upload-copy">
          <strong>{{ selectedFile?.name || '上传 PDF、Word、PPT、Excel、Markdown 或 TXT' }}</strong>
          <small>单文件最大 100MB，上传后自动解析、切片并写入原文索引</small>
        </div>
        <input class="file-input" type="file" accept=".pdf,.docx,.pptx,.xlsx,.md,.markdown,.txt" @change="chooseFile" />
        <el-input v-if="selectedFile" v-model="uploadTitle" class="upload-title" placeholder="资料标题" />
        <el-button v-if="selectedFile" type="primary" :loading="uploading" @click="submitUpload">开始处理</el-button>
      </section>

      <section class="panel-card" v-loading="materialLoading">
        <div class="row-between section-heading compact-heading">
          <div><h2>学习资料</h2></div>
          <span class="muted-text">{{ materials.length }} 份</span>
        </div>
        <div v-if="materials.length" class="material-list">
          <article v-for="material in materials" :key="material.id" class="material-row">
            <div class="file-mark"><el-icon><DocumentAdd /></el-icon></div>
            <div class="material-main">
              <div class="row-inline">
                <strong>{{ material.title }}</strong>
                <el-tag :type="statusMap[material.parse_status]?.type || 'info'" size="small">
                  {{ statusMap[material.parse_status]?.label || material.parse_status }}
                </el-tag>
              </div>
              <small>{{ material.original_filename }} · {{ formatBytes(material.size_bytes) }} · {{ formatDate(material.created_at) }}</small>
              <el-progress
                v-if="ingestionJobs[material.id] && ['queued', 'running'].includes(ingestionJobs[material.id]!.status)"
                class="material-progress"
                :percentage="ingestionJobs[material.id]!.progress"
                :stroke-width="6"
              />
              <small v-if="ingestionJobs[material.id] && ['queued', 'running'].includes(ingestionJobs[material.id]!.status)">
                当前阶段：{{ ingestionJobs[material.id]!.stage }}
              </small>
              <p v-if="material.error_message" class="error-text">{{ material.error_message }}</p>
              <div v-if="generationJobs[material.id]" class="generation-result" role="status">
                <strong>{{ generationLabel(generationJobs[material.id]!) }}</strong>
                <small>目标 {{ generationJobs[material.id]!.target_question_count }} 道 · 通过校验 {{ generationJobs[material.id]!.generated_count }} 道 · 拒绝 {{ generationJobs[material.id]!.rejected_count }} 道</small>
                <el-progress v-if="['pending', 'running', 'queued'].includes(generationJobs[material.id]!.status)" :percentage="generationJobs[material.id]!.progress" :stroke-width="6" />
                <small v-else-if="generationJobs[material.id]!.error_message" class="error-text">{{ generationJobs[material.id]!.error_message }}</small>
                <small v-else-if="generationJobs[material.id]!.generated_count < generationJobs[material.id]!.target_question_count">未通过校验的候选题不会入库；生成数量是目标，可能因资料、引用校验或重复题而不足。</small>
                <small v-if="generationJobs[material.id]!.rejected_count">被拒绝的候选题未进入题库，详情可在此查看。</small>
                <el-button v-if="generationJobs[material.id]!.rejected_count" link type="primary" style="justify-self: start" @click="rejectedJob = generationJobs[material.id]!">查看拒绝详情</el-button>
                <RouterLink :to="{ path: '/questions', query: { knowledge_base_id: selectedId } }">查看该知识库题目</RouterLink>
              </div>
            </div>
            <div class="row-inline">
              <el-button
                v-if="material.parse_status === 'ready' && selectedBase?.status === 'active'"
                type="primary"
                plain
                :loading="generatingIds.has(material.id)"
                :disabled="['pending', 'running', 'queued'].includes(generationJobs[material.id]?.status || '')"
                @click="openGeneration(material)"
              >生成题目</el-button>
              <el-button text type="danger" :icon="Delete" @click="removeMaterial(material)" />
            </div>
          </article>
        </div>
        <el-empty v-else description="还没有资料" :image-size="90" />
      </section>
    </main>
  </section>

  <el-dialog v-model="createVisible" title="创建知识库" width="460px">
    <el-form label-position="top">
      <el-form-item label="名称" required><el-input v-model="createForm.name" maxlength="200" /></el-form-item>
      <el-form-item label="描述"><el-input v-model="createForm.description" type="textarea" :rows="4" /></el-form-item>
    </el-form>
    <template #footer><el-button @click="createVisible = false">取消</el-button><el-button type="primary" :loading="creating" @click="submitCreate">创建</el-button></template>
  </el-dialog>

  <el-dialog v-model="generationVisible" title="生成题目" width="460px">
    <p>{{ generationMaterial?.title }}</p>
    <el-form label-position="top">
      <el-form-item label="目标题目数量"><el-input-number v-model="generationForm.count" :min="1" :max="100" :precision="0" aria-label="目标题目数量" /></el-form-item>
      <el-form-item label="题型"><el-checkbox-group v-model="generationForm.types"><el-checkbox value="single_choice">单选题</el-checkbox><el-checkbox value="fill_blank">填空题</el-checkbox><el-checkbox value="true_false">判断题</el-checkbox></el-checkbox-group></el-form-item>
      <el-form-item label="难度范围"><el-slider v-model="generationForm.difficulty" range :min="1" :max="5" :step="1" show-stops /></el-form-item>
    </el-form>
    <p class="muted-text">可设置 1–100 道。仅保存通过质量和原文引用校验的题目；实际数量可能不足目标，同一知识库中的重复题会复用。</p>
    <template #footer><el-button @click="generationVisible = false">取消</el-button><el-button type="primary" :loading="!!generationMaterial && generatingIds.has(generationMaterial.id)" @click="generateQuestions">提交生成</el-button></template>
  </el-dialog>

  <el-dialog :model-value="Boolean(rejectedJob)" title="拒绝详情" width="min(720px, 90vw)" @close="rejectedJob = null">
    <template v-if="rejectedJob">
      <p>以下候选题未进入题库，不能用于练习。题库中的“已拒绝”状态与生成校验失败的候选题分开记录。</p>
      <template v-if="rejectedJob.rejected_candidates?.length">
        <section v-for="(item, index) in rejectedJob.rejected_candidates" :key="index" class="rejected-candidate">
          <el-tag type="danger">{{ item.reason }}</el-tag>
          <h3>{{ index + 1 }}. {{ item.question.stem }}</h3>
          <p>{{ questionTypeLabel[item.question.question_type] }} · 难度 {{ item.question.difficulty }}</p>
          <p v-for="option in item.question.options || []" :key="option.key">{{ option.key }}. {{ option.text }}</p>
          <p>候选答案：{{ item.question.correct_answers.join('、') }}</p>
          <p>候选解析：{{ item.question.explanation }}</p>
          <p>来源片段 {{ item.question.source_chunk_ids.length }} 个 · 引文 {{ item.question.source_quotes.length }} 条</p>
          <blockquote v-for="(quote, quoteIndex) in item.question.source_quotes" :key="quoteIndex">候选引文 {{ quoteIndex + 1 }}：{{ quote }}</blockquote>
          <small>以上内容由模型生成，未通过校验，不能视为可靠答案或原文引用。</small>
        </section>
      </template>
      <template v-else>
        <el-alert title="这次生成发生在详情保存功能上线前，候选题内容未被保存，无法补回。后续生成会保存题干、答案、引文和拒绝原因。" type="info" :closable="false" />
        <p v-if="rejectedJob.error_message">当时记录：{{ rejectedJob.error_message }}</p>
        <p v-else>当时仅记录了拒绝 {{ rejectedJob.rejected_count }} 道，未保存具体原因。</p>
      </template>
    </template>
    <template #footer><el-button @click="rejectedJob = null">关闭</el-button></template>
  </el-dialog>
</template>

<style scoped>
.generation-result { margin-top: 10px; display: grid; gap: 5px; font-size: 13px; }
.generation-result strong { font-size: 13px; }
.generation-result a { color: #347454; }
.rejected-candidate { padding: 18px 0; border-bottom: 1px solid #e2e9e3; }
.rejected-candidate p, .rejected-candidate blockquote { white-space: pre-wrap; overflow-wrap: anywhere; }
</style>
