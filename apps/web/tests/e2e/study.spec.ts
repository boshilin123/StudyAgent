import { expect, test, type Page } from '@playwright/test'

async function mockStudy(page: Page, loseFirstResponse = false, rejectFirstRequest = false) {
  const submitted: string[] = []
  const results = new Map<string, object>()
  const questions = [
    { id: 'q1', sequence: 1, question_type: 'single_choice', stem: '浏览器选择题',
      options: ['A', 'B', 'C', 'D'].map(key => ({ key, text: key + '选项' })) },
    { id: 'q2', sequence: 2, question_type: 'fill_blank', stem: '浏览器填空题', options: null },
    { id: 'q3', sequence: 3, question_type: 'true_false', stem: '浏览器判断题', options: null },
  ].map(question => ({ ...question, difficulty: 2, max_score: 10, selection_reason: null }))
  let session = {
    id: 'session-1', knowledge_base_id: 'kb1', mode: 'practice', status: 'active',
    planned_question_count: 3, answered_question_count: 0, correct_count: 0, incorrect_count: 0,
    total_score: 0, max_total_score: 0, started_at: new Date().toISOString(), finished_at: null,
    current_question: questions[0] as (typeof questions)[number] | null,
  }
  await page.route('**/api/**', async route => {
    const request = route.request()
    const path = new URL(request.url()).pathname
    if (!path.startsWith('/api/')) {
      await route.continue()
      return
    }
    if (path.endsWith('/knowledge-bases')) {
      await route.fulfill({ json: { items: [{ id: 'kb1', name: '浏览器测试知识库', status: 'active' }], total: 1 } })
    } else if (path.endsWith('/study/sessions') && request.method() === 'POST') {
      session.mode = request.postDataJSON().mode
      await route.fulfill({ status: 201, json: session })
    } else if (path.endsWith('/answers')) {
      const body = request.postDataJSON()
      submitted.push(body.submission_id)
      if (rejectFirstRequest) {
        rejectFirstRequest = false
        await route.fulfill({ status: 422, json: { error: { code: 'INVALID_ANSWER', message: '测试拒绝' } } })
        return
      }
      let result = results.get(body.submission_id)
      if (!result) {
        const count = session.answered_question_count + 1
        session = { ...session, status: count === 3 ? 'completed' : 'active',
          answered_question_count: count, correct_count: count, total_score: count * 10,
          max_total_score: count * 10, current_question: questions[count] || null }
        result = { submission_id: body.submission_id, question_id: body.question_id,
          verdict: 'correct', score: 10, max_score: 10, feedback: '回答正确',
          explanation: '测试解释', idempotent_replay: false, session: { ...session },
          rag_explanation: { conclusion: '正确', gap: '测试解释', provider: 'question_bank',
            status: 'fallback', evidence: [{ chunk_id: 'chunk1', quote: '浏览器来源引用' }] },
          mastery: { mastery_score: 0.6 }, review_task: { due_at: new Date().toISOString() } }
        results.set(body.submission_id, result)
        if (loseFirstResponse) {
          loseFirstResponse = false
          await route.abort('connectionreset')
          return
        }
      } else {
        result = { ...result, idempotent_replay: true }
      }
      await route.fulfill({ json: result })
    } else if (path.endsWith('/session-1')) {
      await route.fulfill({ json: session })
    } else {
      await route.fulfill({ json: { items: [], total: 0 } })
    }
  })
  return submitted
}

for (const mode of ['练习', '诊断', '复习', '模拟']) {
  test(`${mode}：三类题、引用、总结`, async ({ page }) => {
    await mockStudy(page)
    await page.goto('/study')
    await page.locator('.el-segmented__item').filter({ hasText: mode }).click()
    await page.getByRole('button', { name: '开始学习', exact: true }).click()
    await page.getByText('A选项', { exact: true }).click()
    await page.getByRole('button', { name: '提交答案' }).click()
    await expect(page.getByText('浏览器来源引用')).toBeVisible()
    await page.getByRole('button', { name: '下一题' }).click()
    await page.getByPlaceholder('请输入答案').fill('1.5')
    await page.getByRole('button', { name: '提交答案' }).click()
    await page.getByRole('button', { name: '下一题' }).click()
    await page.locator('label.el-radio').filter({ hasText: '正确' }).click()
    await page.getByRole('button', { name: '提交答案' }).click()
    await page.getByRole('button', { name: '查看本轮总结' }).click()
    await expect(page.getByRole('heading', { name: '本轮学习完成' })).toBeVisible()
    expect(await page.evaluate(() => localStorage.getItem('study-agent-active-session'))).toBeNull()
  })
}

for (const refresh of [false, true]) {
  test(`响应丢失后${refresh ? '刷新' : '重试'}复用提交 ID`, async ({ page }) => {
    const ids = await mockStudy(page, true)
    await page.goto('/study')
    await page.getByRole('button', { name: '开始学习', exact: true }).click()
    await page.getByText('A选项', { exact: true }).click()
    await page.getByRole('button', { name: '提交答案' }).click()
    await expect(page.getByRole('button', { name: '提交答案' })).toBeEnabled()
    if (refresh) await page.reload()
    else await page.getByRole('button', { name: '提交答案' }).click()
    await expect(page.getByRole('heading', { name: '回答正确' })).toBeVisible()
    expect(ids).toHaveLength(2)
    expect(ids[0]).toBe(ids[1])
    expect(await page.evaluate(() => localStorage.getItem('study-agent-pending-answer'))).toBeNull()
  })
}

test('明确拒绝后允许新提交，不重试旧无效请求', async ({ page }) => {
  const ids = await mockStudy(page, false, true)
  await page.goto('/study')
  await page.getByRole('button', { name: '开始学习', exact: true }).click()
  await page.getByText('A选项', { exact: true }).click()
  await page.getByRole('button', { name: '提交答案' }).click()
  await expect(page.getByText('测试拒绝')).toBeVisible()
  await page.getByRole('button', { name: '提交答案' }).click()
  await expect(page.getByRole('heading', { name: '回答正确' })).toBeVisible()
  expect(ids).toHaveLength(2)
  expect(ids[0]).not.toBe(ids[1])
})

test('刷新恢复被明确拒绝后清除旧载荷，允许重新作答', async ({ page }) => {
  const ids = await mockStudy(page, false, true)
  await page.goto('/study')
  await page.evaluate(() => {
    localStorage.setItem('study-agent-active-session', 'session-1')
    localStorage.setItem('study-agent-pending-answer', JSON.stringify({
      session_id: 'session-1', submission_id: 'old-invalid-id', question_id: 'q1',
      answer: 'Z', elapsed_seconds: 1,
    }))
  })
  await page.reload()
  await expect(page.getByText('上次会话无法恢复：测试拒绝')).toBeVisible()
  expect(await page.evaluate(() => localStorage.getItem('study-agent-pending-answer'))).toBeNull()
  await page.getByText('A选项', { exact: true }).click()
  await page.getByRole('button', { name: '提交答案' }).click()
  await expect(page.getByRole('heading', { name: '回答正确' })).toBeVisible()
  expect(ids).toHaveLength(2)
  expect(ids[0]).not.toBe(ids[1])
})
