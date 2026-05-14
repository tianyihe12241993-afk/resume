import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useLogin } from '@/hooks/useAuth'
import { Alert } from '@/components/ui'

export default function Login() {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const login = useLogin()

  const onSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!email.trim() || !password) return
    login.mutate({ email: email.trim(), password })
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-slate-50 p-4">
      <div className="w-full max-w-sm">
        <div className="flex items-center gap-2.5 mb-8 justify-center">
          <span
            className="w-9 h-9 rounded-lg grid place-items-center text-white text-base font-bold shadow"
            style={{ background: 'linear-gradient(135deg,#6366f1,#4f46e5)' }}
          >S</span>
          <span className="font-semibold text-lg text-gray-900 tracking-tight">Tailor Studio</span>
        </div>

        <form
          onSubmit={onSubmit}
          className="card p-6 space-y-4"
        >
          <div>
            <label className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-1 block">
              Email
            </label>
            <input
              type="email"
              autoFocus
              required
              autoComplete="username"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="input"
              placeholder="you@example.com"
            />
          </div>
          <div>
            <label className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-1 block">
              Password
            </label>
            <input
              type="password"
              required
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="input"
              placeholder="••••••••"
            />
          </div>

          {login.isError && (
            <Alert variant="error">{(login.error as Error).message || 'Login failed.'}</Alert>
          )}

          <button
            disabled={login.isPending || !email.trim() || !password}
            className="btn-primary w-full"
            type="submit"
          >
            {login.isPending ? 'Signing in…' : 'Sign in'}
          </button>
        </form>

        <p className="text-xs text-gray-400 text-center mt-4">
          New here?{' '}
          <Link to="/signup" className="text-brand-600 hover:underline">Create an account</Link>
        </p>
      </div>
    </div>
  )
}
