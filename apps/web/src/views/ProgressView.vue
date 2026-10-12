<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { Calendar, DataAnalysis, Refresh } from '@element-plus/icons-vue'

import {
  apiErrorMessage,
  listDueReviews,
  listKnowledgeBases,
  listMastery,
  listStudyHistory,
} from '@/api'
import type { KnowledgeBase, Mastery, ReviewTask, StudySession } from '@/api/types'
import { formatDate, modeLabel, percentage } from '@/utils/format'

const loading = ref(false)
const bases = ref<KnowledgeBase[]>([])
const selectedBaseId = ref('')
const mastery = ref<Mastery[]>([])
const reviews = ref<ReviewTask[]>([])
const history = ref<StudySession[]>([])
const historyTotal = ref(0)
const historyLoading = ref(false)
const pageSize = 5
const masteryPage = ref(1)
const reviewPage = ref(1)
const historyPage = ref(1)
let loadVersion = 0
let historyVersion = 0

// 两个知识点列表各自翻页；顶部统计始终使用全部掌握度记录。
const visibleMastery = computed(() => mastery.value.slice((masteryPage.value - 1) * pageSize, masteryPage.value * pageSize))
const visibleReviews = computed(() => reviews.value.slice((reviewPage.value - 1) * pageSize, reviewPage.value * pageSize))

const average = computed(() => {
  if (!mastery.value.length) return 0
  return mastery.value.reduce((sum, item) => sum + item.mastery_score, 0) / mastery.value.length
})
const totalAnswered = computed(() => mastery.value.reduce((sum, item) => sum + item.answered_count, 0))
const totalCorrect = computed(() => mastery.value.reduce((sum, item) => sum + item.correct_count, 0))
const accuracy = computed(() => (totalAnswered.value ? totalCorrect.value / totalAnswered.value : 0))

function pointName(item: Mastery | ReviewTask) {
  return item.knowledge_point_name?.trim() || '未命名知识点'
}

async function loadHistory(page: number) {
  const version = ++historyVersion
  historyLoading.value = true
  try {
    const data = await listStudyHistory({
      ...(selectedBaseId.value ? { knowledge_base_id: selectedBaseId.value } : {}),
      page,
      page_size: pageSize,
    })
    if (version !== historyVersion) return
    history.value = data.items
    historyTotal.value = data.total
    historyPage.value = page
  } catch (error) {
    if (version === historyVersion) ElMessage.error(apiErrorMessage(error))
  } finally {
    if (version === historyVersion) historyLoading.value = false
  }
}

async function load() {
  const version = ++loadVersion
  const currentHistoryVersion = ++historyVersion
  loading.value = true
  historyLoading.value = false
  try {
    const horizon = new Date(Date.now() + 30 * 24 * 60 * 60 * 1000).toISOString()
    const [masteryData, reviewData, historyData] = await Promise.all([
      listMastery(selectedBaseId.value || undefined),
      listDueReviews(selectedBaseId.value || undefined, horizon),
      listStudyHistory({
        ...(selectedBaseId.value ? { knowledge_base_id: selectedBaseId.value } : {}),
        page: 1,
        page_size: pageSize,
      }),
    ])
    // 切换知识库后，忽略先前较慢的响应，避免显示旧范围的记录。
    if (version !== loadVersion) return
    mastery.value = masteryData
    reviews.value = reviewData
    masteryPage.value = 1
    reviewPage.value = 1
    if (currentHistoryVersion === historyVersion) {
      history.value = historyData.items
      historyTotal.value = historyData.total
      historyPage.value = 1
    }
  } catch (error) {
    if (version === loadVersion) ElMessage.error(apiErrorMessage(error))
  } finally {
    if (version === loadVersion) loading.value = false
  }
}

