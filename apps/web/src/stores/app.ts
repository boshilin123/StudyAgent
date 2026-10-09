import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

// 侧栏折叠状态由 Pinia 共享，布局和按钮都读取同一份状态。
export const useAppStore = defineStore('app', () => {
  const sidebarCollapsed = ref(false)
  const sidebarWidth = computed(() => (sidebarCollapsed.value ? '72px' : '232px'))

  function toggleSidebar() {
    sidebarCollapsed.value = !sidebarCollapsed.value
  }

  return { sidebarCollapsed, sidebarWidth, toggleSidebar }
})
