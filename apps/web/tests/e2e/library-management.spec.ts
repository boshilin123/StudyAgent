import { expect, test, type Page } from '@playwright/test'

async function setupLibrary(page: Page, withCandidates = false) {
  const now = new Date().toISOString()
  let bases = [{ id: 'kb1', name: '聚时', status: 'active', material_count: 1, question_count: 3 },
    { id: 'kb2', name: '空知识库', status: 'active', material_count: 0, question_count: 0 }]
  const material = { id: 'm1', knowledge_base_id: 'kb1', title: '部署笔记', original_filename: 'notes.pdf',
    media_type: 'application/pdf', size_bytes: 1000, parse_status: 'ready', created_at: now }
  let job = { id: 'j1', material_id: 'm1', status: 'completed', stage: 'completed', progress: 100,
    target_question_count: withCandidates ? 10 : 6, generated_count: withCandidates ? 9 : 3,
    rejected_count: withCandidates ? 1 : 3, error_message: null,
    rejected_candidates: withCandidates ? [{ reason: '片段与引文数量不一致', question: {
      question_type: 'true_false', stem: '未通过校验的部署候选题', options: null,
      correct_answers: ['正确'], explanation: '模型生成的候选解析', difficulty: 2,
      source_chunk_ids: ['c1'], source_quotes: ['引文一', '引文二'],
    } }] : [] }
  const submitted: Record<string, unknown>[] = []
  const deleted: string[] = []
  let healthy = true
  await page.route('**/api/**', async route => {
    const request = route.request()
    const url = new URL(request.url())
    const path = url.pathname
    if (!path.startsWith('/api/')) {
      await route.continue()
      return
    }
    if (path === '/api/health/ready') {
      await route.fulfill({ status: healthy ? 200 : 503, json: { status: healthy ? 'ok' : 'not_ready' } })
    } else if (path === '/api/knowledge-bases') {
      await route.fulfill({ json: { items: bases, total: bases.length } })
    } else if (path.startsWith('/api/knowledge-bases/') && request.method() === 'DELETE') {
      const id = path.split('/').at(-1)!
      deleted.push(id)
      bases = bases.filter(base => base.id !== id)
      await route.fulfill({ status: 204 })
    } else if (path.endsWith('/materials')) {
      await route.fulfill({ json: { items: path.includes('/kb1/') ? [material] : [], total: path.includes('/kb1/') ? 1 : 0 } })
    } else if (path === '/api/materials/m1/question-generation-jobs') {
      if (request.method() === 'POST') {
        const payload = request.postDataJSON()
        submitted.push(payload)
        job = { ...job, id: 'j2', status: 'pending', progress: 0, target_question_count: payload.target_question_count,
          generated_count: 0, rejected_count: 0 }
        await route.fulfill({ status: 202, json: job })
      } else await route.fulfill({ json: [job] })
    } else await route.fulfill({ json: { items: [], total: 0 } })
  })
  return { submitted, deleted, failHealth: () => { healthy = false }, recoverHealth: () => { healthy = true } }
}

test('旧生成任务目标6实际3：刷新可见真实结果，自定义17题和题型提交', async ({ page }) => {
  const state = await setupLibrary(page)
  await page.goto('/knowledge-bases')
  await expect(page.getByText('生成数量不足', { exact: true })).toBeVisible()
  await expect(page.getByText('目标 6 道 · 通过校验 3 道 · 拒绝 3 道', { exact: true })).toBeVisible()
  await page.reload()
  await expect(page.getByText('目标 6 道 · 通过校验 3 道 · 拒绝 3 道', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: '查看拒绝详情', exact: true }).click()
  await expect(page.getByText(/候选题内容未被保存，无法补回/)).toBeVisible()
  await page.getByRole('button', { name: '关闭', exact: true }).click()
  await page.getByRole('button', { name: '生成题目', exact: true }).click()
  await page.locator('.el-dialog .el-input-number input').fill('17')
  await page.locator('.el-dialog').getByText('填空题', { exact: true }).click()
  await expect(page.getByRole('checkbox', { name: '填空题', exact: true })).not.toBeChecked()
  await page.getByRole('button', { name: '提交生成', exact: true }).click()
  await expect.poll(() => state.submitted.length).toBe(1)
  expect(state.submitted[0]).toMatchObject({ target_question_count: 17, allowed_types: ['single_choice', 'true_false'] })
  await expect(page.getByText('目标 17 道 · 通过校验 0 道 · 拒绝 0 道', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: '生成题目', exact: true })).toBeDisabled()
})

