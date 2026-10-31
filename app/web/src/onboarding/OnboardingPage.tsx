/**
 * The first run, as a screen.
 *
 * Full-screen and outside `AppShell` on purpose: there is no rail, no session list and no engine
 * notice here, because a person being shown around for the first time has nothing to navigate to
 * yet and a rail full of unfamiliar words is the fastest way to lose them. The chrome arrives when
 * setup ends.
 *
 * The state is one `useState` for the step and the shared profile store for the answers, so a closed
 * tab loses the position and keeps everything else. `Back` is always there except on the first
 * screen, `Skip` is always there, and neither is hidden behind a menu.
 */

import { useState } from 'react'
import { useNavigate } from 'react-router'
import { PantlerMark } from '../brand/PantlerMark'
import { Wordmark } from '../brand/Wordmark'
import { Button } from '../ui/button'
import { Dots } from './kit'
import { STEPS, nextStep, previousStep, progressOf, type StepId } from './flow'
import { operatorProfile, useOperatorProfile } from './profile'
import { StepBody } from './steps'

export function OnboardingPage() {
  const profile = useOperatorProfile()
  const navigate = useNavigate()
  const [step, setStep] = useState<StepId>('welcome')

  const current = STEPS.find(entry => entry.id === step) ?? STEPS[0]
  const { index, total } = progressOf(step)
  const forward = nextStep(step)

  /**
   * Leaving, either way, finishes setup. Skipping is an answer — a person who says "not now" and is
   * asked again every time they open the app has been given a worse product than one who is never
   * asked at all. Settings can start it again.
   */
  const leave = (to: string) => {
    operatorProfile.update({ complete: true })
    void navigate(to, { replace: true })
  }

  const advance = () => {
    if (forward) {
      setStep(forward)
      return
    }
    leave('/chat')
  }

  return (
    /* Exactly one viewport tall, never taller. `min-h-dvh` was here and it was wrong: the column
       grew to fit the step's content, `main` was therefore never shorter than what it held, so it
       scrolled by nothing and the footer was painted below the fold — with `body` set to
       `overflow: hidden`, there was no scroll anywhere that could bring Next back. A bounded height
       is what makes `main` the thing that scrolls, and the footer the thing that stays. */
    <div className="flex h-dvh flex-col overflow-hidden bg-canvas text-ink">
      <header className="flex items-center justify-between gap-4 px-5 py-4 sm:px-8">
        <span className="flex min-w-0 items-center gap-3">
          <PantlerMark state="idle" size={32} interactive />
          <span className="hidden sm:block">
            <Wordmark />
          </span>
        </span>
        <Dots index={index} total={total} />
        <Button variant="ghost" size="sm" onClick={() => leave('/chat')}>
          Skip setup
        </Button>
      </header>

      <main className="flex min-h-0 flex-1 justify-center overflow-y-auto px-5 pb-8 sm:px-8">
        <div className="w-full max-w-xl py-6">
          <StepBody
            step={current.id}
            profile={profile}
            update={patch => void operatorProfile.update(patch)}
            go={setStep}
          />
        </div>
      </main>

      {/* A normal flex child, not `sticky`: pinned overlap looks fine until the last row of a long
          step slides under it, and "the button ate my last example" is a bad first impression. */}
      <footer className="border-t border-line bg-canvas px-5 py-4 sm:px-8">
        <div className="mx-auto flex w-full max-w-xl items-center justify-between gap-4">
          <Button
            variant="ghost"
            size="lg"
            disabled={previousStep(step) === null}
            onClick={() => {
              const back = previousStep(step)
              if (back) setStep(back)
            }}
          >
            Back
          </Button>
          <Button variant="primary" size="lg" onClick={advance}>
            {forward ? 'Next' : 'Start using it'}
          </Button>
        </div>
      </footer>
    </div>
  )
}
