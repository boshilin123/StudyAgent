export type QuestionType = 'single_choice' | 'fill_blank' | 'true_false'
export type StudyMode = 'diagnostic' | 'practice' | 'review' | 'mock_exam'

export interface Page<T> {
  items: T[]
  page: number
  page_size: number
  total: number
}

export interface KnowledgeBase {
  id: string
  name: string
  description: string | null
  language: string
  status: 'active' | 'archived'
  material_count: number
  question_count: number
  created_at: string
  updated_at: string
}

export interface Material {
  id: string
  knowledge_base_id: string
  title: string
  original_filename: string
  media_type: string
  sha256: string
  size_bytes: number
  language: string
  parse_status: 'pending' | 'parsing' | 'ready' | 'partial' | 'failed'
  parser_version: string | null
  error_message: string | null
  created_at: string
  updated_at: string
}

export interface Job {
  id: string
  material_id: string
  status: string
  stage: string
  progress: number
  error_code: string | null
  error_message: string | null
}

export interface UploadResult {
  material: Material
  job: Job
}

export interface QuestionSource {
  chunk_id: string
  quote: string
  rank: number
}

export interface Question {
  id: string
  knowledge_base_id: string
  knowledge_point_id: string
  question_type: QuestionType
  stem: string
  options: Array<{ key: string; text: string }> | null
  correct_answer: unknown
  scoring_points: string[]
  explanation: string
  difficulty: number
  max_score: number
  status: 'draft' | 'active' | 'disabled' | 'rejected'
  vector_id: string | null
  sources: QuestionSource[]
  created_at: string | null
  updated_at: string | null
}

export interface QuestionGenerationJob extends Job {
  target_question_count: number
  allowed_types: string[]
  difficulty_min: number
  difficulty_max: number
  language: string
  generated_count: number
  rejected_count: number
  rejected_candidates?: Array<{
    reason: string
    question: {
      question_type: QuestionType
      stem: string
      options: Array<{ key: string; text: string }> | null
      correct_answers: string[]
      explanation: string
      difficulty: number
      source_chunk_ids: string[]
      source_quotes: string[]
    }
  }>
}

export interface SelectionReason {
  code?: string
  message?: string
  target_difficulty?: number
  factors?: Record<string, unknown>
}

export interface PublicQuestion {
  id: string
  sequence: number
  question_type: QuestionType
  stem: string
  options: Array<{ key: string; text: string }> | null
  difficulty: number
  max_score: number
  selection_reason: SelectionReason | null
}

export interface StudySession {
  id: string
  knowledge_base_id: string
  mode: StudyMode
  status: 'active' | 'completed' | 'abandoned'
  planned_question_count: number
  answered_question_count: number
  correct_count: number
  incorrect_count: number
  total_score: number
  max_total_score: number
  started_at: string
  finished_at: string | null
  current_question: PublicQuestion | null
}

export interface Mastery {
  knowledge_point_id: string
  knowledge_base_id: string
  mastery_score: number
  answered_count: number
  correct_count: number
  recent_accuracy: number
  confidence: number
  updated_at: string
}

export interface ReviewTask {
  id: string
  knowledge_point_id: string
  knowledge_base_id: string
  due_at: string
  interval_days: number
  repetitions: number
  ease_factor: number
  last_quality: number
  status: 'pending' | 'completed'
}

export interface ExplanationEvidence {
  chunk_id: string
  quote: string
  rank: number
}

export interface RagExplanation {
  provider: string
  status: string
  conclusion: string
  gap: string
  evidence: ExplanationEvidence[]
}

export interface AnswerResult {
  submission_id: string
  question_id: string
  verdict: 'correct' | 'incorrect'
  score: number
  max_score: number
  feedback: string
  explanation: string
  rag_explanation: RagExplanation
  idempotent_replay: boolean
  mastery: Mastery
  review_task: ReviewTask
  session: StudySession
}

export interface ApiErrorBody {
  error?: {
    code?: string
    message?: string
    details?: unknown
    request_id?: string | null
  }
}
