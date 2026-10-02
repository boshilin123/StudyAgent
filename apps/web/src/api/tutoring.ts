import { apiClient } from './client'
import type { Page } from './types'

export type TutorIntent = 'materials' | 'answered_question' | 'progress' | 'mistakes' | 'general'
export type TutorTurnStatus = 'pending' | 'running' | 'completed' | 'failed' | 'cancelled'

export interface TutorCitation {
  evidence_id: string
  material_id: string
  chunk_id: string
  title: string
  page_start: number | null
  page_end: number | null
  quote: string
  content_hash: string
  valid: boolean
}

export interface TutorConversation {
  id: string
  knowledge_base_id: string
  study_session_id: string | null
  answered_question_id: string | null
  status: string
  created_at: string
}

export interface TutorMessage {
  id: string
  turn_id: string
  role: string
  content: string
  citations: TutorCitation[]
  created_at: string
  sequence: number
}

export interface TutorResponse {
  turn_id: string
  status: TutorTurnStatus
  message: string | null
  answer_status: string | null
  mode: string | null
  citations: TutorCitation[]
  suggestions: string[]
  suggested_questions: string[]
  usage: { model_calls: number | null; tool_calls: number | null; total_tokens: number | null; known: boolean }
  idempotent_replay: boolean
  error_code: string | null
  error_message: string | null
}

export interface TutorTurn {
  id: string
  status: TutorTurnStatus
  client_message_id: string
  response: TutorResponse | null
  error_code: string | null
  error_message: string | null
}

export interface TutorDetail {
  conversation: TutorConversation
  messages: TutorMessage[]
  page: number
  page_size: number
  total: number
}

export interface TutorInput {
  client_message_id: string
  content: string
  intent: TutorIntent
}

export async function createTutorConversation(payload: {
  knowledge_base_id: string
  study_session_id?: string
  answered_question_id?: string
}) {
  return (await apiClient.post<TutorConversation>('/tutor/conversations', payload)).data
}

export async function listTutorConversations(knowledgeBaseId: string, page = 1) {
  return (await apiClient.get<Page<TutorConversation>>('/tutor/conversations', {
    params: { knowledge_base_id: knowledgeBaseId, page, page_size: 20 },
  })).data
}

export async function getTutorConversation(id: string, page = 1) {
  return (await apiClient.get<TutorDetail>(`/tutor/conversations/${id}`, {
    params: { page, page_size: 50 },
  })).data
}

export async function sendTutorMessage(id: string, input: TutorInput) {
  return (await apiClient.post<TutorResponse>(`/tutor/conversations/${id}/messages`, input, {
    timeout: 110_000,
  })).data
}

export async function getTutorTurn(conversationId: string, turnId: string) {
  return (await apiClient.get<TutorTurn>(
    `/tutor/conversations/${conversationId}/turns/${turnId}`,
  )).data
}

export async function archiveTutorConversation(id: string) {
  return (await apiClient.post<TutorConversation>(`/tutor/conversations/${id}/archive`)).data
}
