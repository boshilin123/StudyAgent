import { createRouter, createWebHistory } from 'vue-router'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: '/',
      name: 'home',
      component: () => import('@/views/HomeView.vue'),
      meta: { title: '学习概览' },
    },
    {
      path: '/knowledge-bases',
      name: 'knowledge-bases',
      component: () => import('@/views/KnowledgeBasesView.vue'),
      meta: { title: '知识库', description: '资料上传、解析状态与知识点管理' },
    },
    {
      path: '/questions',
      name: 'questions',
      component: () => import('@/views/QuestionBankView.vue'),
      meta: { title: '题库', description: '生成题目、核对来源并启用题目' },
    },
    {
      path: '/study',
      name: 'study',
      component: () => import('@/views/StudyView.vue'),
      meta: { title: '学习工作台', description: '诊断、练习、复习和模拟考试' },
    },
    {
      path: '/tutor',
      name: 'tutor',
      component: () => import('@/views/TutorView.vue'),
      meta: { title: '学习辅导', description: '资料问答、答后追问和薄弱点辅导' },
    },
    {
      path: '/progress',
      name: 'progress',
      component: () => import('@/views/ProgressView.vue'),
      meta: { title: '学习进度', description: '掌握度、答题历史和复习计划' },
    },
  ],
})

router.afterEach((to) => {
  document.title = `${String(to.meta.title ?? 'StudyAgent')} · StudyAgent`
})

export default router
