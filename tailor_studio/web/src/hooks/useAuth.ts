import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { api, ApiError, type User } from '@/lib/api'

/**
 * useAuth: returns the logged-in user, null when unauthenticated, undefined while loading.
 * Calls GET /api/me — if 401, returns null without throwing.
 */
export function useAuth() {
  return useQuery<User | null>({
    queryKey: ['me'],
    queryFn: async () => {
      try {
        return await api.get<User>('/api/me')
      } catch (e) {
        if (e instanceof ApiError && e.status === 401) return null
        throw e
      }
    },
    staleTime: 60_000,
    retry: false,
  })
}

async function fetchMe(): Promise<User | null> {
  try {
    return await api.get<User>('/api/me')
  } catch (e) {
    if (e instanceof ApiError && e.status === 401) return null
    throw e
  }
}

export function useLogin() {
  const qc = useQueryClient()
  const nav = useNavigate()
  return useMutation({
    mutationFn: (creds: { email: string; password: string }) =>
      api.post<{ ok: boolean; email: string }>('/api/login', creds),
    onSuccess: async () => {
      // Wait for /api/me to return fresh data BEFORE navigating; otherwise
      // the cached 'null' from the unauth state lingers and RequireAuth
      // bounces us back to /login.
      const me = await fetchMe()
      qc.setQueryData(['me'], me)
      nav('/dashboard', { replace: true })
    },
  })
}

export function useSignup() {
  const qc = useQueryClient()
  const nav = useNavigate()
  return useMutation({
    mutationFn: (creds: { email: string; password: string }) =>
      api.post<{ ok: boolean; email: string; id: number }>('/api/signup', creds),
    onSuccess: async () => {
      const me = await fetchMe()
      qc.setQueryData(['me'], me)
      nav('/dashboard', { replace: true })
    },
  })
}

export function useLogout() {
  const qc = useQueryClient()
  const nav = useNavigate()
  return useMutation({
    mutationFn: () => api.post('/api/logout'),
    onSuccess: () => {
      qc.setQueryData(['me'], null)
      qc.invalidateQueries()
      nav('/login', { replace: true })
    },
  })
}
