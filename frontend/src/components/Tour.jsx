import { Joyride, STATUS } from 'react-joyride'

const STEPS = [
  {
    target: 'body',
    placement: 'center',
    disableBeacon: true,
    content: "Welcome! Here's a quick tour of how to use What's Up Madison.",
  },
  {
    target: '[data-tour="search"]',
    disableBeacon: true,
    content: 'Type here to search every upcoming event by title, description, or venue.',
  },
  {
    target: '[data-tour="view-toggle"]',
    disableBeacon: true,
    content: "Switch between a time-grouped list and a map of Madison with clustered pins.",
  },
  {
    target: '[data-tour="categories"]',
    disableBeacon: true,
    content: 'Filter events by type — music, food, family, free, etc. Your choices are remembered.',
  },
  {
    target: '[data-tour="venues"]',
    disableBeacon: true,
    content: "Hide venues you're not interested in so they stop appearing in your results.",
  },
  {
    target: '[data-tour="date-picker"]',
    disableBeacon: true,
    content: "Pick any date. Click the brand logo in the corner to jump back to today.",
  },
  {
    target: '[data-tour="help"]',
    disableBeacon: true,
    placement: 'left',
    content: 'Click this anytime to reopen the guide or replay the tour.',
  },
]

const JOYRIDE_STYLES = {
  options: {
    primaryColor: 'var(--c-brand)',
    zIndex: 10001,
  },
}

export default function Tour({ run, onClose }) {
  function handleCallback({ status }) {
    if (status === STATUS.FINISHED || status === STATUS.SKIPPED) {
      onClose()
    }
  }

  return (
    <Joyride
      steps={STEPS}
      run={run}
      continuous
      showProgress
      showSkipButton
      scrollToFirstStep
      disableScrolling={false}
      styles={JOYRIDE_STYLES}
      callback={handleCallback}
    />
  )
}
