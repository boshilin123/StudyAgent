import { expect, test, type Page } from '@playwright/test'

// These tests verify real Vue/browser recovery against an explicit HTTP fixture.
// They do not claim to test PostgreSQL or a live model provider.
const NOW = '2026-10-01T08:00:00Z'
type Mode = 'success' | 'running' | 'lost' | 'failed' | 'disabled' | 'unsafe' | 'insufficient' | 'busy'

async function mockTutor(page: Page, mode: Mode = 'success') {
  const ids: string[] = []
  const created: Record<string, unknown>[] = []
  const replay = new Map<string, Record<string, unknown>>()
  const messages: Record<string, unknown>[] = []
  let conversation = { id: 'tutor-1', knowledge_base_id: 'kb1', study_session_id: null as string | null,
    answered_question_id: null as string | null, status: 'active', created_at: NOW }
  let made = false
  let pollCount = 0
  const studyQuestion = { id: 'answered-question-1', sequence: 1, question_type: 'true_false',
    stem: 'TCP三次握手判断题', options: null, difficulty: 2, max_score: 10, selection_reason: null }
  const studySession = { id: 'study-session-1', knowledge_base_id: 'kb1', mode: 'practice', status: 'active',
    planned_question_count: 2, answered_question_count: 0, correct_count: 0, incorrect_count: 0,
    total_score: 0, max_total_score: 0, started_at: NOW, finished_at: null, current_question: studyQuestion }
  const citation = { evidence_id: 'e1', material_id: 'm1', chunk_id: 'c1', title: 'TCP资料',
    page_start: 2, page_end: 2, quote: '三次握手用于确认双方收发能力。', content_hash: 'a'.repeat(64), valid: true }
  const response = (id: string) => ({ turn_id: id, status: 'completed',
    message: mode === 'unsafe' ? '<img src="https://invalid.example/x" onerror="window.pwned=1"><script>window.pwned=1</script>' : '这是当前资料中的解释。',
    answer_status: mode === 'insufficient' ? 'insufficient_evidence' : 'answered', mode: 'agent',
    citations: mode === 'insufficient' ? [] : [citation], suggestions: ['先复习握手流程（仅为建议）'],
    suggested_questions: ['再解释第二个概念'], usage: { model_calls: 2, tool_calls: 1, total_tokens: null, known: false },
    idempotent_replay: false, error_code: null, error_message: null })
  const commit = (body: Record<string, string>, result: ReturnType<typeof response>) => {
    if (!messages.some(item => item.turn_id === result.turn_id)) {
      messages.push({ id: 'user-' + result.turn_id, turn_id: result.turn_id, role: 'user', content: body.content,
        citations: [], sequence: messages.length + 1, created_at: NOW })
      messages.push({ id: 'assistant-' + result.turn_id, turn_id: result.turn_id, role: 'assistant', content: result.message,
        citations: result.citations, sequence: messages.length + 1, created_at: NOW })
    }
  }
  await page.route('**/api/**', async route => {
    const request = route.request()
    const path = new URL(request.url()).pathname
    if (!path.startsWith('/api/')) {
      await route.continue()
      return
    }
    if (path.endsWith('/knowledge-bases')) {
      await route.fulfill({ json: { items: [{ id: 'kb1', name: '验收知识库', status: 'active' }], total: 1 } })
    } else if (path.endsWith('/study/sessions') && request.method() === 'POST') {
      await route.fulfill({ status: 201, json: studySession })
    } else if (path.endsWith('/answers')) {
      const body = request.postDataJSON()
      await route.fulfill({ json: { submission_id: body.submission_id, question_id: studyQuestion.id,
        verdict: 'correct', score: 10, max_score: 10, feedback: '回答正确', explanation: '题库解释',
        idempotent_replay: false, session: { ...studySession, answered_question_count: 1,
          correct_count: 1, total_score: 10, max_total_score: 10,
          current_question: { ...studyQuestion, id: 'next-question-2', sequence: 2 } },
        rag_explanation: { conclusion: '正确', gap: '测试解释', provider: 'question_bank', status: 'fallback', evidence: [] },
        mastery: { mastery_score: 0.6 }, review_task: { due_at: NOW } } })
    } else if (path.endsWith('/tutor/conversations') && request.method() === 'POST') {
      if (mode === 'disabled') {
        await route.fulfill({ status: 503, json: { error: { code: 'TUTOR_DISABLED', message: '学习辅导暂未启用' } } })
        return
      }
      const body = request.postDataJSON()
      created.push(body)
      conversation = { ...conversation, study_session_id: body.study_session_id || null,
        answered_question_id: body.answered_question_id || null }
      made = true
      await route.fulfill({ status: 201, json: conversation })
    } else if (path.endsWith('/tutor/conversations')) {
      await route.fulfill({ json: { items: made ? [conversation] : [], total: made ? 1 : 0, page: 1, page_size: 20 } })
    } else if (path.endsWith('/messages')) {
      const body = request.postDataJSON()
      ids.push(body.client_message_id)
      const stored = replay.get(body.client_message_id)
      if (stored) {
        await route.fulfill({ json: { ...stored, idempotent_replay: true } })
        return
      }
      const result = response('turn-' + ids.length)
      if (mode === 'failed' && ids.length === 1) {
        await route.fulfill({ json: { ...result, status: 'failed', message: null,
          error_code: 'TUTOR_BUDGET_EXCEEDED', error_message: '本轮调用预算已耗尽' } })
        return
      }
      replay.set(body.client_message_id, result)
      commit(body, result)
      if (mode === 'busy' && ids.length === 1) await route.fulfill({ status: 409,
        json: { error: { code: 'TUTOR_THREAD_BUSY', message: '正在处理，请恢复同条消息' } } })
      else if (mode === 'lost' && ids.length === 1) await route.abort('connectionreset')
      else if (mode === 'running' && ids.length === 1) await route.fulfill({ status: 202, json: { ...result, status: 'running', message: null } })
      else await route.fulfill({ json: result })
    } else if (path.includes('/turns/')) {
      pollCount += 1
      await route.fulfill({ json: { id: 'turn-1', status: 'completed', client_message_id: ids[0],
        response: replay.get(ids[0]!), error_code: null, error_message: null } })
    } else if (path.endsWith('/archive')) {
      conversation.status = 'archived'
      await route.fulfill({ json: conversation })
    } else if (path.endsWith('/tutor/conversations/tutor-1')) {
      await route.fulfill({ json: { conversation, messages, page: 1, page_size: 50, total: messages.length } })
    } else await route.fulfill({ json: { items: [], total: 0 } })
  })
  return { ids, created, getPollCount: () => pollCount }
}