test('新的拒绝详情保存题干、答案和不匹配的引文，刷新后可查看', async ({ page }) => {
  await setupLibrary(page, true)
  await page.goto('/knowledge-bases')
  await page.reload()
  await page.getByRole('button', { name: '查看拒绝详情', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: '拒绝详情' })
  await expect(dialog.getByText('片段与引文数量不一致', { exact: true })).toBeVisible()
  await expect(dialog.getByRole('heading', { name: '1. 未通过校验的部署候选题' })).toBeVisible()
  await expect(dialog.getByText('候选答案：正确', { exact: true })).toBeVisible()
  await expect(dialog.getByText('来源片段 1 个 · 引文 2 条', { exact: true })).toBeVisible()
  await expect(dialog.getByText('候选引文 2：引文二', { exact: true })).toBeVisible()
  await expect(dialog.getByText(/未通过校验，不能视为可靠答案或原文引用/)).toBeVisible()
  await dialog.getByRole('button', { name: '关闭', exact: true }).click()
  await expect(dialog).not.toBeVisible()
})

test('知识库删除可取消，确认后选下一库，删最后一个无旧资料残留', async ({ page }) => {
  const state = await setupLibrary(page)
  await page.goto('/knowledge-bases')
  await page.getByRole('button', { name: '删除知识库', exact: true }).click()
  await page.getByRole('button', { name: '取消', exact: true }).click()
  expect(state.deleted).toEqual([])
  await page.getByRole('button', { name: '删除知识库', exact: true }).click()
  await page.getByRole('button', { name: '删除', exact: true }).click()
  await expect(page.locator('.library-header h2')).toHaveText('空知识库')
  await expect(page.getByText('部署笔记', { exact: true })).toHaveCount(0)
  await page.getByRole('button', { name: '删除知识库', exact: true }).click()
  await page.getByRole('button', { name: '删除', exact: true }).click()
  await expect(page.getByText('先创建一个学习主题', { exact: true })).toBeVisible()
  expect(state.deleted).toEqual(['kb1', 'kb2'])
  await expect(page.locator('.library-header')).toHaveCount(0)
})

test('API就绪提示依据真实状态响应变化，可重新检查恢复', async ({ page }) => {
  const state = await setupLibrary(page)
  await page.goto('/knowledge-bases')
  const indicator = page.getByRole('button', { name: '检查 API 状态', exact: true })
  await expect(indicator).toHaveText('API 可用')
  state.failHealth()
  await indicator.click()
  await expect(indicator).toHaveText('API 不可用')
  state.recoverHealth()
  await indicator.click()
  await expect(indicator).toHaveText('API 可用')
})

test('所有主要页面只保留中文标题，生成结果链接固定知识库范围', async ({ page }) => {
  await setupLibrary(page)
  await page.goto('/knowledge-bases')
  await page.getByRole('link', { name: '查看该知识库题目', exact: true }).click()
  await expect(page).toHaveURL(/questions\?knowledge_base_id=kb1/)
  await expect(page.locator('.filter-bar .el-select').first()).toContainText('聚时')
  for (const path of ['/', '/knowledge-bases', '/questions', '/study', '/tutor', '/progress']) {
    await page.goto(path)
    await expect(page.locator('.topbar h1')).toBeVisible()
    const copy = await page.locator('body').innerText()
    expect(copy).not.toMatch(/PERSONAL LEARNING OS|LIBRARIES|KNOWLEDGE BASE|MATERIALS|RECENT ACTIVITY|QUICK START|ADAPTIVE SESSION|QUESTION REVIEW|LEARNING ANALYTICS|SESSION COMPLETED|ANSWER FEEDBACK|SESSION RECOVERY|REVIEW QUEUE|MASTERY|HISTORY/)
  }
})
