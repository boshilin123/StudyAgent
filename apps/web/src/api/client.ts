import axios from 'axios'

export const apiClient = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || '/api',
  timeout: 30_000,
  headers: { Accept: 'application/json' },
})

apiClient.interceptors.request.use((config) => {
  config.headers['X-Request-ID'] ??= crypto.randomUUID()
  return config
})
