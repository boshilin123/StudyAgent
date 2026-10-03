import { expect, test, type Page } from '@playwright/test'

async function setupQuestions(page: Page, failDeletion = false) {
  let items = [{ id: 'q1', knowledge_base_id: 'kb1', knowledge_point_id: 'p1',
    question_type: 'true_false', stem: '部署接口可以自动创建容器。', options: null,
    correct_answer: ['正确'], explanation: '资料中有相应接口。', difficulty: 2,
    max_score: 10, status: 'active', sources: [{ chunk_id: 'c1', quote: '部署接口', rank: 1 }] }]
  const deletions: string[] = []
  await page.route('**/api/**', async route => {
    const url = new URL(route.request().url())
    if (!url.pathname.startsWith('/api/')) return route.continue()
    if (url.pathname === '/api/health/ready') return route.fulfill({ json: { status: 'ok' } })
    if (url.pathname === '/api/knowledge-bases') return route.fulfill({ json: {
      items: [{ id: 'kb1', name: '聚时', status: 'active', question_count: items.length }], total: 1,
    } })
    if (url.pathname === '/api/questions/q1' && route.request().method() === 'DELETE') {
      deletions.push('q1')
      if (failDeletion) return route.fulfill({ status: 503, json: { error: {
        code: 'UNAVAILABLE', message: '服务暂时不可用，请重试',
      } } })
      items = []
      return route.fulfill({ status: 204 })
    }
    if (url.pathname === '/api/questions') return route.fulfill({ json: {
      items, total: items.length, page: 1, page_size: 100,
    } })
    await route.fulfill({ json: { items: [], total: 0 } })
  })
  return deletions
}

test('卡片删除可取消，确认后刷新数量且不会再显示已删除题目', async ({ page }) => {
  const deletions = await setupQuestions(page)
  await page.goto('/questions?knowledge_base_id=kb1')
  const card = page.locator('.question-card')
  await expect(card).toHaveCount(1)
  await card.getByRole('button', { name: '删除', exact: true }).click()
  await expect(page.getByText(/已有作答和学习历史会保留/)).toBeVisible()
  await page.getByRole('button', { name: '取消', exact: true }).click()
  expect(deletions).toEqual([])
  await expect(card).toHaveCount(1)
  await card.getByRole('button', { name: '删除', exact: true }).click()
  await page.locator('.el-message-box').getByRole('button', { name: '删除', exact: true }).click()
  await expect(card).toHaveCount(0)
  await expect(page.locator('.metric-card strong').first()).toHaveText('0')
  await page.reload()
  await expect(card).toHaveCount(0)
  expect(deletions).toEqual(['q1'])
})

test('题目详情中的删除成功后关闭抽屉', async ({ page }) => {
  await setupQuestions(page)
  await page.goto('/questions')
  await page.locator('.question-card h3').click()
  const drawer = page.locator('.el-drawer')
  await expect(drawer.getByText('标准答案', { exact: true })).toBeVisible()
  await drawer.getByRole('button', { name: '删除题目', exact: true }).click()
  await page.locator('.el-message-box').getByRole('button', { name: '删除', exact: true }).click()
  await expect(drawer).not.toBeVisible()
  await expect(page.locator('.question-card')).toHaveCount(0)
})

test('删除请求失败时显示错误并保留题目供重试', async ({ page }) => {
  await setupQuestions(page, true)
  await page.goto('/questions')
  await page.locator('.question-card').getByRole('button', { name: '删除', exact: true }).click()
  await page.locator('.el-message-box').getByRole('button', { name: '删除', exact: true }).click()
  await expect(page.getByText('服务暂时不可用，请重试', { exact: true })).toBeVisible()
  await expect(page.locator('.question-card')).toHaveCount(1)
})
