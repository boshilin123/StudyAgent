<script setup lang="ts">
import { useRoute } from 'vue-router'

const route = useRoute()
</script>

<template>
  <section class="placeholder-card">
    <span class="section-kicker">MODULE SCAFFOLD</span>
    <h2>{{ route.meta.title }}</h2>
    <p>{{ route.meta.description }}</p>
    <div class="empty-state">
      <span>框架已就绪</span>
      <small>对应业务将在后续实施阶段接入</small>
    </div>
  </section>
</template>
