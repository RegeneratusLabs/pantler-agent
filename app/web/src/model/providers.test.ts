import { describe, expect, it } from 'vitest'
import { PROVIDERS, modelProblem, modelValues, providerById } from './providers'

const ENV_NAME = /^[A-Za-z_][A-Za-z0-9_]*$/

describe('the provider catalogue', () => {
  it('offers a small, unique list with the custom endpoint last', () => {
    expect(PROVIDERS.map(provider => provider.id)).toEqual([
      'deepseek',
      'anthropic',
      'openrouter',
      'custom'
    ])
    expect(new Set(PROVIDERS.map(provider => provider.id)).size).toBe(PROVIDERS.length)
    expect(PROVIDERS.at(-1)?.custom).toBe(true)
  })

  it('names a key the engine can persist for every provider', () => {
    for (const provider of PROVIDERS) {
      expect(provider.keyEnv).toMatch(ENV_NAME)
      expect(provider.blurb.length).toBeGreaterThan(20)
    }
  })

  it('pins every preset to the endpoint and transport the engine uses', () => {
    // Copied from hermes_cli/auth.py::PROVIDER_REGISTRY and providers.py::TRANSPORT_TO_API_MODE.
    // A wrong value here is a key stored against the wrong endpoint, found only on the first turn.
    const byId = Object.fromEntries(PROVIDERS.map(provider => [provider.id, provider]))
    expect(byId.deepseek.baseUrl).toBe('https://api.deepseek.com/v1')
    expect(byId.deepseek.apiMode).toBe('chat_completions')
    expect(byId.anthropic.baseUrl).toBe('https://api.anthropic.com')
    expect(byId.anthropic.apiMode).toBe('anthropic_messages')
    expect(byId.openrouter.baseUrl).toBe('https://openrouter.ai/api/v1')
    expect(byId.openrouter.apiMode).toBe('chat_completions')
  })

  it('suggests a model that is one of its own choices', () => {
    for (const provider of PROVIDERS) {
      if (provider.custom) {
        expect(provider.defaultModel).toBe('')
        expect(provider.models).toEqual([])
      } else {
        expect(provider.models).toContain(provider.defaultModel)
      }
    }
  })
})

describe('what the form writes', () => {
  const deepseek = providerById('deepseek')!

  it('names every model key, because set_model merges and a stale base_url would win', () => {
    expect(
      modelValues({
        provider: deepseek,
        model: ' deepseek-chat ',
        keyEnv: ' DEEPSEEK_API_KEY ',
        baseUrl: 'ignored for a preset'
      })
    ).toEqual({
      provider: 'deepseek',
      default: 'deepseek-chat',
      base_url: 'https://api.deepseek.com/v1',
      api_mode: 'chat_completions',
      key_env: 'DEEPSEEK_API_KEY'
    })
  })

  it('writes the operator’s endpoint and key name for a custom provider', () => {
    const custom = providerById('custom')!
    expect(
      modelValues({
        provider: custom,
        model: 'qwen2.5:7b',
        keyEnv: 'LOCAL_LLM_KEY',
        baseUrl: 'http://127.0.0.1:11434/v1'
      })
    ).toEqual({
      provider: 'custom',
      default: 'qwen2.5:7b',
      base_url: 'http://127.0.0.1:11434/v1',
      api_mode: 'chat_completions',
      key_env: 'LOCAL_LLM_KEY'
    })
  })
})

describe('what the form refuses', () => {
  const deepseek = providerById('deepseek')!

  it('wants a model', () => {
    expect(modelProblem({ provider: deepseek, model: '  ', keyEnv: 'DEEPSEEK_API_KEY', baseUrl: '' })).toMatch(/model/i)
  })

  it('wants a key name the engine will read', () => {
    expect(modelProblem({ provider: deepseek, model: 'deepseek-chat', keyEnv: 'not a name', baseUrl: '' })).toMatch(
      /environment-variable name/i
    )
  })

  it('wants an https endpoint for a custom provider, or loopback for a local one', () => {
    const custom = providerById('custom')!
    const base = { provider: custom, model: 'm', keyEnv: 'CUSTOM_API_KEY' }
    expect(modelProblem({ ...base, baseUrl: '' })).toMatch(/base URL/i)
    expect(modelProblem({ ...base, baseUrl: 'api.example.com/v1' })).toMatch(/not a URL/i)
    expect(modelProblem({ ...base, baseUrl: 'http://example.com/v1' })).toMatch(/https/i)
    expect(modelProblem({ ...base, baseUrl: 'https://api.example.com/v1' })).toBeNull()
    expect(modelProblem({ ...base, baseUrl: 'http://127.0.0.1:11434/v1' })).toBeNull()
  })
})
