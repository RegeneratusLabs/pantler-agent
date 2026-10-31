/**
 * The tour: four cards, in the order the operator will meet them, and a few things worth saying.
 *
 * A guided tour of a five-screen app is a way of making someone sit through what they could have
 * seen by looking. What is worth the two minutes is *orientation* — which box does what, and what
 * happens when you type — so each card names one part of the app in the words on the rail beside it
 * (`shell/Sidebar.tsx`), says what it is for in one sentence, and stops.
 *
 * The three things worth trying are not here: they are shared with the new-chat empty state and
 * live in `chat/examples.ts`, so the tour and the chat cannot drift apart.
 */

export interface TourCard {
  id: string
  /** The name on the rail, so the tour and the app agree. */
  where: string
  title: string
  body: string
}

export const TOUR: TourCard[] = [
  {
    id: 'chat',
    where: 'Chat',
    title: 'Say it in your own words',
    body: 'The conversation is the whole app. You do not need the right words or a special command — “invoice the cafe for twelve kilos of beans” is enough, and if I am unsure I will ask instead of guessing.'
  },
  {
    id: 'capabilities',
    where: 'Capabilities',
    title: 'What I’m allowed to do',
    body: 'Every switch is here, in plain names, and everything is off unless you turn it on. This is the page to look at if you ever want to know what I can reach.'
  },
  {
    id: 'jobs',
    where: 'Scheduled jobs',
    title: 'Things that come back on their own',
    body: 'A reminder that repeats — a compliance date, a market day, a delivery that goes out every Tuesday. Set the day and the time once, and it runs without being asked; each run’s output stays under the job.'
  },
  {
    id: 'settings',
    where: 'Settings',
    title: 'Where the knobs are',
    body: 'Your voice, the apps you connect, and the engine this app talks to. Nothing there is urgent, and nothing there can lose your records.'
  }
]
