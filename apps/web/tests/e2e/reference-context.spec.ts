import { expect, test } from '@playwright/test'

test('出题参考原文可展开，展示资料页码并保留旧引文类型', async ({ page }) => {
  const question = {
    id: 'q1', knowledge_base_id: 'kb1', knowledge_point_id: 'p1', question_type: 'true_false',
    stem: 'TCP通过三次握手建立连接。', options: null, correct_answer: ['正确'],
    scoring_points: [], explanation: '请结合参考原文核对连接建立过程。', difficulty: 2,
    max_score: 10, status: 'draft', vector_id: 'q1',
    sources: [
      { chunk_id: 'c1', quote: 'TCP通过三次握手建立连接。UDP是无连接协议。', rank: 1,
        source_kind: 'reference_context', material_title: '网络学习资料', page_start: 3, page_end: 4,
        heading_path: ['传输层', 'TCP与UDP'] },
      { chunk_id: 'c2', quote: '这是旧版本保留的原文引文。', rank: 2, source_kind: 'quote',
        material_title: '旧资料', page_start: 8, page_end: 8, heading_path: [] },
    ],
  }
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname
    if (!path.startsWith('/api/')) return route.continue()
    if (path === '/api/health/ready') await route.fulfill({ json: { status: 'ok' } })
    else if (path === '/api/knowledge-bases') await route.fulfill({ json: { items: [
      { id: 'kb1', name: '网络知识库', status: 'active', material_count: 1, question_count: 1 },
    ], total: 1 } })
    else if (path === '/api/questions') await route.fulfill({ json: { items: [question], total: 1 } })
    else await route.fulfill({ json: { items: [], total: 0 } })
  })
  await page.goto('/questions')
  await page.getByRole('heading', { name: question.stem, exact: true }).click()
  const drawer = page.locator('.el-drawer')
  await expect(drawer.getByText('出题参考原文', { exact: true })).toBeVisible()
  await expect(drawer.getByText('请结合参考原文核对答案与解析，审核后再启用。')).toBeVisible()
  await expect(drawer.getByText(question.sources[0].quote, { exact: true })).not.toBeVisible()
  await drawer.locator('summary').filter({ hasText: '网络学习资料' }).click()
  await expect(drawer.getByText(question.sources[0].quote, { exact: true })).toBeVisible()
  await expect(drawer.getByText('传输层 / TCP与UDP', { exact: true })).toBeVisible()
  await expect(drawer.locator('summary').filter({ hasText: '网络学习资料' })).toContainText('第 3–4 页')
  await expect(drawer.locator('summary').filter({ hasText: '网络学习资料' })).toContainText('出题上下文')
  await expect(drawer.locator('summary').filter({ hasText: '旧资料' })).toContainText('原文引文')
  await drawer.locator('summary').filter({ hasText: '旧资料' }).click()
  await expect(drawer.getByText(question.sources[1].quote, { exact: true })).toBeVisible()
})