async function start(page: Page) {
  await page.goto('/tutor')
  await page.getByRole('button', { name: '新建辅导会话' }).click()
  await expect(page.getByRole('button', { name: '归档会话' })).toBeVisible()
}
async function send(page: Page, content = '解释三次握手') {
  await page.getByRole('textbox', { name: '辅导问题', exact: true }).fill(content)
  await page.getByRole('button', { name: '发送问题' }).click()
}

test('辅导完整交互：资料依据、追问、用量unknown和归档历史', async ({ page }) => {
  const fixture = await mockTutor(page)
  await start(page)
  await send(page)
  await expect(page.getByText('这是当前资料中的解释。', { exact: true })).toBeVisible()
  await page.getByText('查看资料依据（1）', { exact: true }).click()
  await expect(page.getByText('三次握手用于确认双方收发能力。')).toBeVisible()
  await expect(page.getByText('Token 用量不可用', { exact: false })).toBeVisible()
  await page.getByRole('button', { name: '再解释第二个概念' }).click()
  await page.getByRole('button', { name: '发送问题' }).click()
  await expect(page.locator('.tutor-message.assistant')).toHaveCount(2)
  expect(fixture.ids[0]).not.toBe(fixture.ids[1])
  await page.getByRole('button', { name: '归档会话' }).click()
  await expect(page.getByText('会话已归档，历史仍可查看。请新建会话继续辅导。')).toBeVisible()
  await expect(page.getByRole('button', { name: '发送问题' })).toHaveCount(0)
  await page.reload()
  await expect(page.locator('.tutor-message.assistant')).toHaveCount(2)
})

test('202运行轮次自动查询，并阻止第二次发送', async ({ page }) => {
  const fixture = await mockTutor(page, 'running')
  await start(page)
  await send(page)
  await expect(page.getByRole('button', { name: '发送问题' })).toBeDisabled()
  await expect(page.getByText('这是当前资料中的解释。', { exact: true })).toBeVisible({ timeout: 8000 })
  expect(fixture.ids).toHaveLength(1)
  expect(fixture.getPollCount()).toBeGreaterThanOrEqual(1)
  expect(await page.evaluate(() => localStorage.getItem('study-agent-tutor-pending-message'))).toBeNull()
})

test('提交完成响应丢失后刷新重放同一ID，仅有一对消息', async ({ page }) => {
  const fixture = await mockTutor(page, 'lost')
  await start(page)
  await send(page)
  await expect(page.getByRole('button', { name: '恢复待确认消息' })).toBeEnabled()
  expect(await page.evaluate(() => localStorage.getItem('study-agent-tutor-pending-message'))).not.toBeNull()
  await page.reload()
  await expect(page.getByText('这是当前资料中的解释。', { exact: true })).toBeVisible()
  expect(fixture.ids).toHaveLength(2)
  expect(fixture.ids[0]).toBe(fixture.ids[1])
  await expect(page.locator('.tutor-message')).toHaveCount(2)
})

