import { Joyride, STATUS, ACTIONS, EVENTS } from 'react-joyride'

const LIST_STEPS = [
  {
    target: '[data-tour="search"]',
    skipBeacon: true,
    content: 'Type here to search every upcoming event by title, description, or venue.',
  },
  {
    target: '[data-tour="view-toggle"]',
    skipBeacon: true,
    content: "Switch between a time-grouped list and a map of Madison with clustered pins.",
  },
  {
    target: '[data-tour="categories"]',
    skipBeacon: true,
    content: 'Filter events by type — music, food, family, free, etc. Your choices are remembered.',
  },
  {
    target: '[data-tour="venues"]',
    skipBeacon: true,
    content: "Look up a specific venue, or hide venues you're not interested in.",
  },
  {
    target: '[data-tour="date-picker"]',
    skipBeacon: true,
    content: "Pick any date. Click What's Up Madison to jump back to today.",
  },
  {
    target: '[data-tour="help"]',
    skipBeacon: true,
    placement: 'left',
    content: 'Click this anytime to reopen the guide or replay the tour.',
  },
]

const MAP_STEPS = [
  {
    target: '[data-tour="view-toggle"]',
    skipBeacon: true,
    content: 'Tap List to browse the day grouped by time of day instead.',
  },
  {
    target: '[data-tour="categories"]',
    skipBeacon: true,
    content: 'Filter the pins by event type. Your choices are remembered between visits.',
  },
  {
    target: '[data-tour="venues"]',
    skipBeacon: true,
    content: 'Look up a specific venue on the map.',
  },
  {
    target: '[data-tour="date-picker"]',
    skipBeacon: true,
    content: "Pick a date to see that day's events on the map.",
  },
  {
    target: '[data-tour="help"]',
    skipBeacon: true,
    placement: 'left',
    content: 'Click this anytime to reopen the guide or replay the tour.',
  },
]

const JOYRIDE_OPTIONS = {
  primaryColor: 'var(--c-brand)',
  zIndex: 10001,
  showProgress: true,
  // Anchors live in the sticky header — there's nothing to scroll to. Without
  // skipScroll, Joyride re-runs its scroll positioning on each Next/Back and
  // drifts the page by a few pixels every step when the user is scrolled down.
  skipScroll: true,
  // Default ('close') merely advances to the next step in continuous mode.
  // We want the tooltip X to end the tour.
  closeButtonAction: 'skip',
}

const TERMINAL_STATUSES = new Set([STATUS.FINISHED, STATUS.SKIPPED])

export default function Tour({ run, mode, onClose }) {
  // v3 renamed v2's `callback` prop to `onEvent`. Without this, the parent
  // never learns the tour ended (FINISHED, SKIPPED, or CLOSE), and the
  // "Start interactive tour" button feels dead because tourRunning stays true.
  function handleEvent(data) {
    const { status, action, type } = data
    if (
      TERMINAL_STATUSES.has(status)
      || action === ACTIONS.CLOSE
      || type === EVENTS.TARGET_NOT_FOUND
    ) {
      onClose()
    }
  }

  const steps = mode === 'map' ? MAP_STEPS : LIST_STEPS

  return (
    <Joyride
      steps={steps}
      run={run}
      continuous
      options={JOYRIDE_OPTIONS}
      onEvent={handleEvent}
    />
  )
}
