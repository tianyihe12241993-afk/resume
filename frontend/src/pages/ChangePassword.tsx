import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { Alert } from '@/components/ui'

export default function ChangePassword() {
  const [current, setCurrent] = useState('')
  const [pw, setPw] = useState('')
  const [confirm, setConfirm] = useState('')

  const submit = useMutation({
    mutationFn: () => api.post<{ ok: boolean }>('/api/change-password', { current, password: pw, confirm }),
    onSuccess: () => { setCurrent(''); setPw(''); setConfirm('') },
  })

  return (
    <div className="max-w-sm mx-auto mt-8">
      <h1 className="text-2xl font-bold text-gray-900 mb-6">Change password</h1>
      <div className="card p-6">
        {submit.isSuccess && <div className="mb-4"><Alert variant="success">Password updated successfully.</Alert></div>}
        {submit.isError && <div className="mb-4"><Alert variant="error">{(submit.error as Error).message}</Alert></div>}

        <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); submit.mutate() }}>
          <div>
            <label className="label">Current password</label>
            <input type="password" required className="input" value={current}
                   onChange={(e) => setCurrent(e.target.value)} />
          </div>
          <div>
            <label className="label">New password <span className="text-gray-400 font-normal">(min 8 chars)</span></label>
            <input type="password" required minLength={8} className="input" value={pw}
                   onChange={(e) => setPw(e.target.value)} />
          </div>
          <div>
            <label className="label">Confirm new password</label>
            <input type="password" required minLength={8} className="input" value={confirm}
                   onChange={(e) => setConfirm(e.target.value)} />
          </div>
          <button disabled={submit.isPending} className="btn-primary w-full py-2.5">
            {submit.isPending ? 'Updating…' : 'Update password'}
          </button>
        </form>
      </div>
    </div>
  )
}
