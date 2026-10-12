import { expect, test, type Page } from '@playwright/test'

async function setupProgress(page: Page) {
  const now = new Date().toISOString()
  const requests: URL[] = []
  const points = Array.from({ length: 12 }, (_, i) => ({
    knowledge_point_id: `point-${i + 1}`,
    knowledge_point_name: i === 0 ? 'RAG 检索与生成的职责边界' : `学习闭环第 ${i + 1} 个概念`,
    knowledge_base_id: 'kb1', mastery_score: 0.405, answered_count: 20,
    correct_count: 10, recent_accuracy: 0.5, confidence: 1, updated_at: now,
  }))
  const reviews = points.map((point, i) => ({
    ...point, id: `review-${i}`, due_at: now, interval_days: 1,
    repetitions: 1, ease_factor: 2.6, last_quality: 5, status: 'pending',
  }))
  const history = Array.from({ length: 121 }, (_, i) => ({
    id: `session-${i}`, knowledge_base_id: 'kb1', mode: i < 5 ? 'diagnostic' : 'practice',
    status: 'completed', planned_question_count: 2, answered_question_count: i < 120 ? 2 : 0,
    correct_count: i < 120 ? 1 : 0, total_score: 10, max_total_score: 20,
    started_at: now, finished_at: now, current_question: null,
  }))
  await page.route('**/api/**', async route => {
    const url = new URL(route.request().url())
    if (!url.pathname.startsWith('/api/')) {
      await route.continue()
      return
    }
    requests.push(url)
    const empty = url.searchParams.get('knowledge_base_id') === 'kb2'
    if (url.pathname === '/api/health/ready') await route.fulfill({ json: { status: 'ok' } })
    else if (url.pathname === '/api/knowledge-bases') await route.fulfill({ json: {
      items: [{ id: 'kb1', name: 'RAG 学习', status: 'active' },
        { id: 'kb2', name: '空知识库', status: 'active' }], total: 2,
    } })
    else if (url.pathname === '/api/mastery') await route.fulfill({ json: empty ? [] : points })
    else if (url.pathname === '/api/reviews/due') await route.fulfill({ json: empty ? [] : reviews })
    else if (url.pathname === '/api/study/history') {
      const index = Number(url.searchParams.get('page') || 1)
      const size = Number(url.searchParams.get('page_size'))
      await route.fulfill({ json: { items: empty ? [] : history.slice((index - 1) * size, index * size),
        total: empty ? 0 : history.length, page: index, page_size: size } })
    } else throw new Error(`Unexpected progress request: ${url.pathname}`)
  })
  return requests
}

test('知识点显示真实名称，三组列表各自每页5条且统计不随翻页变化', async ({ page }) => {
  const requests = await setupProgress(page)
  await page.goto('/progress')
  const mastery = page.getByRole('article', { name: '知识点掌握度', exact: true })
  const reviews = page.getByRole('article', { name: '复习计划', exact: true })
  const history = page.getByRole('region', { name: '学习历史', exact: true })
  await expect(mastery.getByText('RAG 检索与生成的职责边界', { exact: true })).toBeVisible()
  await expect(reviews.getByText('RAG 检索与生成的职责边界', { exact: true })).toBeVisible()
  await expect(page.getByText(/知识点 point-/)).toHaveCount(0)
  await expect(mastery.locator('.mastery-row')).toHaveCount(5)
  await expect(reviews.locator('.review-row')).toHaveCount(5)
  await expect(history.locator('tbody tr')).toHaveCount(5)
  await expect(page.getByText('121 次学习会话', { exact: true })).toBeVisible()
  const answered = page.locator('.metric-card').filter({ hasText: '累计答题' }).locator('strong')
  await expect(answered).toHaveText('240')
  await mastery.getByRole('navigation', { name: '掌握度分页' }).getByText('2', { exact: true }).click()
  await expect(mastery.getByText('学习闭环第 6 个概念', { exact: true })).toBeVisible()
  await expect(reviews.getByText('RAG 检索与生成的职责边界', { exact: true })).toBeVisible()
  await reviews.getByRole('navigation', { name: '复习分页' }).getByText('3', { exact: true }).click()
  await expect(reviews.locator('.review-row')).toHaveCount(2)
  await history.getByRole('navigation', { name: '学习历史分页' }).getByText('2', { exact: true }).click()
  await expect(history.getByText('练习', { exact: true })).toHaveCount(5)
  await expect(answered).toHaveText('240')
  expect(requests.filter(url => url.pathname === '/api/study/history')
    .every(url => url.searchParams.get('page_size') === '5')).toBe(true)
  expect(requests.some(url => url.pathname === '/api/study/history'
    && url.searchParams.get('page') === '2')).toBe(true)
  await page.screenshot({ path: '../../tmp/progress-pagination.png', fullPage: true })
})

test('切换知识库重置分页，空列表不残留旧知识点和统计', async ({ page }) => {
  await setupProgress(page)
  await page.goto('/progress')
  const mastery = page.getByRole('article', { name: '知识点掌握度', exact: true })
  await mastery.getByRole('navigation', { name: '掌握度分页' }).getByText('3', { exact: true }).click()
  await page.locator('.progress-filter .el-select__wrapper').click()
  await page.getByRole('option', { name: '空知识库' }).click()
  await expect(mastery.getByText('完成练习后生成掌握度', { exact: true })).toBeVisible()
  await expect(page.getByText('0 次学习会话', { exact: true })).toBeVisible()
  await expect(page.getByRole('navigation', { name: /分页/ })).toHaveCount(0)
  await page.locator('.progress-filter .el-select__wrapper').click()
  await page.getByRole('option', { name: 'RAG 学习' }).click()
  await expect(mastery.getByText('RAG 检索与生成的职责边界', { exact: true })).toBeVisible()
  await expect(mastery.locator('.mastery-row')).toHaveCount(5)
})
