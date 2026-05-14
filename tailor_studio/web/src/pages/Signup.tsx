import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useSignup } from '@/hooks/useAuth'
import { Alert } from '@/components/ui'

export default function Signup() {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [localErr, setLocalErr] = useState<string | null>(null)
  const signup = useSignup()

  const onSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    setLocalErr(null)
    if (password.length < 8) {
      setLocalErr('Password must be at least 8 characters.')
      return
    }
    if (password !== confirm) {
      setLocalErr('Passwords do not match.')
      return
    }
    signup.mutate({ email: email.trim(), password })
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

        <form onSubmit={onSubmit} className="card p-6 space-y-4">
          <h1 className="text-base font-semibold text-gray-900">Create your account</h1>

          <div>
            <label className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-1 block">
              Email
            </label>
            <input
              type="email"
              autoFocus
              required
              autoComplete="email"
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
              autoComplete="new-password"
              minLength={8}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="input"
              placeholder="at least 8 characters"
            />
          </div>
          <div>
            <label className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-1 block">
              Confirm password
            </label>
            <input
              type="password"
              required
              autoComplete="new-password"
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
              className="input"
              placeholder="re-enter password"
            />
          </div>

          {(localErr || signup.isError) && (
            <Alert variant="error">
              {localErr || (signup.error as Error)?.message || 'Sign-up failed.'}
            </Alert>
          )}

          <button
            disabled={signup.isPending || !email.trim() || !password || !confirm}
            className="btn-primary w-full"
            type="submit"
          >
            {signup.isPending ? 'Creating account…' : 'Create account'}
          </button>

          <p className="text-xs text-gray-400 text-center">
            Already have an account?{' '}
            <Link to="/login" className="text-brand-600 hover:underline">Sign in</Link>
          </p>
        </form>
      </div>
    </div>
  )
}
