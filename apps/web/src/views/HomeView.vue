<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'

import {
  apiErrorMessage,
  listDueReviews,
  listKnowledgeBases,
  listMastery,
  listQuestions,
  listStudyHistory,
} from '@/api'
import type { KnowledgeBase, StudySession } from '@/api/types'
import { formatDate, modeLabel, percentage } from '@/utils/format'

const loading = ref(true)
const knowledgeBases = ref<KnowledgeBase[]>([])
const dueCount = ref(0)
const questionCount = ref(0)
const masteryScores = ref<number[]>([])
const recentSessions = ref<StudySession[]>([])

const averageMastery = computed(() => {
  if (!masteryScores.value.length) return '尚未学习'
  return percentage(
    masteryScores.value.reduce((total, value) => total + value, 0) /
      masteryScores.value.length,
  )
})

async function loadDashboard() {
  loading.value = true
  try {
    const [bases, reviews, mastery, questions, history] = await Promise.all([
      listKnowledgeBases({ page_size: 100, status: 'active' }),
      listDueReviews(),
      listMastery(),
      listQuestions(),
      listStudyHistory({ page_size: 5 }),
    ])
    knowledgeBases.value = bases.items
    dueCount.value = reviews.length
    masteryScores.value = mastery.map((item) => item.mastery_score)
    questionCount.value = questions.total
    recentSessions.value = history.items.slice(0, 5)
  } catch (error) {
    ElMessage.error(apiErrorMessage(error))
  } finally {
    loading.value = false
  }
}

onMounted(loadDashboard)
</script>

<template>
  <div v-loading="loading" class="page-stack">
    <section class="hero-card">
      <div>
        <span class="section-kicker">从资料到掌握</span>
        <h2>今天继续，把薄弱点变成真正掌握。</h2>
        <p>资料、题库、练习与复习计划已经连成一条可恢复的学习闭环。</p>
      </div>
      <RouterLink class="primary-action" to="/study">开始自适应练习</RouterLink>
    </section>

    <section class="metric-grid metric-grid-four">
      <article class="metric-card">
        <span>今日待复习</span><strong>{{ dueCount }}</strong><small>已到期知识点</small>
      </article>
      <article class="metric-card">
        <span>平均掌握度</span><strong>{{ averageMastery }}</strong><small>基于已练知识点</small>
      </article>
      <article class="metric-card">
        <span>可用题库</span><strong>{{ questionCount }}</strong><small>全部状态题目</small>
      </article>
      <article class="metric-card">
        <span>知识库</span><strong>{{ knowledgeBases.length }}</strong><small>当前活跃主题</small>
      </article>
    </section>

    <section class="content-grid two-one">
      <article class="panel-card">
        <div class="section-heading row-between">
          <div><h2>最近学习</h2></div>
          <RouterLink class="text-link" to="/progress">查看全部</RouterLink>
        </div>
        <div v-if="recentSessions.length" class="activity-list">
          <div v-for="session in recentSessions" :key="session.id" class="activity-row">
            <div>
              <strong>{{ modeLabel[session.mode] || session.mode }}</strong>
              <small>{{ formatDate(session.started_at) }}</small>
            </div>
            <div class="activity-result">
              <span>{{ session.correct_count }}/{{ session.answered_question_count }} 正确</span>
              <el-tag :type="session.status === 'completed' ? 'success' : 'warning'" size="small">
                {{ session.status === 'completed' ? '已完成' : '进行中' }}
              </el-tag>
            </div>
          </div>
        </div>
        <el-empty v-else description="还没有学习记录，开始第一轮练习吧" :image-size="80" />
      </article>

      <article class="panel-card quick-card">

        <h2>下一步做什么？</h2>
        <RouterLink to="/knowledge-bases"><b>01</b><span>上传或管理学习资料</span></RouterLink>
        <RouterLink to="/questions"><b>02</b><span>审核题目与原文引用</span></RouterLink>
        <RouterLink to="/study"><b>03</b><span>开始诊断、练习或复习</span></RouterLink>
      </article>
    </section>
  </div>
</template>