test('明确失败轮次重新尝试产生新ID，并展示受控错误', async ({ page }) => {
  const fixture = await mockTutor(page, 'failed')
  await start(page)
  await send(page)
  await expect(page.getByText('本轮调用预算已耗尽')).toBeVisible()
  await page.getByRole('button', { name: '重新尝试本次问题' }).click()
  await expect(page.getByText('这是当前资料中的解释。', { exact: true })).toBeVisible()
  expect(fixture.ids).toHaveLength(2)
  expect(fixture.ids[0]).not.toBe(fixture.ids[1])
})

test('辅导关闭显示明确提示和外发说明，学习入口仍在', async ({ page }) => {
  await mockTutor(page, 'disabled')
  await page.goto('/tutor')
  await page.getByRole('button', { name: '新建辅导会话' }).click()
  await expect(page.getByText('学习辅导暂未启用')).toBeVisible()
  await expect(page.getByText('问题及必要的资料片段会发送给配置的模型服务。', { exact: false })).toBeVisible()
  await expect(page.getByRole('button', { name: '发送问题' })).toHaveCount(0)
  await page.goto('/study')
  await expect(page.getByRole('button', { name: '开始学习', exact: true })).toBeVisible()
})

test('HTML按纯文本展示，不创建脚本/图片、不请求外部地址', async ({ page }) => {
  const external: string[] = []
  page.on('request', request => { if (request.url().includes('invalid.example')) external.push(request.url()) })
  await mockTutor(page, 'unsafe')
  await start(page)
  await send(page)
  await expect(page.locator('.tutor-message.assistant')).toContainText('<script>window.pwned=1</script>')
  await expect(page.locator('.tutor-message.assistant img, .tutor-message.assistant script')).toHaveCount(0)
  expect(await page.evaluate(() => (window as unknown as Record<string, unknown>).pwned)).toBeUndefined()
  expect(external).toEqual([])
})

test('无依据终态清除待确认请求，显示不足提示', async ({ page }) => {
  await mockTutor(page, 'insufficient')
  await start(page)
  await send(page)
  await expect(page.getByText('当前资料依据不足。')).toBeVisible()
  await expect(page.locator('.tutor-citations')).toHaveCount(0)
  expect(await page.evaluate(() => localStorage.getItem('study-agent-tutor-pending-message'))).toBeNull()
})

test('答后链接参数在创建会话时固定传送，不使用下一题', async ({ page }) => {
  const fixture = await mockTutor(page)
  await page.goto('/tutor?knowledge_base_id=kb1&study_session_id=session-1&answered_question_id=answered-1')
  await page.getByRole('button', { name: '新建辅导会话' }).click()
  await expect(page.getByRole('heading', { name: '围绕刚才的作答继续请教' })).toBeVisible()
  expect(fixture.created).toEqual([{ knowledge_base_id: 'kb1', study_session_id: 'session-1', answered_question_id: 'answered-1' }])
  await send(page, '我刚才为什么答错')
  await expect(page.locator('.tutor-message.assistant')).toHaveCount(1)
})

test('同ID占位尚不可见的busy冲突恢复仍复用原ID', async ({ page }) => {
  const fixture = await mockTutor(page, 'busy')
  await start(page)
  await send(page)
  await expect(page.getByRole('button', { name: '恢复待确认消息' })).toBeEnabled()
  await page.getByRole('button', { name: '恢复待确认消息' }).click()
  await expect(page.locator('.tutor-message.assistant')).toHaveCount(1)
  expect(fixture.ids).toHaveLength(2)
  expect(fixture.ids[0]).toBe(fixture.ids[1])
})

test('真实StudyView作答后点击继续请教绑定已答题而非next题', async ({ page }) => {
  const fixture = await mockTutor(page)
  await page.goto('/study')
  await expect(page.getByRole('link', { name: '继续请教' })).toHaveCount(0)
  await page.getByRole('button', { name: '开始学习', exact: true }).click()
  await page.locator('label.el-radio').filter({ hasText: '正确' }).click()
  await page.getByRole('button', { name: '提交答案' }).click()
  await page.getByRole('link', { name: '继续请教' }).click()
  await expect(page).toHaveURL(/answered_question_id=answered-question-1/)
  await page.getByRole('button', { name: '新建辅导会话' }).click()
  expect(fixture.created[0]).toEqual({ knowledge_base_id: 'kb1', study_session_id: 'study-session-1',
    answered_question_id: 'answered-question-1' })
})
