// @vitest-environment jsdom
/**
 * The connect form: what it writes, what it refuses, and what it says when it cannot apply the
 * write itself.
 *
 * The form takes its BFF and its settings as props, so these tests never mock the app context —
 * they exercise the same component Settings and the first run render.
 */

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { EngineSettings } from '@shared/wire'
import { ModelForm } from './ModelForm'

const blank: EngineSettings = { available: true, model: {}, keys: [] }

function api() {
  return {
    saveKey: vi.fn(async (name: string) => ({ name, is_set: true, restart_required: true })),
    saveModel: vi.fn(async (values: Record<string, string>) => ({
      model: values,
      restart_required: true
    })),
    clearKey: vi.fn(async (name: string) => ({ name, is_set: false, restart_required: true }))
  }
}

afterEach(() => {
  cleanup()
  delete window.pantler
})

describe('connecting a model', () => {
  it('writes the key, then the model block, and names the restart in a browser', async () => {
    const bff = api()
    const onSaved = vi.fn()
    render(<ModelForm settings={blank} bff={bff} onSaved={onSaved} />)

    fireEvent.change(screen.getByPlaceholderText('paste the key'), {
      target: { value: 'sk-test' }
    })
    fireEvent.click(screen.getByRole('button', { name: 'Connect' }))

    await waitFor(() => expect(bff.saveModel).toHaveBeenCalledTimes(1))
    expect(bff.saveKey).toHaveBeenCalledWith('DEEPSEEK_API_KEY', 'sk-test')
    expect(bff.saveModel).toHaveBeenCalledWith({
      provider: 'deepseek',
      default: 'deepseek-chat',
      base_url: 'https://api.deepseek.com/v1',
      api_mode: 'chat_completions',
      key_env: 'DEEPSEEK_API_KEY'
    })
    expect(onSaved).toHaveBeenCalledTimes(1)
    // No window.pantler in jsdom: the copy must not pretend the model is live.
    expect(await screen.findByText(/restart the engine to apply/i)).toBeTruthy()
  })

  it('does not rewrite a key that is already set', async () => {
    const bff = api()
    const settings: EngineSettings = {
      available: true,
      model: {
        provider: 'deepseek',
        default: 'deepseek-chat',
        base_url: 'https://api.deepseek.com/v1',
        api_mode: 'chat_completions',
        key_env: 'DEEPSEEK_API_KEY'
      },
      keys: [{ name: 'DEEPSEEK_API_KEY', is_set: true }]
    }
    render(<ModelForm settings={settings} bff={bff} />)

    fireEvent.change(screen.getByDisplayValue('deepseek-chat'), {
      target: { value: 'deepseek-reasoner' }
    })
    fireEvent.click(screen.getByRole('button', { name: 'Connect' }))

    await waitFor(() => expect(bff.saveModel).toHaveBeenCalledTimes(1))
    expect(bff.saveKey).not.toHaveBeenCalled()
    expect(bff.saveModel).toHaveBeenCalledWith(
      expect.objectContaining({ default: 'deepseek-reasoner', key_env: 'DEEPSEEK_API_KEY' })
    )
  })

  it('asks the host to restart the engine and reports it connected', async () => {
    const restartEngine = vi.fn(async () => ({ ok: true }))
    window.pantler = { restartEngine }
    const bff = api()
    render(<ModelForm settings={blank} bff={bff} />)

    fireEvent.change(screen.getByPlaceholderText('paste the key'), {
      target: { value: 'sk-test' }
    })
    fireEvent.click(screen.getByRole('button', { name: 'Connect' }))

    await waitFor(() => expect(restartEngine).toHaveBeenCalledTimes(1))
    expect(await screen.findByText(/Connected\. The engine restarted/i)).toBeTruthy()
  })

  it('reports a host that could not restart instead of claiming success', async () => {
    window.pantler = {
      restartEngine: vi.fn(async () => ({ ok: false, error: 'the engine refused to start' }))
    }
    const bff = api()
    render(<ModelForm settings={blank} bff={bff} />)

    fireEvent.change(screen.getByPlaceholderText('paste the key'), {
      target: { value: 'sk-test' }
    })
    fireEvent.click(screen.getByRole('button', { name: 'Connect' }))

    expect(await screen.findByRole('alert')).toBeTruthy()
    expect(screen.getByRole('alert').textContent).toMatch(/the engine refused to start/i)
  })

  it('will not write a custom provider without an endpoint', async () => {
    const bff = api()
    render(<ModelForm settings={blank} bff={bff} />)

    fireEvent.change(screen.getByRole('combobox', { name: /^Provider/ }), {
      target: { value: 'custom' }
    })
    fireEvent.change(screen.getByPlaceholderText('paste the key'), { target: { value: 'sk-test' } })
    fireEvent.change(screen.getByPlaceholderText('your-model-id'), { target: { value: 'local-model' } })
    fireEvent.click(screen.getByRole('button', { name: 'Connect' }))

    expect((await screen.findByRole('alert')).textContent).toMatch(/base URL/i)
    expect(bff.saveModel).not.toHaveBeenCalled()
  })
})
