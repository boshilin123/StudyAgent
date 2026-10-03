import { expect, test, type Page } from '@playwright/test'

// Long conversations use isolated HTTP fixtures; no model provider is contacted.
async function scrollFixture(page: Page, turns = 10, delayed = false, archived = false) {
  const conversation = { id: 'scroll-conversation', title: '连续问答', knowledge_base_id: 'kb1',
    study_session_id: null, answered_question_id: null, status: archived ? 'archived' : 'active',
    created_at: '2026-10-02T08:00:00Z' }
  const quote = { evidence_id: 'e1', material_id: 'm1', chunk_id: 'c1', title: '测试资料',
    page_start: 1, page_end: 1, quote: '引用内容\n'.repeat(50), content_hash: 'a'.repeat(64), valid: true }
  const messages = Array.from({ length: turns * 2 }, (_, i) => ({
    id: `history-${i}`, turn_id: `turn-${Math.floor(i / 2)}`, sequence: i + 1,
    role: i % 2 ? 'assistant' : 'user', content: i % 2
      ? `历史回复${i}\n${'接口说明与示例内容。\n'.repeat(35)}` : `历史问题${i}`,
    citations: i % 2 ? [quote] : [], created_at: conversation.created_at,
  }))
  let release = () => {}
  const gate = new Promise<void>(resolve => { release = resolve })
  let submits = 0
  await page.addInitScript(() => localStorage.setItem('study-agent-tutor-conversation', 'scroll-conversation'))
  await page.route('**/api/**', async route => {
    const request = route.request()
    const url = new URL(request.url())
    if (!url.pathname.startsWith('/api/')) { await route.continue(); return }
    if (url.pathname === '/api/knowledge-bases') await route.fulfill({ json: {
      items: [{ id: 'kb1', name: '滚动验收资料', status: 'active' }], total: 1,
    } })
    else if (url.pathname === '/api/tutor/conversations') await route.fulfill({ json: {
      items: Array.from({ length: 20 }, (_, i) => ({ ...conversation, id: i ? `other-${i}` : conversation.id,
        title: i ? `其他会话${i}` : conversation.title })), total: 20,
    } })
    else if (url.pathname.endsWith('/messages')) {
      submits += 1
      if (delayed) await gate
      const input = request.postDataJSON()
      const answer = `新增回复${submits}\n${'新回复内容及资料说明。\n'.repeat(40)}`
      messages.push({ id: `sent-${submits}`, turn_id: `new-${submits}`, sequence: messages.length + 1,
        role: 'user', content: input.content, citations: [], created_at: conversation.created_at })
      messages.push({ id: `reply-${submits}`, turn_id: `new-${submits}`, sequence: messages.length + 1,
        role: 'assistant', content: answer, citations: [quote], created_at: conversation.created_at })
      await route.fulfill({ json: { turn_id: `new-${submits}`, status: 'completed', message: answer,
        answer_status: 'answered', citations: [quote], suggestions: ['先复习相关接口'],
        suggested_questions: ['进一步解释'], usage: { known: true, total_tokens: 100, model_calls: 2, tool_calls: 1 },
        error_code: null, error_message: null, idempotent_replay: false } })
    } else if (url.pathname === '/api/tutor/conversations/scroll-conversation') {
      const offset = (Number(url.searchParams.get('page') || '1') - 1) * 50
      await route.fulfill({ json: { conversation, messages: messages.slice(offset, offset + 50),
        total: messages.length, page: offset / 50 + 1, page_size: 50 } })
    } else await route.fulfill({ json: { status: 'ok' } })
  })
  return { release, getSubmits: () => submits }
}

async function layoutMetrics(page: Page) {
  return page.evaluate(() => {
    const history = document.querySelector<HTMLElement>('.tutor-history')!
    const chat = document.querySelector<HTMLElement>('.tutor-chat')!
    const input = document.querySelector<HTMLElement>('.tutor-compose')
    return { outerHeight: document.documentElement.scrollHeight, viewportHeight: innerHeight,
      chatBottom: chat.getBoundingClientRect().bottom, chatHeight: chat.getBoundingClientRect().height,
      inputBottom: input?.getBoundingClientRect().bottom,
      historyHeight: history.clientHeight, scrollHeight: history.scrollHeight, top: history.scrollTop,
      gap: history.scrollHeight - history.scrollTop - history.clientHeight }
  })
}

