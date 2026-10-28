/**
 * The conversation's width and horizontal gutter, shared by the transcript, the notices and the
 * composer.
 *
 * The target is the DSH harness's chat column: its content is capped at 920px and its composer
 * card at 952px. We use the same pair. At wide sizes the column is 952px with 16px of side
 * padding, which leaves 920px for the words — wide enough to feel like a conversation rather than
 * a narrow sheet, and short enough that a line does not run the length of a 3200px monitor.
 *
 * The right side is wider than the left below `xl` on purpose: `PreviewTab` is absolutely
 * positioned over the chat pane's right edge, and a column that fills a narrow pane must not run
 * underneath it. At `xl` the column is narrower than the pane, so the tab is already outside it
 * and the padding can be symmetric.
 */
export const CHAT_COLUMN = 'mx-auto w-full max-w-[952px]'

export const CHAT_GUTTER = 'pl-4 pr-10 sm:pl-6 sm:pr-12 xl:px-4'
