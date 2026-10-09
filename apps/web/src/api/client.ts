import axios from 'axios'

// 全部业务接口共用请求地址和超时，页面无需重复配置。
export const apiClient = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || '/api',
  timeout: 30_000,
  headers: { Accept: 'application/json' },
})

// 自动携带本次浏览器会话的访问令牌和请求 ID，方便鉴权与定位问题。
apiClient.interceptors.request.use((config) => {
  const token = sessionStorage.getItem('study-agent-access-token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  config.headers['X-Request-ID'] ??= crypto.randomUUID()
  return config
})
