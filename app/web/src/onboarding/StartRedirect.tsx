/**
 * Where the app opens for someone who has not been set up yet.
 *
 * This is the entry point only — it stands where the catch-all route used to send everyone to the
 * chat. It deliberately does **not** wrap every route: a person halfway through setup who follows
 * the apps link into Settings must be allowed to go there, and a guard that drags them back to step
 * one would be the app arguing with its own instructions. What it guarantees is the thing that
 * matters — nobody lands in an empty conversation with no idea what to type.
 */

import { Navigate } from 'react-router'
import { needsSetup } from './flow'
import { useOperatorProfile } from './profile'

export function StartRedirect() {
  const profile = useOperatorProfile()
  return <Navigate to={needsSetup(profile) ? '/welcome' : '/chat'} replace />
}
