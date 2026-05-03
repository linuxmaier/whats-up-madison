import { useState, useRef, useEffect } from 'react'
import { CalendarDays, Send, Check } from 'lucide-react'
import { googleCalendarUrl, downloadIcal, shareCalendarInvite, formatEventText } from '../lib/calendarUtils'

export default function EventActionButtons({ event, compact = false }) {
  const [calOpen, setCalOpen] = useState(false)
  const [sendOpen, setSendOpen] = useState(false)
  const [showCheck, setShowCheck] = useState(false)
  const calRef = useRef(null)
  const sendRef = useRef(null)
  const iconSize = compact ? 13 : 14
  const btnPad = compact ? 'p-0.5' : 'p-1'

  useEffect(() => {
    if (!calOpen) return
    function handleOutside(e) {
      if (calRef.current && !calRef.current.contains(e.target)) setCalOpen(false)
    }
    document.addEventListener('mousedown', handleOutside)
    return () => document.removeEventListener('mousedown', handleOutside)
  }, [calOpen])

  useEffect(() => {
    if (!sendOpen) return
    function handleOutside(e) {
      if (sendRef.current && !sendRef.current.contains(e.target)) setSendOpen(false)
    }
    document.addEventListener('mousedown', handleOutside)
    return () => document.removeEventListener('mousedown', handleOutside)
  }, [sendOpen])

  function flashCheck() {
    setShowCheck(true)
    setTimeout(() => setShowCheck(false), 1500)
  }

  async function handleCopyText(e) {
    e.stopPropagation()
    await navigator.clipboard.writeText(formatEventText(event))
    setSendOpen(false)
    flashCheck()
  }

  async function handleSendInvite(e) {
    e.stopPropagation()
    const result = await shareCalendarInvite(event)
    setSendOpen(false)
    if (result?.downloaded) flashCheck()
  }

  return (
    <>
      <div className="relative" ref={calRef}>
        <button
          className={`text-gray-400 hover:text-gray-600 ${btnPad} rounded cursor-pointer`}
          onClick={e => { e.stopPropagation(); setCalOpen(o => !o); setSendOpen(false) }}
          title="Add to calendar"
        >
          <CalendarDays size={iconSize} />
        </button>
        {calOpen && (
          <div className="absolute right-0 top-6 z-10 bg-white border border-gray-200 rounded shadow-md text-sm min-w-max">
            <button
              className="block w-full text-left px-3 py-2 hover:bg-gray-50 whitespace-nowrap"
              onClick={e => { e.stopPropagation(); window.open(googleCalendarUrl(event), '_blank'); setCalOpen(false) }}
            >
              Google Calendar
            </button>
            <button
              className="block w-full text-left px-3 py-2 hover:bg-gray-50 whitespace-nowrap"
              onClick={e => { e.stopPropagation(); downloadIcal(event); setCalOpen(false) }}
            >
              Apple / Outlook (.ics)
            </button>
          </div>
        )}
      </div>
      <div className="relative" ref={sendRef}>
        <button
          className={`${btnPad} rounded cursor-pointer ${showCheck ? 'text-green-600' : 'text-gray-400 hover:text-gray-600'}`}
          onClick={e => { e.stopPropagation(); setSendOpen(o => !o); setCalOpen(false) }}
          title="Send / share event"
        >
          {showCheck ? <Check size={iconSize} /> : <Send size={iconSize} />}
        </button>
        {sendOpen && (
          <div className="absolute right-0 top-6 z-10 bg-white border border-gray-200 rounded shadow-md text-sm min-w-max">
            <button
              className="block w-full text-left px-3 py-2 hover:bg-gray-50 whitespace-nowrap"
              onClick={handleCopyText}
            >
              Copy text
            </button>
            <button
              className="block w-full text-left px-3 py-2 hover:bg-gray-50 whitespace-nowrap"
              onClick={handleSendInvite}
            >
              Calendar invite
            </button>
          </div>
        )}
      </div>
    </>
  )
}
