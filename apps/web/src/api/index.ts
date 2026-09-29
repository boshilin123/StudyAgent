import axios from 'axios'

import { apiClient } from './client'
import type {
  AnswerResult,
  ApiErrorBody,
  Job,
  KnowledgeBase,
  Mastery,
  Material,
  Page,
  Question,
  QuestionGenerationJob,
  QuestionType,
  ReviewTask,
  StudyMode,
  StudySession,
  UploadResult,
} from './types'

export function apiErrorMessage(error: unknown): string {
  if (axios.isAxiosError<ApiErrorBody>(error)) {
    return error.response?.data?.error?.message || error.message || '请求失败'
  }
  return error instanceof Error ? error.message : '发生未知错误'
}

export async function listKnowledgeBases(params: Record<string, unknown> = {}) {
  return (await apiClient.get<Page<KnowledgeBase>>('/knowledge-bases', { params })).data
}

export async function createKnowledgeBase(payload: {
  name: string
  description?: string
  language?: string
}) {
  return (await apiClient.post<KnowledgeBase>('/knowledge-bases', payload)).data
}

export async function updateKnowledgeBase(
  id: string,
  payload: Partial<Pick<KnowledgeBase, 'name' | 'description' | 'language' | 'status'>>,
) {
  return (await apiClient.patch<KnowledgeBase>(`/knowledge-bases/${id}`, payload)).data
}

export async function listMaterials(knowledgeBaseId: string) {
  return (
    await apiClient.get<Page<Material>>(`/knowledge-bases/${knowledgeBaseId}/materials`, {
      params: { page_size: 100 },
    })
  ).data
}

export async function uploadMaterial(
  knowledgeBaseId: string,
  file: File,
  title?: string,
) {
  const form = new FormData()
  form.append('file', file)
  if (title?.trim()) form.append('title', title.trim())
  return (
    await apiClient.post<UploadResult>(`/knowledge-bases/${knowledgeBaseId}/materials`, form, {
      timeout: 120_000,
    })
  ).data
}

export async function deleteMaterial(id: string) {
  await apiClient.delete(`/materials/${id}`)
}

export async function getIngestionJob(id: string) {
  return (await apiClient.get<Job>(`/ingestion-jobs/${id}`)).data
}

export async function createQuestionGenerationJob(
  materialId: string,
  payload: {
    target_question_count: number
    allowed_types: QuestionType[]
    difficulty_min: number
    difficulty_max: number
  },
) {
  return (
    await apiClient.post<QuestionGenerationJob>(
      `/materials/${materialId}/question-generation-jobs`,
      payload,
    )
  ).data
}

export async function getQuestionGenerationJob(id: string) {
  return (await apiClient.get<QuestionGenerationJob>(`/question-generation-jobs/${id}`)).data
}

export async function listQuestions(params: Record<string, unknown> = {}) {
  return (
    await apiClient.get<Page<Question>>('/questions', { params: { page_size: 100, ...params } })
  ).data
}

export async function updateQuestion(
  id: string,
  payload: {
    stem?: string
    correct_answers?: string[]
    explanation?: string
    difficulty?: number
  },
) {
  return (await apiClient.patch<Question>(`/questions/${id}`, payload)).data
}

export async function setQuestionStatus(id: string, active: boolean) {
  const action = active ? 'activate' : 'disable'
  return (await apiClient.post<Question>(`/questions/${id}/${action}`)).data
}

export async function createStudySession(payload: {
  knowledge_base_id: string
  mode: StudyMode
  question_count: number
  question_types: QuestionType[]
  difficulty_min: number
  difficulty_max: number
}) {
  return (await apiClient.post<StudySession>('/study/sessions', payload)).data
}

export async function getStudySession(id: string) {
  return (await apiClient.get<StudySession>(`/study/sessions/${id}`)).data
}

export async function submitAnswer(
  sessionId: string,
  payload: {
    submission_id: string
    question_id: string
    answer: string | boolean | number
    elapsed_seconds: number
  },
) {
  return (
    await apiClient.post<AnswerResult>(`/study/sessions/${sessionId}/answers`, payload, {
      timeout: 90_000,
    })
  ).data
}

export async function finishStudySession(id: string) {
  return (await apiClient.post<StudySession>(`/study/sessions/${id}/finish`)).data
}

export async function listMastery(knowledgeBaseId?: string) {
  return (
    await apiClient.get<Mastery[]>('/mastery', {
      params: knowledgeBaseId ? { knowledge_base_id: knowledgeBaseId } : {},
    })
  ).data
}

export async function listDueReviews(knowledgeBaseId?: string, dueBefore?: string) {
  return (
    await apiClient.get<ReviewTask[]>('/reviews/due', {
      params: {
        ...(knowledgeBaseId ? { knowledge_base_id: knowledgeBaseId } : {}),
        ...(dueBefore ? { due_before: dueBefore } : {}),
      },
    })
  ).data
}

export async function listStudyHistory(params: Record<string, unknown> = {}) {
  return (
    await apiClient.get<Page<StudySession>>('/study/history', {
      params: { page_size: 100, ...params },
    })
  ).data
}
