import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api, type User } from '@/lib/api'

export function useAuth() {
  return useQuery({
    queryKey: ['me'],
    queryFn: async () => (await api.get<{ user: User | null }>('/api/me')).user,
    staleTime: 30_000,
  })
}

export function useLogin() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: { email: string; password: string }) =>
      api.post<{ user: User }>('/api/login', body),
    onSuccess: (data) => qc.setQueryData(['me'], data.user),
  })
}

export function useLogout() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => api.post<{ ok: boolean }>('/api/logout'),
    onSuccess: () => qc.setQueryData(['me'], null),
  })
}
