import { HelpCircle } from 'lucide-react'

export default function HelpButton({ onClick }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label="Help and tutorial"
      title="Help and tutorial"
      data-tour="help"
      className="fixed bottom-4 right-4 w-11 h-11 rounded-full shadow-lg flex items-center justify-center text-white hover:opacity-90 active:scale-95 transition cursor-pointer"
      style={{ background: 'var(--c-brand)', zIndex: 50 }}
    >
      <HelpCircle size={22} aria-hidden="true" />
    </button>
  )
}