for (const viewport of [{ width: 1365, height: 768 }, { width: 1080, height: 600 }, { width: 840, height: 900 }]) {
  test(`连续长回复保持固定面板和可见输入框 ${viewport.width}×${viewport.height}`, async ({ page }) => {
    await page.setViewportSize(viewport)
    await scrollFixture(page)
    await page.goto('/tutor')
    await expect(page.locator('.tutor-message')).toHaveCount(20)
    await expect.poll(async () => (await layoutMetrics(page)).gap).toBeLessThanOrEqual(2)
    const before = await layoutMetrics(page)
    expect(before.scrollHeight).toBeGreaterThan(before.historyHeight)
    for (let i = 1; i <= 3; i++) {
      await page.getByRole('textbox', { name: '辅导问题', exact: true }).fill(`追问${i}`)
      await page.getByRole('button', { name: '发送问题', exact: true }).click()
      await expect(page.locator('.tutor-message')).toHaveCount(20 + i * 2)
      await expect.poll(async () => (await layoutMetrics(page)).gap).toBeLessThanOrEqual(2)
      const after = await layoutMetrics(page)
      expect(after.outerHeight).toBeLessThanOrEqual(viewport.height + 1)
      expect(after.chatBottom).toBeLessThanOrEqual(viewport.height)
      expect(after.inputBottom).toBeLessThanOrEqual(viewport.height)
      expect(Math.abs(after.chatHeight - before.chatHeight)).toBeLessThanOrEqual(1)
    }
    await page.setViewportSize({ width: viewport.width, height: viewport.height + 100 })
    await expect.poll(async () => (await layoutMetrics(page)).gap).toBeLessThanOrEqual(2)
    await page.reload()
    await expect(page.locator('.tutor-message')).toHaveCount(26)
    await expect.poll(async () => (await layoutMetrics(page)).gap).toBeLessThanOrEqual(2)
    await expect(page.getByRole('textbox', { name: '辅导问题', exact: true })).toBeInViewport()
  })
}

test('等待回复时翻看历史保留位置，最新入口跳到底部，引用展开不会撑高页面', async ({ page }) => {
  await page.setViewportSize({ width: 1365, height: 768 })
  const fixture = await scrollFixture(page, 10, true)
  await page.goto('/tutor')
  await expect(page.locator('.tutor-message')).toHaveCount(20)
  await page.getByRole('textbox', { name: '辅导问题', exact: true }).fill('继续解释')
  await page.getByRole('button', { name: '发送问题', exact: true }).click()
  await expect(page.getByRole('button', { name: '发送问题', exact: true })).toBeDisabled()
  await page.getByRole('region', { name: '辅导消息记录' }).evaluate(element => { element.scrollTop = 0 })
  await expect.poll(async () => (await layoutMetrics(page)).top).toBe(0)
  // Wait for the actual browser scroll event before releasing the HTTP response.
  await page.getByRole('region', { name: '辅导消息记录' }).dispatchEvent('scroll')
  fixture.release()
  await expect(page.locator('.tutor-message')).toHaveCount(22)
  await expect(page.getByRole('button', { name: '查看最新回复', exact: true })).toBeVisible()
  expect((await layoutMetrics(page)).top).toBe(0)
  await page.locator('.tutor-citations summary').first().click()
  expect((await layoutMetrics(page)).outerHeight).toBeLessThanOrEqual(769)
  await expect(page.getByRole('textbox', { name: '辅导问题', exact: true })).toBeInViewport()
  await page.getByRole('button', { name: '查看最新回复', exact: true }).click()
  await expect.poll(async () => (await layoutMetrics(page)).gap).toBeLessThanOrEqual(2)
  await expect(page.getByRole('button', { name: '查看最新回复', exact: true })).toHaveCount(0)
  expect(fixture.getSubmits()).toBe(1)
})

test('历史分页定位页首，新提问完成后切换最新页', async ({ page }) => {
  await scrollFixture(page, 40)
  await page.goto('/tutor')
  await expect(page.locator('.tutor-message')).toHaveCount(30)
  await expect.poll(async () => (await layoutMetrics(page)).gap).toBeLessThanOrEqual(2)
  await page.getByRole('listitem', { name: 'page 1', exact: true }).click()
  await expect(page.locator('.tutor-message').first()).toContainText('历史问题0')
  await expect.poll(async () => (await layoutMetrics(page)).top).toBe(0)
  await page.getByRole('textbox', { name: '辅导问题', exact: true }).fill('从历史页发起追问')
  await page.getByRole('button', { name: '发送问题', exact: true }).click()
  await expect(page.locator('.tutor-message').last()).toContainText('新增回复1')
  await expect(page.locator('.tutor-message')).toHaveCount(32)
  await expect.poll(async () => (await layoutMetrics(page)).gap).toBeLessThanOrEqual(2)
})

test('归档会话长历史与侧栏各自滚动，页面高度保持在视口内', async ({ page }) => {
  await page.setViewportSize({ width: 1365, height: 768 })
  await scrollFixture(page, 10, false, true)
  await page.goto('/tutor')
  await expect(page.locator('.tutor-message')).toHaveCount(20)
  await expect(page.getByRole('textbox', { name: '辅导问题', exact: true })).toHaveCount(0)
  expect((await layoutMetrics(page)).outerHeight).toBeLessThanOrEqual(769)
  const sidebar = page.getByRole('navigation', { name: '辅导会话', exact: true })
  expect(await sidebar.evaluate(element => element.scrollHeight > element.clientHeight)).toBe(true)
  await sidebar.evaluate(element => { element.scrollTop = element.scrollHeight })
  await expect(page.getByRole('button', { name: '其他会话19 已归档', exact: true })).toBeInViewport()
  expect((await layoutMetrics(page)).outerHeight).toBeLessThanOrEqual(769)
})
