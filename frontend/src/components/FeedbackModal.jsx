import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { X } from 'lucide-react'

const GITHUB_REPO = 'linuxmaier/whats-up-madison'
const GITHUB_ISSUES_URL = `https://github.com/${GITHUB_REPO}/issues/new`

export default function FeedbackModal({ open, onClose }) {
  const [title, setTitle] = useState('')
  const [body, setBody] = useState('')
  const [honeypot, setHoneypot] = useState('')
  const [status, setStatus] = useState('idle') // idle | submitting | success | error
  const [issueUrl, setIssueUrl] = useState(null)
  const dialogRef = useRef(null)

  useEffect(() => {
    if (!open) return
    function handleKey(e) {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', handleKey)
    return () => document.removeEventListener('keydown', handleKey)
  }, [open, onClose])

  useEffect(() => {
    if (!open) return
    const previousFocus = document.activeElement
    dialogRef.current?.focus()
    return () => { previousFocus?.focus() }
  }, [open])

  function handleClose() {
    setTitle('')
    setBody('')
    setHoneypot('')
    setStatus('idle')
    setIssueUrl(null)
    onClose()
  }

  async function handleSubmit(e) {
    e.preventDefault()
    setStatus('submitting')
    try {
      const res = await fetch('/feedback', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title, body, website: honeypot }),
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      setIssueUrl(data.issue_url ?? null)
      setStatus('success')
    } catch {
      setStatus('error')
    }
  }

  if (!open) return null

  return createPortal(
    <div
      className="fixed inset-0 flex items-center justify-center p-4"
      style={{ zIndex: 10000 }}
      onClick={handleClose}
    >
      <div className="absolute inset-0 bg-black/30" />
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="feedback-modal-title"
        tabIndex={-1}
        className="relative bg-white rounded-xl shadow-2xl w-full max-w-lg focus:outline-none"
        onClick={e => e.stopPropagation()}
      >
        <div className="px-5 py-4 flex flex-col gap-4">
          <div className="flex items-center justify-between">
            <h2 id="feedback-modal-title" className="text-base font-semibold text-gray-900">
              Submit feedback
            </h2>
            <button
              type="button"
              className="text-gray-400 hover:text-gray-600 p-1 rounded cursor-pointer"
              onClick={handleClose}
              title="Close"
            >
              <X size={14} />
            </button>
          </div>

          {status === 'success' ? (
            <div className="flex flex-col gap-3 py-2">
              <p className="text-sm text-gray-700">
                Thanks! Your feedback was submitted as a GitHub issue.
              </p>
              {issueUrl && (
                <a
                  href={issueUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-sm text-blue-600 hover:underline"
                >
                  View your issue ↗
                </a>
              )}
              <button
                type="button"
                className="self-start text-sm text-gray-500 hover:text-gray-700 cursor-pointer"
                onClick={handleClose}
              >
                Close
              </button>
            </div>
          ) : (
            <form onSubmit={handleSubmit} className="flex flex-col gap-3">
              {/* honeypot — hidden from humans, bots fill it out */}
              <div style={{ position: 'absolute', opacity: 0, top: '-9999px', left: '-9999px' }} aria-hidden="true">
                <label htmlFor="feedback-website">Website</label>
                <input
                  id="feedback-website"
                  type="text"
                  name="website"
                  value={honeypot}
                  onChange={e => setHoneypot(e.target.value)}
                  tabIndex={-1}
                  autoComplete="off"
                />
              </div>

              <div className="flex flex-col gap-1">
                <label htmlFor="feedback-title" className="text-sm font-medium text-gray-700">
                  Title
                </label>
                <input
                  id="feedback-title"
                  type="text"
                  required
                  maxLength={100}
                  value={title}
                  onChange={e => setTitle(e.target.value)}
                  placeholder="Short summary of your feedback"
                  className="border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-gray-400"
                />
              </div>

              <div className="flex flex-col gap-1">
                <label htmlFor="feedback-body" className="text-sm font-medium text-gray-700">
                  Details
                </label>
                <textarea
                  id="feedback-body"
                  required
                  rows={5}
                  value={body}
                  onChange={e => setBody(e.target.value)}
                  placeholder="Describe the bug or suggestion in more detail"
                  className="border border-gray-300 rounded-lg px-3 py-2 text-sm resize-y focus:outline-none focus:ring-2 focus:ring-gray-400"
                />
              </div>

              {status === 'error' && (
                <p className="text-sm text-red-600">
                  Something went wrong.{' '}
                  <a
                    href={GITHUB_ISSUES_URL}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="underline"
                  >
                    Open an issue directly on GitHub ↗
                  </a>
                </p>
              )}

              <div className="flex items-center justify-end gap-3 pt-1">
                <button
                  type="button"
                  className="text-sm text-gray-500 hover:text-gray-700 cursor-pointer"
                  onClick={handleClose}
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={status === 'submitting'}
                  className="bg-gray-800 text-white text-sm px-4 py-2 rounded-lg hover:bg-gray-700 disabled:opacity-50 cursor-pointer"
                >
                  {status === 'submitting' ? 'Submitting…' : 'Submit'}
                </button>
              </div>
            </form>
          )}
        </div>
      </div>
    </div>,
    document.body
  )
}
