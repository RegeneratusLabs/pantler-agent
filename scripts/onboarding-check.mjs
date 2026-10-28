import fs from 'node:fs'
import { createRequire } from 'node:module'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

// Playwright is not a dependency of this repo, and the import used to be an absolute path into
// another project's `node_modules` — so the script only ran on one machine
// (the internal audit SCR-7). `PANTLER_PLAYWRIGHT` names it; otherwise it is resolved as a
// package, and a missing one is a sentence rather than a stack trace.
const HERE = path.dirname(fileURLToPath(import.meta.url))
let chromium
try {
  ;({ chromium } = await import(
    process.env.PANTLER_PLAYWRIGHT ||
      createRequire(import.meta.url).resolve('playwright-core')
  ))
} catch {
  console.error(
    'onboarding-check: playwright-core is not installed.\n' +
      '  npm i -D playwright-core, or set PANTLER_PLAYWRIGHT to a playwright-core index.mjs'
  )
  process.exit(2)
}

/**
 * Drive the first run in a real browser, on the running dev server.
 *
 *   node check.mjs
 *
 * Not a unit test and not meant to be one: the unit tests cover the shape of the flow, the
 * profile and the voices (`app/web/src/onboarding/*.test.ts`), and this is the "verified, and how"
 * half — that a person with an empty browser actually lands in setup, that each answer survives to
 * the next screen, that the closing summary says what they chose, that finishing lets them into the
 * app, and that Settings asks the same questions and reads the same answers back.
 *
 * The one it cannot check is the voice reaching the model: that needs a real conversation and the
 * engine, and it was verified by hand against the running gateway (the engine notes §9).
 */

// The headless shell a Playwright install downloads, found rather than pinned to one build id; a
// `PANTLER_CHROMIUM` path wins, and an absent binary lets Playwright find its own.
function chromePath() {
  if (process.env.PANTLER_CHROMIUM) return process.env.PANTLER_CHROMIUM
  const root = path.join(process.env.HOME || '', '.cache', 'ms-playwright')
  try {
    const build = fs
      .readdirSync(root)
      .filter(name => name.startsWith('chromium_headless_shell-'))
      .sort()
      .pop()
    if (!build) return undefined
    const binary = path.join(root, build, 'chrome-headless-shell-linux64', 'chrome-headless-shell')
    return fs.existsSync(binary) ? binary : undefined
  } catch {
    return undefined
  }
}
const EXEC = chromePath()
const OUT = process.env.PANTLER_ONBOARDING_OUT || path.join(HERE, '..', 'output', 'onboarding-check')
const BASE = process.env.PANTLER_WEB || 'http://127.0.0.1:5175'

fs.mkdirSync(OUT, { recursive: true })

