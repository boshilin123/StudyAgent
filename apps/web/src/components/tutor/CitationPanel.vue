<script setup lang="ts">
import type { TutorCitation } from '@/api/tutoring'

defineProps<{ citations: TutorCitation[] }>()
</script>

<template>
  <details v-if="citations.length" class="tutor-citations">
    <summary>查看资料依据（{{ citations.length }}）</summary>
    <blockquote v-for="citation in citations" :key="citation.evidence_id">
      <strong>{{ citation.title }}</strong>
      <span v-if="citation.page_start != null"> · 第 {{ citation.page_start }} 页</span>
      <el-tag v-if="!citation.valid" type="warning" size="small">来源已失效</el-tag>
      <p>{{ citation.quote }}</p>
    </blockquote>
  </details>
</template>

<style scoped>
.tutor-citations { margin-top: 12px; font-size: 13px; }
summary { cursor: pointer; color: var(--el-color-primary); }
blockquote { margin: 12px 0 0; padding: 12px; border-left: 3px solid var(--el-border-color); background: var(--el-fill-color-light); }
p { white-space: pre-wrap; line-height: 1.7; margin-bottom: 0; }
</style>
