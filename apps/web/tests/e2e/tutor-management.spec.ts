import { expect, test, type Page } from '@playwright/test'

// Real Vue interactions; isolated HTTP fixtures make no paid model requests.
async function managementFixture(page: Page, count = 2, reject = false) {
  const rows = Array.from({ length: count }, (_, i) => ({
    id: `conversation-${i + 1}`, title: `会话${i + 1}`, knowledge_base_id: 'kb1',
    study_session_id: null, answered_question_id: null,
    status: i === 0 ? 'archived' : 'active', created_at: '2026-10-02T07:00:00Z',
  }))
  const writes: string[] = []
  await page.route('**/api/**', async route => {
    const request = route.request()
    const url = new URL(request.url())
    if (!url.pathname.startsWith('/api/')) {
      await route.continue()
      return
    }
    if (request.method() !== 'GET') writes.push(request.method() + ' ' + url.pathname)
    if (url.pathname === '/api/knowledge-bases') {
      await route.fulfill({ json: { items: [{ id: 'kb1', name: '测试知识库', status: 'active' }], total: 1 } })
    } else if (url.pathname === '/api/tutor/conversations') {
      const offset = (Number(url.searchParams.get('page') || '1') - 1) * 20
      await route.fulfill({ json: { items: rows.slice(offset, offset + 20), total: rows.length, page_size: 20 } })
    } else if (url.pathname.startsWith('/api/tutor/conversations/')) {
      const id = url.pathname.split('/')[4]
      const row = rows.find(item => item.id === id)
      if (!row) await route.fulfill({ status: 404, json: { error: { message: '辅导会话不存在' } } })
      else if (request.method() === 'GET') await route.fulfill({ json: {
        conversation: row, messages: [{ id: `message-${id}`, role: 'assistant',
          sequence: 1, content: `${row.title}历史`, citations: [] }], total: 1,
      } })
      else if (reject) await route.fulfill({ status: 409, json: {
        error: { code: 'TUTOR_THREAD_BUSY', message: '会话运行中，暂不能修改' },
      } })
      else if (request.method() === 'PATCH') {
        row.title = request.postDataJSON().title
        await route.fulfill({ json: row })
      } else if (request.method() === 'DELETE') {
        rows.splice(rows.indexOf(row), 1)
        await route.fulfill({ status: 204 })
      } else throw new Error(`Unexpected write: ${request.method()} ${url.pathname}`)
    } else await route.fulfill({ json: { status: 'ok' } })
  })
  return { rows, writes }
}

test('归档与使用中会话重命名：取消、空名称、长度上限、刷新持久化', async ({ page }) => {
  const fixture = await managementFixture(page)
  await page.goto('/tutor')
  const first = page.locator('.conversation-item').filter({ hasText: '会话1' })
  await first.getByRole('button', { name: '重命名会话 会话1', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: '重命名会话', exact: true })
  await dialog.getByRole('textbox', { name: '会话名称' }).fill('取消名称')
  await dialog.getByRole('button', { name: '取消', exact: true }).click()
  expect(fixture.writes).toEqual([])
  await first.getByRole('button', { name: '重命名会话 会话1', exact: true }).click()
  await dialog.getByRole('textbox', { name: '会话名称' }).fill('  ')
  await expect(dialog.getByRole('button', { name: '保存名称' })).toBeDisabled()
  await dialog.getByRole('textbox', { name: '会话名称' }).fill('名'.repeat(110))
  await expect(dialog.getByRole('textbox', { name: '会话名称' })).toHaveValue('名'.repeat(100))
  await dialog.getByRole('textbox', { name: '会话名称' }).fill('  聚时接口复习  ')
  await dialog.getByRole('button', { name: '保存名称' }).click()
  await expect(first).toHaveCount(0)
  await page.getByRole('button', { name: '聚时接口复习 已归档', exact: true }).click()
  await expect(page.getByRole('heading', { name: '聚时接口复习', exact: true })).toBeVisible()
  await page.reload()
  await expect(page.getByRole('heading', { name: '聚时接口复习', exact: true })).toBeVisible()
  await page.getByRole('button', { name: '重命名会话 聚时接口复习', exact: true }).click()
  await dialog.getByRole('textbox', { name: '会话名称' }).fill('再次修改')
  await dialog.getByRole('button', { name: '保存名称' }).click()
  await expect(page.getByRole('heading', { name: '再次修改', exact: true })).toBeVisible()
  await page.getByRole('button', { name: '重命名会话 会话2', exact: true }).click()
  await dialog.getByRole('textbox', { name: '会话名称' }).fill('使用中名称')
  await dialog.getByRole('button', { name: '保存名称' }).click()
  await expect(page.getByRole('button', { name: '使用中名称 可继续', exact: true })).toBeVisible()
  expect(fixture.rows[0]?.status).toBe('archived')
  expect(fixture.writes.every(item => item.startsWith('PATCH '))).toBe(true)
})