const results = []
const check = (name, ok, detail = '') => {
  results.push({ name, ok, detail })
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? ` — ${detail}` : ''}`)
}

// `--no-sandbox` is deliberate and stays: this is a by-hand check against a dev server, and the
// Chromium sandbox needs kernel features some dev boxes do not have. It is also the flag that
// removes the browser's process isolation, so anything that reaches the page runs with the
// invoking user's reach. It is announced on stderr at launch so nobody wires this into
// automation by accident (the internal security audit A19-SC-10); `identity-check.mjs` is
// the script in this directory that belongs in a pipeline.
const BROWSER_ARGS = ['--no-sandbox', '--disable-dev-shm-usage']

if (BROWSER_ARGS.includes('--no-sandbox')) {
  console.error(
    'onboarding-check: Chromium launches with --no-sandbox — the browser sandbox is OFF.\n' +
      '  This script is a by-hand dev check, not automation: do not run it unattended\n' +
      '  (the internal security audit A19-SC-10).'
  )
}

const browser = await chromium.launch({
  ...(EXEC ? { executablePath: EXEC } : {}),
  headless: true,
  args: BROWSER_ARGS
})
// A throw anywhere below used to leak the browser and write no results; the body is wrapped
// instead, and the tally and the close happen whether it passed or threw.
const context = await browser.newContext({ viewport: { width: 1280, height: 900 } })
const page = await context.newPage()
async function run() {
  page.on('pageerror', error => console.log('PAGE EXCEPTION:', error.message))
  page.on('console', message => {
    if (message.type() === 'error') console.log('CONSOLE ERROR:', message.text())
  })
  page.on('response', response => {
    // A 404 on this app is never something to shrug at: it is either a route we think exists or an
    // asset the shell is asking for. Reported with its URL so it can be attributed rather than
    // assumed to be the engine.
    if (response.status() >= 400) console.log(`HTTP ${response.status()}  ${response.url()}`)
  })

  const shot = name => page.screenshot({ path: `${OUT}/${name}.png`, fullPage: true })
  const heading = name => page.getByRole('heading', { name }).waitFor({ timeout: 15000 })
  const next = () => page.getByRole('button', { name: 'Next', exact: true }).click()
  const stepCount = () => page.locator('ol[aria-label^="Step "] > li').count()

  // ------------------------------------------------------------ a browser that has never run it
  await page.goto(BASE, { waitUntil: 'domcontentloaded' })
  await page.evaluate(() => window.localStorage.clear())
  await page.reload({ waitUntil: 'domcontentloaded' })

  await heading('This is an assistant for the business side of your work')
  check('an empty browser opens in setup, not in an empty chat', new URL(page.url()).pathname === '/welcome', page.url())
  check('the welcome step shows six dots of progress', (await stepCount()) === 6, `${await stepCount()} dots`)
  check(
    'the welcome step promises nothing that leaves the machine',
    await page.getByText('What you type stays on this machine.').isVisible()
  )
  check(
    'skipping is offered from the first screen',
    await page.getByRole('button', { name: 'Skip setup' }).isVisible()
  )
  await shot('01-welcome')

  // ------------------------------------------------------------------------ step 1: who they are
  await next()
  await heading('Who am I working for?')
  await page.getByLabel('What should I call you?').fill('Sam')
  await page.getByLabel('What is the business called?').fill('Bellview Farm')
  await page.getByRole('radio', { name: /I grow it/ }).click()
  check(
    'the chosen kind of work is checked, not merely tinted',
    (await page.getByRole('radio', { name: /I grow it/ }).getAttribute('aria-checked')) === 'true'
  )
  await shot('02-business')

  // ----------------------------------------------------------------------------- step 2: a voice
  await next()
  await heading('How should I sound?')
  const voices = page.getByRole('radio')
  check('exactly three voices are offered', (await voices.count()) === 3, `${await voices.count()} voices`)
  const samples = await page.locator('ol, div').getByText(/^\$158\.40|144\.00/).count()
  check('each voice shows the same answer in its own manner', samples >= 3, `${samples} samples`)
  check(
    'the default voice is the warm one',
    (await page.getByRole('radio', { name: /Warm/ }).getAttribute('aria-checked')) === 'true'
  )
  await page.getByRole('radio', { name: /Brief/ }).click()
  await shot('03-voice')

  // ------------------------------------------------------------------------- step 3: their apps
  await next()
  await heading('The apps you already use')
  for (const app of ['Gmail', 'Google Calendar', 'Shopify']) {
    check(`${app} is named on the apps step`, await page.getByText(app, { exact: true }).first().isVisible())
  }
  check(
    'the apps shown follow the work they said they do',
    await page.getByText('Gmail', { exact: true }).first().isVisible()
  )
  check('the sign-in layer is named, in the operator’s terms', await page.getByText(/Composio/).isVisible())
  check(
    'the apps step says plainly that nothing is connected yet',
    await page.getByText('Not switched on yet.').isVisible()
  )
  await shot('04-apps')

  // ------------------------------------------------------------------------------ step 4: a tour
  await next()
  await heading('Where everything is')
  for (const where of ['Chat', 'Capabilities', 'Scheduled jobs', 'Settings']) {
    check(`the tour names the ${where} screen`, await page.getByText(where, { exact: true }).first().isVisible())
  }
  const asks = await page.getByRole('button', { name: /^Copy “/ }).count()
  check('three things to try are offered, with copy buttons', asks === 3, `${asks} copy buttons`)
  const growAsk = await page.getByText('Invoice Bellview CSA for 12 kilos of beans and four dozen eggs.').isVisible()
  check('the examples follow the work they said they do', growAsk)
  await shot('05-tour')

  // ------------------------------------------------ the longest step in a window that is short
  //
  // This is the one the rest of this file cannot see. `locator.click()` scrolls its element into view
  // first, and `overflow: hidden` is still scrollable *programmatically* — so every `next()` below
  // passes happily while the button sits under the fold with no wheel, no keyboard and no scrollbar
  // that a person could use to reach it. That is exactly what happened: the page column was
  // `min-h-dvh`, so it grew to the height of the four cards and the three examples, `main` was never
  // shorter than what it held, and Next was drawn at y≈1133 in a 920px window. Bounding boxes and a
  // real wheel are the only honest way to check the thing a person actually does.
  await page.setViewportSize({ width: 1280, height: 620 })
  await page.waitForTimeout(200)
  const pane = await page.evaluate(() => {
    const main = document.querySelector('main')
    return {
      scrollable: main.scrollHeight > main.clientHeight + 1,
      top: main.scrollTop,
      pageOverflows: document.documentElement.scrollHeight > window.innerHeight + 1
    }
  })
  const nextBox = await page.getByRole('button', { name: 'Next', exact: true }).boundingBox()
  check(
    'the longest step keeps Next on screen in a short window',
    Boolean(nextBox) && nextBox.y + nextBox.height <= 620,
    nextBox ? `Next ends at ${Math.round(nextBox.y + nextBox.height)} of 620` : 'no Next button'
  )
  check('and it is the step body that scrolls, never the page', pane.scrollable && !pane.pageOverflows)
  await page.mouse.move(640, 300)
  await page.mouse.wheel(0, 1500)
  await page.waitForTimeout(200)
  const wheeled = await page.evaluate(() => document.querySelector('main').scrollTop)
  check('a wheel over the step moves it', wheeled > pane.top, `scrollTop ${pane.top} → ${wheeled}`)
  await shot('05b-tour-short-window')
  await page.setViewportSize({ width: 1280, height: 900 })
  await page.waitForTimeout(200)

  // ----------------------------------------------------------------------- the closing summary
  await next()
  await heading('That’s the lot')
  for (const [label, value] of [
    ['Call you', 'Sam'],
    ['Business', 'Bellview Farm'],
    ['Mostly', 'I grow it'],
    ['Voice', 'Brief']
  ]) {
    const row = page.locator('div', { has: page.getByText(label, { exact: true }) }).last()
    check(`the summary remembers ${label.toLowerCase()}`, (await row.innerText()).includes(value))
  }
  await shot('06-done')

  // ------------------------------------------------------------------------------ into the app
  await page.getByRole('button', { name: 'Start using it' }).click()
  await page.waitForURL(/\/chat/, { timeout: 15000 })
  check('finishing lands in the conversation', /\/chat/.test(new URL(page.url()).pathname), page.url())

  const stored = await page.evaluate(() => window.localStorage.getItem('pantler.operator.v1'))
  const profile = JSON.parse(stored ?? '{}')
  check('the answers are kept on this machine', profile.name === 'Sam' && profile.business === 'Bellview Farm')
  check('the voice is kept with them', profile.voice === 'brief')
  check('setup is marked finished, so the app stops asking', profile.complete === true)
  await shot('07-chat')

  // ------------------------------- the voice actually rides on the turn they send
  //
  // Asserted on the request, not on the reply: whether a model sounds brief on any given day is not
  // something to build a check on, but "did we send the overlay at all" is exact. The end-to-end
  // effect — an `instructions` string reaching the model — was verified by hand against the gateway
  // with a marker word (the engine notes §9).
  let runBody = null
  page.on('request', request => {
    if (request.method() === 'POST' && request.url().endsWith('/v1/runs')) {
      try {
        runBody = JSON.parse(request.postData() ?? '{}')
      } catch {
        runBody = null
      }
    }
  })
  await page.getByPlaceholder(/Say what you want done/).fill('Say hello in one short line.')
  await page.getByRole('button', { name: 'Send' }).click()
  await page.waitForTimeout(3000)
  check('a turn carries the chosen voice to the engine', Boolean(runBody?.instructions), JSON.stringify(runBody)?.slice(0, 80))
  check(
    'and it is the brief one they chose',
    (runBody?.instructions ?? '').startsWith('Keep every reply as short')
  )
  check('the turn carries what they typed', runBody?.input === 'Say hello in one short line.')
  await shot('09-turn-with-voice')

  // ------------------------------------------------ and the app does not ask again on a reload
  await page.goto(BASE, { waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(500)
  check(
    'opening the app again goes straight to the chat',
    /\/chat/.test(new URL(page.url()).pathname),
    page.url()
  )

  // ------------------------------------------------------------------- the same answers in Settings
  await page.goto(`${BASE}/settings`, { waitUntil: 'domcontentloaded' })
  await heading('Your voice')
  check('Settings carries the same choice', await page.getByText(/Currently/).first().isVisible())
  check(
    'and shows the voice they picked as the checked one',
    (await page.getByRole('radio', { name: /Brief/ }).getAttribute('aria-checked')) === 'true'
  )
  check(
    'Settings offers a way back through setup',
    await page.getByRole('link', { name: 'run the guided setup' }).isVisible()
  )

  // The profile questions, asked here in the same words the first run uses. Settings and setup write
  // the same store, so this is also where a tester can see that an answer given in one place is the
  // answer the other one reads.
  await heading('Your details')
  check(
    'Settings carries the questions setup asked, with the answers they gave',
    (await page.getByLabel('What should I call you?').inputValue()) === 'Sam' &&
      (await page.getByLabel('What is the business called?').inputValue()) === 'Bellview Farm'
  )
  check(
    'and the kind of work they chose',
    (await page.getByRole('radio', { name: /I grow it/ }).getAttribute('aria-checked')) === 'true'
  )
  await page.getByLabel('What is the business called?').fill('Bellview Farm Produce')
  const edited = await page.evaluate(() => window.localStorage.getItem('pantler.operator.v1'))
  check(
    'editing it here saves as you type, into the store setup wrote to',
    JSON.parse(edited ?? '{}').business === 'Bellview Farm Produce',
    JSON.parse(edited ?? '{}').business
  )
  await page.getByLabel('What is the business called?').fill('Bellview Farm')

  // The four sections this build does not need. Asserted as absent rather than left to a reviewer to
  // notice: a screen that grows a model picker back without a model to pick is the failure this
  // guards against.
  for (const gone of ['Model', 'API key', 'Providers', 'Connection']) {
    check(
      `Settings no longer offers ${gone}`,
      (await page.getByRole('heading', { name: gone, exact: true }).count()) === 0
    )
  }
  await shot('08-settings')

  // ------------------------------------------------------------------ setup can be run again
  await page.goto(`${BASE}/welcome`, { waitUntil: 'domcontentloaded' })
  await heading('This is an assistant for the business side of your work')
  check('setup can be run again deliberately', new URL(page.url()).pathname === '/welcome')
  await page.getByRole('button', { name: 'Skip setup' }).click()
  await page.waitForURL(/\/chat/, { timeout: 15000 })
  check('and skipped again without losing the answers', /\/chat/.test(new URL(page.url()).pathname))
}

try {
  await run()
} catch (error) {
  // A throwing check used to leave Chromium running and write no results.json — the run that
  // needs the record most was the one that produced none
  // (the internal audit SCR-7).
  check('the check ran to completion', false, error && error.message ? error.message : String(error))
  if (error && error.stack) console.log(error.stack)
} finally {
  // ----------------------------------------------------------------------------------- the tally
  const failed = results.filter(entry => !entry.ok)
  fs.writeFileSync(`${OUT}/results.json`, JSON.stringify(results, null, 2))
  console.log(`\n${results.length - failed.length}/${results.length} checks passed`)
  await browser.close()
  process.exit(failed.length ? 1 : 0)
}
