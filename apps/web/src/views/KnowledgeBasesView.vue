<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Delete, DocumentAdd, Plus, Refresh, UploadFilled } from '@element-plus/icons-vue'

import {
  apiErrorMessage,
  createKnowledgeBase,
  createQuestionGenerationJob,
  deleteMaterial,
  getIngestionJob,
  listKnowledgeBases,
  listMaterials,
  updateKnowledgeBase,
  uploadMaterial,
} from '@/api'
import type { Job, KnowledgeBase, Material } from '@/api/types'
import { formatBytes, formatDate } from '@/utils/format'

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
    if (!selectedId.value && bases.value.length) {
      selectedId.value = bases.value.find((item) => item.status === 'active')?.id || bases.value[0]!.id
    }
  } catch (error) {
    ElMessage.error(apiErrorMessage(error))
  } finally {
    loading.value = false
  }
}

async function loadMaterials() {
  if (!selectedId.value) {
    materials.value = []
    return
  }
  materialLoading.value = true
  try {
    materials.value = (await listMaterials(selectedId.value)).items
    await refreshJobs()
  } catch (error) {
    ElMessage.error(apiErrorMessage(error))
  } finally {
    materialLoading.value = false
  }
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

async function generateQuestions(material: Material) {
  generatingIds.value = new Set(generatingIds.value).add(material.id)
  try {
    await createQuestionGenerationJob(material.id, {
      target_question_count: 6,
      allowed_types: ['single_choice', 'fill_blank', 'true_false'],
      difficulty_min: 1,
      difficulty_max: 3,
    })
    ElMessage.success('题库生成任务已提交，可稍后到题库页面审核')
  } catch (error) {
    ElMessage.error(apiErrorMessage(error))
  } finally {
    const next = new Set(generatingIds.value)
    next.delete(material.id)
    generatingIds.value = next
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
    if (processing.value) void loadMaterials()
  }, 3000)
})
onUnmounted(() => window.clearInterval(refreshTimer))
</script>

<template>
  <section class="content-grid knowledge-layout">
    <aside class="panel-card base-sidebar" v-loading="loading">
      <div class="row-between section-heading compact-heading">
        <div><span class="section-kicker">LIBRARIES</span><h2>学习主题</h2></div>
        <el-button circle :icon="Plus" type="primary" @click="createVisible = true" />
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
            <span class="section-kicker">KNOWLEDGE BASE</span>
            <el-tag :type="selectedBase.status === 'active' ? 'success' : 'info'" size="small">
              {{ selectedBase.status === 'active' ? '使用中' : '已归档' }}
            </el-tag>
          </div>
          <h2>{{ selectedBase.name }}</h2>
          <p>{{ selectedBase.description || '暂无描述，可以直接上传个人学习资料。' }}</p>
        </div>
        <div class="row-inline">
          <el-button :icon="Refresh" @click="loadMaterials">刷新</el-button>
          <el-button @click="toggleArchive(selectedBase)">
            {{ selectedBase.status === 'active' ? '归档' : '恢复' }}
          </el-button>
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
          <div><span class="section-kicker">MATERIALS</span><h2>学习资料</h2></div>
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
            </div>
            <div class="row-inline">
              <el-button
                v-if="material.parse_status === 'ready'"
                type="primary"
                plain
                :loading="generatingIds.has(material.id)"
                @click="generateQuestions(material)"
              >生成 6 道题</el-button>
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
</template>
