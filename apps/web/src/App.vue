<script setup lang="ts">
import { Collection, DataAnalysis, HomeFilled, Reading } from '@element-plus/icons-vue'
import { storeToRefs } from 'pinia'
import { useRoute } from 'vue-router'

import { useAppStore } from '@/stores/app'

const route = useRoute()
const appStore = useAppStore()
const { sidebarCollapsed, sidebarWidth } = storeToRefs(appStore)

const navItems = [
  { path: '/', label: '学习概览', icon: HomeFilled },
  { path: '/knowledge-bases', label: '知识库', icon: Collection },
  { path: '/questions', label: '题库', icon: Reading },
  { path: '/study', label: '学习工作台', icon: Reading },
  { path: '/progress', label: '学习进度', icon: DataAnalysis },
]
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

      <div v-if="!sidebarCollapsed" class="sidebar-note">个人学习空间 · MVP</div>
    </aside>

    <main class="main-content">
      <header class="topbar">
        <div>
          <p class="eyebrow">PERSONAL LEARNING OS</p>
          <h1>{{ route.meta.title }}</h1>
        </div>
        <span class="status-pill"><i /> 服务已连接</span>
      </header>
      <RouterView />
    </main>
  </div>
</template>
