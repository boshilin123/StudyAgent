export function formatDate(value: string | null | undefined): string {
  if (!value) return '—'
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(value))
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 ** 2).toFixed(1)} MB`
}

export function percentage(value: number): string {
  return `${Math.round(value * 100)}%`
}

export const questionTypeLabel: Record<string, string> = {
  single_choice: '单选题',
  fill_blank: '填空题',
  true_false: '判断题',
}

export const modeLabel: Record<string, string> = {
  diagnostic: '诊断',
  practice: '练习',
  review: '复习',
  mock_exam: '模拟考试',
}