watch(selectedBaseId, load)
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
  <div v-loading="loading" class="page-stack">
    <section class="panel-card filter-bar progress-filter">
      <div><h2>掌握度与复习计划</h2></div>
      <div class="row-inline">
        <el-select v-model="selectedBaseId" clearable placeholder="全部知识库">
          <el-option v-for="base in bases" :key="base.id" :label="base.name" :value="base.id" />
        </el-select>
        <el-button :icon="Refresh" @click="load">刷新</el-button>
      </div>
    </section>

    <section class="metric-grid metric-grid-four compact-metrics">
      <article class="metric-card"><span>平均掌握度</span><strong>{{ percentage(average) }}</strong><small>{{ mastery.length }} 个已练知识点</small></article>
      <article class="metric-card"><span>累计答题</span><strong>{{ totalAnswered }}</strong><small>{{ historyTotal }} 次学习会话</small></article>
      <article class="metric-card"><span>总体正确率</span><strong>{{ percentage(accuracy) }}</strong><small>{{ totalCorrect }} 题回答正确</small></article>
      <article class="metric-card"><span>未来 30 天复习</span><strong>{{ reviews.length }}</strong><small>按到期时间排列</small></article>
    </section>

    <section class="content-grid equal-columns">
      <article class="panel-card progress-list-panel" aria-label="知识点掌握度">
        <div class="section-heading compact-heading"><h2>知识点掌握度</h2><span>共 {{ mastery.length }} 个</span></div>
        <div v-if="mastery.length" class="mastery-list">
          <div v-for="item in visibleMastery" :key="item.knowledge_point_id" class="mastery-row">
            <div class="row-between"><strong class="point-name" :title="pointName(item)">{{ pointName(item) }}</strong><b>{{ percentage(item.mastery_score) }}</b></div>
            <el-progress :percentage="Math.round(item.mastery_score * 100)" :show-text="false" :stroke-width="8" />
            <small>答题 {{ item.answered_count }} · 正确 {{ item.correct_count }} · 置信度 {{ percentage(item.confidence) }}</small>
          </div>
        </div>
        <el-empty v-else description="完成练习后生成掌握度" :image-size="80" />
        <nav v-if="mastery.length > pageSize" class="progress-pagination" aria-label="掌握度分页">
          <el-pagination v-model:current-page="masteryPage" :page-size="pageSize" :total="mastery.length" :pager-count="5" layout="prev, pager, next" size="small" />
        </nav>
      </article>

      <article class="panel-card progress-list-panel" aria-label="复习计划">
        <div class="section-heading compact-heading"><h2>复习计划</h2><span>共 {{ reviews.length }} 项</span></div>
        <div v-if="reviews.length" class="review-list">
          <div v-for="item in visibleReviews" :key="item.id" class="review-row">
            <span class="calendar-mark"><el-icon><Calendar /></el-icon></span>
            <div class="review-point"><strong class="point-name" :title="pointName(item)">{{ pointName(item) }}</strong><small>{{ formatDate(item.due_at) }} · 间隔 {{ item.interval_days }} 天</small></div>
            <el-tag :type="new Date(item.due_at) <= new Date() ? 'danger' : 'info'" size="small">{{ new Date(item.due_at) <= new Date() ? '已到期' : '待复习' }}</el-tag>
          </div>
        </div>
        <el-empty v-else description="未来 30 天没有复习任务" :image-size="80" />
        <nav v-if="reviews.length > pageSize" class="progress-pagination" aria-label="复习分页">
          <el-pagination v-model:current-page="reviewPage" :page-size="pageSize" :total="reviews.length" :pager-count="5" layout="prev, pager, next" size="small" />
        </nav>
      </article>
    </section>

    <section v-loading="historyLoading" class="panel-card" aria-label="学习历史">
      <div class="section-heading compact-heading"><h2>学习历史</h2><span>共 {{ historyTotal }} 次</span></div>
      <el-table v-if="history.length" :data="history" stripe>
        <el-table-column label="模式" width="110"><template #default="scope">{{ modeLabel[scope.row.mode] || scope.row.mode }}</template></el-table-column>
        <el-table-column label="开始时间" min-width="150"><template #default="scope">{{ formatDate(scope.row.started_at) }}</template></el-table-column>
        <el-table-column prop="answered_question_count" label="答题" width="90" />
        <el-table-column label="正确率" width="110"><template #default="scope">{{ scope.row.answered_question_count ? percentage(scope.row.correct_count / scope.row.answered_question_count) : '—' }}</template></el-table-column>
        <el-table-column label="得分" width="110"><template #default="scope">{{ scope.row.total_score }} / {{ scope.row.max_total_score }}</template></el-table-column>
        <el-table-column label="状态" width="100"><template #default="scope"><el-tag :type="scope.row.status === 'completed' ? 'success' : 'warning'" size="small">{{ scope.row.status === 'completed' ? '已完成' : '进行中' }}</el-tag></template></el-table-column>
      </el-table>
      <el-empty v-else description="暂无学习历史" :image-size="80"><el-icon :size="28"><DataAnalysis /></el-icon></el-empty>
      <nav v-if="historyTotal > pageSize" class="progress-pagination" aria-label="学习历史分页">
        <el-pagination :current-page="historyPage" :page-size="pageSize" :total="historyTotal" :pager-count="5" :disabled="loading || historyLoading" layout="prev, pager, next" size="small" @current-change="loadHistory" />
      </nav>
    </section>
  </div>
</template>

<style scoped>
.progress-list-panel { display: flex; flex-direction: column; min-width: 0; }
.point-name { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.mastery-row b { flex-shrink: 0; }
.review-point { min-width: 0; }
.progress-pagination { display: flex; justify-content: center; padding-top: 20px; }
.progress-list-panel .progress-pagination { margin-top: auto; }
</style>
