/**
 * The two things a DOM test needs that vitest and jsdom do not do for us.
 *
 * React only batches state updates inside `act` when it is told it is in a test environment, and
 * Testing Library's automatic detection does not fire with `globals: false`. Without this,
 * `renderHook` updates land outside `act` and every assertion races the renderer — which is
 * exactly what the first run of `useConversation.test.tsx` did
 * (the internal audit WEB-16).
 *
 * jsdom implements `<dialog>`'s `open` property but not the two methods that drive it, and the
 * modal's focus trap, backdrop and Escape are deliberately the platform's rather than
 * hand-rolled (`ui/dialog.tsx`). The stubs below provide the two calls the component makes and
 * nothing else, so a dialog test exercises the real component without reimplementing the
 * browser.
 *
 * Loaded for every suite; harmless for the node-environment ones, which have no React.
 */

export {}

declare global {
  // eslint-disable-next-line no-var
  var IS_REACT_ACT_ENVIRONMENT: boolean
}

// React reads this as a bare identifier, so it has to be on the global object.
;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

if (typeof HTMLDialogElement !== 'undefined') {
  HTMLDialogElement.prototype.showModal = function showModal(this: HTMLDialogElement) {
    this.setAttribute('open', '')
  }
  HTMLDialogElement.prototype.close = function close(this: HTMLDialogElement) {
    this.removeAttribute('open')
    this.dispatchEvent(new Event('close'))
  }
}