test('删除取消、删除当前自动切换、删除最后一项清除存储和刷新空列表', async ({ page }) => {
  const fixture = await managementFixture(page)
  await page.goto('/tutor')
  await page.getByRole('button', { name: '会话1 已归档', exact: true }).click()
  await page.getByRole('button', { name: '删除会话 会话1', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: '删除辅导会话', exact: true })
  await dialog.getByRole('button', { name: '取消', exact: true }).click()
  expect(fixture.writes).toEqual([])
  await page.getByRole('button', { name: '删除会话 会话1', exact: true }).click()
  await dialog.getByRole('button', { name: '确认删除', exact: true }).click()
  await expect(page.getByRole('heading', { name: '会话2', exact: true })).toBeVisible()
  await expect(page.locator('.conversation-item')).toHaveCount(1)
  await page.reload()
  await expect(page.getByRole('heading', { name: '会话2', exact: true })).toBeVisible()
  await page.getByRole('button', { name: '删除会话 会话2', exact: true }).click()
  await dialog.getByRole('button', { name: '确认删除', exact: true }).click()
  await expect(page.getByText('暂无辅导会话。')).toBeVisible()
  await expect(page.locator('.tutor-message')).toHaveCount(0)
  expect(await page.evaluate(() => localStorage.getItem('study-agent-tutor-conversation'))).toBeNull()
  await page.reload()
  await expect(page.getByText('暂无辅导会话。')).toBeVisible()
  expect(fixture.writes).toHaveLength(2)
  expect(fixture.writes.every(item => item.startsWith('DELETE '))).toBe(true)
})

test('删除非当前会话保留当前历史', async ({ page }) => {
  const fixture = await managementFixture(page, 21)
  await page.goto('/tutor')
  await page.getByRole('button', { name: '会话1 已归档', exact: true }).click()
  await page.getByRole('button', { name: '删除会话 会话2', exact: true }).click()
  await page.getByRole('button', { name: '确认删除', exact: true }).click()
  await expect(page.getByRole('heading', { name: '会话1', exact: true })).toBeVisible()
  await expect(page.locator('.tutor-message')).toContainText('会话1历史')
  expect(fixture.rows).toHaveLength(20)
})

test('最后一页仅剩一项，删除后加载上一页', async ({ page }) => {
  await managementFixture(page, 21)
  await page.goto('/tutor')
  await page.locator('.tutor-sidebar .btn-next').click()
  await page.getByRole('button', { name: '删除会话 会话21', exact: true }).click()
  await page.getByRole('button', { name: '确认删除', exact: true }).click()
  await expect(page.locator('.conversation-item')).toHaveCount(20)
  await expect(page.getByRole('button', { name: '会话1 已归档', exact: true })).toBeVisible()
})

test('服务端冲突保留原名称和会话，并在弹窗展示原因', async ({ page }) => {
  const fixture = await managementFixture(page, 1, true)
  await page.goto('/tutor')
  await page.getByRole('button', { name: '重命名会话 会话1', exact: true }).click()
  await page.getByRole('textbox', { name: '会话名称' }).fill('不会保存')
  await page.getByRole('button', { name: '保存名称' }).click()
  await expect(page.getByRole('dialog').getByText('会话运行中，暂不能修改')).toBeVisible()
  await page.getByRole('button', { name: '取消', exact: true }).click()
  await page.getByRole('button', { name: '删除会话 会话1', exact: true }).click()
  await page.getByRole('button', { name: '确认删除', exact: true }).click()
  await expect(page.getByRole('dialog').getByText('会话运行中，暂不能修改')).toBeVisible()
  expect(fixture.rows[0]?.title).toBe('会话1')
  expect(fixture.rows).toHaveLength(1)
})

test('恢复指向已删除会话的本地存储，清除待确认消息并加载剩余列表', async ({ page }) => {
  const fixture = await managementFixture(page, 1)
  await page.addInitScript(() => {
    localStorage.setItem('study-agent-tutor-conversation', 'deleted-conversation')
    localStorage.setItem('study-agent-tutor-pending-message', JSON.stringify({
      conversation_id: 'deleted-conversation', client_message_id: 'old-message',
      content: '旧问题', intent: 'materials', turn_id: 'old-turn',
    }))
  })
  await page.goto('/tutor')
  await expect(page.getByRole('button', { name: '会话1 已归档', exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: '恢复待确认消息' })).toHaveCount(0)
  expect(await page.evaluate(() => localStorage.getItem('study-agent-tutor-pending-message'))).toBeNull()
  expect(await page.evaluate(() => localStorage.getItem('study-agent-tutor-conversation'))).toBeNull()
  expect(fixture.writes).toEqual([])
})
