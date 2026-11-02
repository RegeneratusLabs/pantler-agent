/**
 * The bring-your-own-key catalogue.
 *
 * A fresh profile has no `model:` block and the engine ships no key, so the first run and
 * Settings have to ask. This table is deliberately small and explicit rather than a proxy of the
 * engine's `/api/model/options`: that payload is large, it fetches provider catalogues, and its
 * rows are engine internals we would be rendering. These four cover the early product — one cheap
 * native provider, one careful one, an aggregator that reaches most models, and the escape hatch.
 *
 * Every value here is copied from the pinned engine's own registry
 * (`hermes_cli/auth.py::PROVIDER_REGISTRY` and `hermes_cli/providers.py::TRANSPORT_TO_API_MODE`),
 * and `providers.test.ts` holds the shape. A wrong `base_url` or `api_mode` is not a cosmetic
 * bug: it is a first message that fails after a key has been stored.
 *
 * Why a custom entry and not `openai-api`: Hermes models OpenAI's API through its Responses
 * transport, and that is not the same conversation as an OpenAI-compatible chat endpoint. A
 * custom endpoint is the honest route for OpenAI keys, Gemini, a local model or anything else
 * until a provider gets its own verified row here.
 */

export type ApiMode = 'chat_completions' | 'anthropic_messages'

export interface ModelProvider {
  /** The engine's provider id, written to `model.provider`. */
  id: string
  label: string
  /** The env var the key is written to in the profile's `.env`. */
  keyEnv: string
  /** The endpoint, written to `model.base_url`. Empty only for the custom entry. */
  baseUrl: string
  apiMode: ApiMode
  defaultModel: string
  models: readonly string[]
  blurb: string
  custom?: boolean
}

export const PROVIDERS: readonly ModelProvider[] = [
  {
    id: 'deepseek',
    label: 'DeepSeek',
    keyEnv: 'DEEPSEEK_API_KEY',
    baseUrl: 'https://api.deepseek.com/v1',
    apiMode: 'chat_completions',
    defaultModel: 'deepseek-chat',
    models: ['deepseek-chat', 'deepseek-reasoner'],
    blurb: 'Low cost, good at everyday paperwork and short answers.'
  },
  {
    id: 'anthropic',
    label: 'Anthropic',
    keyEnv: 'ANTHROPIC_API_KEY',
    baseUrl: 'https://api.anthropic.com',
    apiMode: 'anthropic_messages',
    defaultModel: 'claude-sonnet-4-5',
    models: ['claude-sonnet-4-5', 'claude-haiku-4-5', 'claude-opus-4-1'],
    blurb: 'Claude models. Careful with long documents and written tone.'
  },
  {
    id: 'openrouter',
    label: 'OpenRouter',
    keyEnv: 'OPENROUTER_API_KEY',
    baseUrl: 'https://openrouter.ai/api/v1',
    apiMode: 'chat_completions',
    defaultModel: 'openrouter/auto',
    models: [
      'openrouter/auto',
      'openai/gpt-4o-mini',
      'google/gemini-2.5-flash',
      'anthropic/claude-sonnet-4.5'
    ],
    blurb: 'One key for many models, including OpenAI and Google.'
  },
  {
    id: 'custom',
    label: 'Custom endpoint',
    keyEnv: 'CUSTOM_API_KEY',
    baseUrl: '',
    apiMode: 'chat_completions',
    defaultModel: '',
    models: [],
    blurb: 'Any OpenAI-compatible endpoint, including a model running on this machine.',
    custom: true
  }
]

export function providerById(id: string): ModelProvider | undefined {
  return PROVIDERS.find(provider => provider.id === id)
}

export interface ModelChoice {
  provider: ModelProvider
  model: string
  keyEnv: string
  baseUrl: string
}

/**
 * The exact `model:` block the form writes. Every key is named every time, because
 * `EngineProfile.set_model` merges into the block: naming only the provider would leave the
 * previous provider's `base_url` in place and send the new key to the old endpoint.
 */
export function modelValues(choice: ModelChoice): Record<string, string> {
  const { provider, model, keyEnv, baseUrl } = choice
  return {
    provider: provider.id,
    default: model.trim(),
    base_url: (provider.custom ? baseUrl : provider.baseUrl).trim(),
    api_mode: provider.apiMode,
    key_env: keyEnv.trim()
  }
}

const ENV_NAME = /^[A-Za-z_][A-Za-z0-9_]*$/

/** The first thing wrong with a choice, in the words the form shows, or null. */
export function modelProblem(choice: ModelChoice): string | null {
  if (!choice.model.trim()) return 'Choose or type the model this provider should use.'
  if (!ENV_NAME.test(choice.keyEnv.trim())) {
    return 'The key name must be an environment-variable name, like MY_PROVIDER_API_KEY.'
  }
  if (choice.provider.custom) {
    const url = choice.baseUrl.trim()
    if (!url) return 'The endpoint needs a base URL, for example https://api.example.com/v1.'
    let parsed: URL
    try {
      parsed = new URL(url)
    } catch {
      return 'That is not a URL. It should start with https:// and end at the provider’s /v1.'
    }
    if (parsed.protocol !== 'https:' && parsed.hostname !== '127.0.0.1' && parsed.hostname !== 'localhost') {
      return 'Use https:// for a remote endpoint, or 127.0.0.1 for a model on this machine.'
    }
  }
  return null
}
