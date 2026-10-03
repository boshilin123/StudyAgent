<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { Collection, DataAnalysis, HomeFilled, Reading } from '@element-plus/icons-vue'
import { storeToRefs } from 'pinia'
import { useRoute } from 'vue-router'
import { ElMessageBox } from 'element-plus'

import { useAppStore } from '@/stores/app'
import { apiClient } from '@/api/client'

const route = useRoute()
const appStore = useAppStore()
const { sidebarCollapsed, sidebarWidth } = storeToRefs(appStore)
const apiState = ref<'checking' | 'ready' | 'unavailable'>('checking')
const apiLabel = computed(() => ({ checking: '正在检查 API', ready: 'API 可用', unavailable: 'API 不可用' })[apiState.value])
let healthTimer: number | undefined
let healthController: AbortController | undefined

async function checkApi() {
  healthController?.abort()
  const controller = new AbortController()
  healthController = controller
  try {
    const { data } = await apiClient.get<{ status: string }>('/health/ready', {
      timeout: 8000, signal: controller.signal,
    })
    if (!controller.signal.aborted) apiState.value = data.status === 'ok' ? 'ready' : 'unavailable'
  } catch {
    if (!controller.signal.aborted) apiState.value = 'unavailable'
  }
}

onMounted(() => {
  void checkApi()
  healthTimer = window.setInterval(() => void checkApi(), 30000)
})
onUnmounted(() => {
  window.clearInterval(healthTimer)
  healthController?.abort()
})

const navItems = [
  { path: '/', label: '学习概览', icon: HomeFilled },
  { path: '/knowledge-bases', label: '知识库', icon: Collection },
  { path: '/questions', label: '题库', icon: Reading },
  { path: '/study', label: '学习工作台', icon: Reading },
  { path: '/tutor', label: '学习辅导', icon: Reading },
  { path: '/progress', label: '学习进度', icon: DataAnalysis },
]

async function configureAccessToken() {
  try {
    const { value } = await ElMessageBox.prompt('受保护部署需要访问令牌；本地未启用认证时可留空。',
      '访问令牌', { inputType: 'password', inputValue: '', confirmButtonText: '保存' })
    if (value?.trim()) sessionStorage.setItem('study-agent-access-token', value.trim())
    else sessionStorage.removeItem('study-agent-access-token')
    window.location.reload()
  } catch { /* Cancel keeps the current token. */ }
}
</script>

<template>
  <div class="app-shell" :style="{ '--sidebar-width': sidebarWidth }">
    <aside class="sidebar" :style="{ width: sidebarWidth }">
      <button class="brand" type="button" @click="appStore.toggleSidebar">
        <span class="brand-mark">S</span>
        <span v-if="!sidebarCollapsed" class="brand-name">StudyAgent</span>
      </button>

      <nav class="nav-list" aria-label="主导航">
        <RouterLink
          v-for="item in navItems"
          :key="item.path"
          :to="item.path"
          class="nav-item"
          :class="{ active: item.path === '/' ? route.path === '/' : route.path.startsWith(item.path) }"
        >
          <el-icon :size="19"><component :is="item.icon" /></el-icon>
          <span v-if="!sidebarCollapsed">{{ item.label }}</span>
        </RouterLink>
      </nav>

      <div v-if="!sidebarCollapsed" class="sidebar-note">个人学习空间</div>
    </aside>

    <main class="main-content" :class="{ 'tutor-page': route.path === '/tutor' }">
      <header class="topbar">
        <div>
          <h1>{{ route.meta.title }}</h1>
        </div>
        <button type="button" class="status-pill" :class="apiState" aria-label="检查 API 状态"
          title="检查后端 API 及数据库、任务队列、索引和存储是否就绪；点击重新检查" @click="checkApi"><i />{{ apiLabel }}</button>
        <el-button text @click="configureAccessToken">访问令牌</el-button>
      </header>
      <RouterView />
    </main>
  </div>
</template>
