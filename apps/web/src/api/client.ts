import axios from 'axios'

export const apiClient = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || '/api',
  timeout: 30_000,
  headers: { Accept: 'application/json' },
})

apiClient.interceptors.request.use((config) => {
  const token = sessionStorage.getItem('study-agent-access-token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  config.headers['X-Request-ID'] ??= crypto.randomUUID()
  return config
})
