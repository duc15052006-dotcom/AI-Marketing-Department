import { useState, useEffect } from 'react';
import {
  IconSettings,
  IconAlertCircle,
  IconCheck,
  IconRotateCw,
  IconPlus,
  IconTrash,
  IconPlug,
} from './Icons.tsx';
import { apiFetch } from '../api/client.ts';

export interface ModelTarget {
  provider_id: string;
  model_id: string;
}

export interface ProviderDefinition {
  provider_id: string;
  adapter_type: string;
  display_name: string;
  base_url?: string | null;
  enabled: boolean;
  default_model: string;
  cost_policy: string;
  timeout_seconds: number;
  has_credential?: boolean;
  is_configured?: boolean;
}

/** Safe user-facing mapping of backend connection-test / mutation statuses. */
export const CONNECTION_STATUS_COPY: Record<string, string> = {
  CONNECTED: 'Connection successful.',
  AUTH_FAILED: 'Authentication failed: the API key was rejected by the provider.',
  TIMEOUT: 'The provider did not respond in time.',
  RATE_LIMIT: 'Rate limit or quota exceeded at the provider.',
  MODEL_NOT_FOUND: 'The provider rejected the model id.',
  INVALID_CONFIGURATION: 'The endpoint configuration is invalid.',
  UNAVAILABLE: 'The provider could not be reached.',
  STALE_SETTINGS_REVISION: 'Settings were changed elsewhere. Refresh and review before retrying.',
  MISSING_SETTINGS_REVISION: 'Internal contract error: mutation was sent without a settings revision.',
};

export function describeStatus(status?: string): string {
  if (!status) return '';
  return CONNECTION_STATUS_COPY[status] ?? status;
}

export interface ModelSettingsData {
  settings_revision: number;
  free_only_mode: boolean;
  global_target: ModelTarget;
  agent_overrides: Record<string, ModelTarget>;
  fallback_chain: ModelTarget[];
  providers: ProviderDefinition[];
  allowed_agents: string[];
}

export interface ConnectionTestResult {
  status: 'CONNECTED' | 'AUTH_FAILED' | 'TIMEOUT' | 'RATE_LIMIT' | 'MODEL_NOT_FOUND' | 'INVALID_CONFIGURATION' | 'UNAVAILABLE';
  latency_ms?: number;
  error?: string;
  details?: string;
  model_used?: string;
}

export function ModelSettingsView() {
  const [settings, setSettings] = useState<ModelSettingsData | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [saving, setSaving] = useState<boolean>(false);
  const [statusMessage, setStatusMessage] = useState<{ type: 'success' | 'error' | 'warning'; text: string } | null>(null);

  // Active form states
  const [editingProviderId, setEditingProviderId] = useState<string | null>(null);
  const [providerForm, setProviderForm] = useState<{
    provider_id: string;
    display_name: string;
    adapter_type: string;
    base_url: string;
    default_model: string;
    api_key: string;
    enabled: boolean;
    cost_policy: string;
    timeout_seconds: number;
  }>({
    provider_id: '',
    display_name: '',
    adapter_type: 'OPENAI_COMPATIBLE',
    base_url: '',
    default_model: '',
    api_key: '',
    enabled: true,
    cost_policy: 'FREE_TIER_ALLOWED',
    timeout_seconds: 60,
  });

  const [testingConnection, setTestingConnection] = useState<boolean>(false);
  const [testResult, setTestResult] = useState<ConnectionTestResult | null>(null);

  // Stale-revision conflict: set on HTTP 409. Blocks further saves until the
  // user deliberately refreshes and reviews authoritative Settings.
  const [staleConflict, setStaleConflict] = useState<boolean>(false);

  const fetchSettings = async () => {
    setLoading(true);
    setStatusMessage(null);
    try {
      const res = await apiFetch('/api/settings/model');
      if (!res.ok) {
        throw new Error(`Failed to load settings (status ${res.status})`);
      }
      const data: ModelSettingsData = await res.json();
      setSettings(data);
      setStaleConflict(false); // authoritative state reloaded; deliberate review done
    } catch (e: any) {
      setStatusMessage({ type: 'error', text: e.message || 'Failed to load model settings.' });
    } finally {
      setLoading(false);
    }
  };

  /** Shared mutation error handling: never fake success on 409/400. */
  const handleMutationError = async (res: Response): Promise<Error> => {
    const err = await res.json().catch(() => ({}) as any);
    if (res.status === 409 || err?.error === 'STALE_SETTINGS_REVISION') {
      setStaleConflict(true);
      return new Error(
        'Settings were changed elsewhere (stale revision). ' +
        'Refresh to load the authoritative configuration, review it, then retry deliberately.',
      );
    }
    if (err?.error === 'MISSING_SETTINGS_REVISION') {
      return new Error(
        'Internal error: this save was sent without a settings revision and was rejected. No changes were applied.',
      );
    }
    return new Error(err?.message || `Save failed with status ${res.status}`);
  };

  /** Adopt the authoritative revision returned by a successful mutation. */
  const adoptRevision = (revision?: number) => {
    if (typeof revision === 'number' && settings) {
      setSettings({ ...settings, settings_revision: revision });
    }
  };

  useEffect(() => {
    fetchSettings();
  }, []);

  const handleGlobalTargetChange = (field: 'provider_id' | 'model_id', value: string) => {
    if (!settings) return;
    setSettings({
      ...settings,
      global_target: {
        ...settings.global_target,
        [field]: value,
      },
    });
  };

  const handleAgentOverrideToggle = (agent: string, enableCustom: boolean) => {
    if (!settings) return;
    const newOverrides = { ...settings.agent_overrides };
    if (enableCustom) {
      newOverrides[agent] = {
        provider_id: settings.global_target.provider_id,
        model_id: settings.global_target.model_id,
      };
    } else {
      delete newOverrides[agent];
    }
    setSettings({ ...settings, agent_overrides: newOverrides });
  };

  const handleAgentOverrideChange = (agent: string, field: 'provider_id' | 'model_id', value: string) => {
    if (!settings || !settings.agent_overrides[agent]) return;
    setSettings({
      ...settings,
      agent_overrides: {
        ...settings.agent_overrides,
        [agent]: {
          ...settings.agent_overrides[agent],
          [field]: value,
        },
      },
    });
  };

  const handleAddFallback = () => {
    if (!settings) return;
    const usable = settings.providers.filter((p) => p.enabled);
    const defaultProv = usable[0]?.provider_id || settings.providers[0]?.provider_id || 'gemini';
    const defaultMod = usable[0]?.default_model || settings.providers[0]?.default_model || 'gemini-flash-latest';
    // UX duplicate guard (backend remains authoritative).
    if (settings.fallback_chain.some((fb) => fb.provider_id === defaultProv && fb.model_id === defaultMod)) {
      setStatusMessage({ type: 'warning', text: 'That fallback target already exists in the chain.' });
      return;
    }
    setSettings({
      ...settings,
      fallback_chain: [...settings.fallback_chain, { provider_id: defaultProv, model_id: defaultMod }],
    });
  };

  const handleMoveFallback = (index: number, direction: -1 | 1) => {
    if (!settings) return;
    const target = index + direction;
    if (target < 0 || target >= settings.fallback_chain.length) return;
    const chain = [...settings.fallback_chain];
    [chain[index], chain[target]] = [chain[target], chain[index]];
    setSettings({ ...settings, fallback_chain: chain });
  };

  const handleRemoveFallback = (index: number) => {
    if (!settings) return;
    const newChain = settings.fallback_chain.filter((_, i) => i !== index);
    setSettings({ ...settings, fallback_chain: newChain });
  };

  const handleFallbackChange = (index: number, field: 'provider_id' | 'model_id', value: string) => {
    if (!settings) return;
    const newChain = [...settings.fallback_chain];
    newChain[index] = { ...newChain[index], [field]: value };
    setSettings({ ...settings, fallback_chain: newChain });
  };

  const handleStartAddProvider = () => {
    setEditingProviderId('__NEW__');
    setProviderForm({
      provider_id: '',
      display_name: '',
      adapter_type: 'OPENAI_COMPATIBLE',
      base_url: 'https://api.openai.com/v1',
      default_model: '',
      api_key: '',
      enabled: true,
      cost_policy: 'FREE_TIER_ALLOWED',
      timeout_seconds: 60,
    });
    setTestResult(null);
  };

  const handleStartEditProvider = (p: ProviderDefinition) => {
    setEditingProviderId(p.provider_id);
    setProviderForm({
      provider_id: p.provider_id,
      display_name: p.display_name,
      adapter_type: p.adapter_type,
      base_url: p.base_url || '',
      default_model: p.default_model,
      api_key: '', // Never preload secret
      enabled: p.enabled,
      cost_policy: p.cost_policy || 'FREE_TIER_ALLOWED',
      timeout_seconds: p.timeout_seconds || 60,
    });
    setTestResult(null);
  };

  /** Per-provider enable/disable/delete: revision-mandatory mutations that
   * adopt the authoritative revision returned by the backend. */
  const handleProviderMutation = async (pid: string, action: 'enable' | 'disable' | 'delete') => {
    if (!settings) return;
    if (action === 'delete' && !window.confirm(`Delete provider '${pid}'? This cannot be undone.`)) {
      return;
    }
    setSaving(true);
    setStatusMessage(null);
    try {
      const res = await apiFetch(`/api/settings/providers/${encodeURIComponent(pid)}/${action}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ expected_revision: settings.settings_revision }),
      });
      if (!res.ok) {
        throw await handleMutationError(res);
      }
      const data = await res.json();
      adoptRevision(data?.settings_revision);
      setStatusMessage({ type: 'success', text: `Provider '${pid}' ${action}d. Applies to new runs.` });
      await fetchSettings();
    } catch (e: any) {
      setStatusMessage({ type: 'error', text: e.message || `Failed to ${action} provider.` });
    } finally {
      setSaving(false);
    }
  };

  const handleCancelProviderEdit = () => {
    // Clear any transient key material from form state.
    setProviderForm((prev) => ({ ...prev, api_key: '' }));
    setEditingProviderId(null);
    setTestResult(null);
  };

  const handleTestConnection = async () => {
    setTestingConnection(true);
    setTestResult(null);
    try {
      const payload: any = {
        provider_id: providerForm.provider_id,
        adapter_type: providerForm.adapter_type,
        base_url: providerForm.base_url || undefined,
        model_id: providerForm.default_model,
        api_key: providerForm.api_key || undefined,
      };
      const res = await apiFetch('/api/settings/models/test', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const result: ConnectionTestResult = await res.json();
      setTestResult(result);
    } catch (e: any) {
      setTestResult({
        status: 'UNAVAILABLE',
        error: e.message || 'Connection test failed to execute.',
      });
    } finally {
      setTestingConnection(false);
    }
  };

  const handleSaveProvider = async () => {
    if (!settings) return;
    if (!providerForm.provider_id.trim()) {
      setStatusMessage({ type: 'error', text: 'Provider ID is required.' });
      return;
    }
    if (!providerForm.default_model.trim()) {
      setStatusMessage({ type: 'error', text: 'Default Model ID is required.' });
      return;
    }

    setSaving(true);
    setStatusMessage(null);
    try {
      const payload: any = {
        expected_revision: settings.settings_revision,
        provider_id: providerForm.provider_id.trim().toLowerCase(),
        display_name: providerForm.display_name.trim() || providerForm.provider_id.trim(),
        adapter_type: providerForm.adapter_type,
        base_url: providerForm.base_url.trim() || null,
        default_model: providerForm.default_model.trim(),
        enabled: providerForm.enabled,
        cost_policy: providerForm.cost_policy,
        timeout_seconds: Number(providerForm.timeout_seconds) || 60,
      };
      if (providerForm.api_key.trim()) {
        payload.api_key = providerForm.api_key.trim();
      }

      const res = await apiFetch('/api/settings/providers/upsert', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });

      if (!res.ok) {
        throw await handleMutationError(res);
      }
      const saved = await res.json();

      // Adopt authoritative revision returned by the backend; clear transient
      // key material from form state for this request lifecycle.
      adoptRevision(saved?.settings_revision);
      setProviderForm((prev) => ({ ...prev, api_key: '' }));
      setStatusMessage({ type: 'success', text: `Provider '${payload.display_name}' saved securely. Applies to new runs.` });
      setEditingProviderId(null);
      await fetchSettings();
    } catch (e: any) {
      setStatusMessage({ type: 'error', text: e.message || 'Failed to save provider.' });
    } finally {
      setSaving(false);
    }
  };

  const handleSaveGlobalAndPolicies = async () => {
    if (!settings) return;
    setSaving(true);
    setStatusMessage(null);
    try {
      const payload = {
        expected_revision: settings.settings_revision,
        free_only_mode: settings.free_only_mode,
        global_target: settings.global_target,
        agent_overrides: settings.agent_overrides,
        fallback_chain: settings.fallback_chain,
      };

      const res = await apiFetch('/api/settings/model', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });

      if (!res.ok) {
        throw await handleMutationError(res);
      }

      const updated: ModelSettingsData = await res.json();
      setSettings(updated);
      setStatusMessage({ type: 'success', text: `Model settings (Rev ${updated.settings_revision}) saved. Applies to new runs.` });
    } catch (e: any) {
      setStatusMessage({ type: 'error', text: e.message || 'Failed to update settings.' });
    } finally {
      setSaving(false);
    }
  };

  if (loading && !settings) {
    return (
      <div style={{ padding: '40px', color: '#A0A0A0', display: 'flex', alignItems: 'center', gap: '10px' }}>
        <IconRotateCw size={16} />
        <span>Loading model settings...</span>
      </div>
    );
  }

  if (!settings) {
    return (
      <div style={{ padding: '40px', color: '#EF4444' }}>
        Failed to load model settings. <button onClick={fetchSettings} style={{ marginLeft: '10px', padding: '4px 10px' }}>Retry</button>
      </div>
    );
  }

  const agentList = settings.allowed_agents || ['CMO', 'INTELLIGENCE', 'STRATEGIST', 'CREATIVE', 'PERFORMANCE'];

  return (
    <div style={{ padding: '30px 40px', maxWidth: '960px', margin: '0 auto', width: '100%', color: '#F2F2F2' }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '24px', borderBottom: '1px solid #1C1C1C', paddingBottom: '16px' }}>
        <div>
          <h1 style={{ fontSize: '20px', fontWeight: 700, margin: '0 0 4px 0', display: 'flex', alignItems: 'center', gap: '8px' }}>
            <IconSettings size={20} />
            <span>AI Model & Provider Settings</span>
          </h1>
          <p style={{ fontSize: '12px', color: '#888888', margin: 0 }}>
            Configure default and per-agent AI providers, models, fallback routes, and custom OpenAI-compatible endpoints.
          </p>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          <span style={{ fontSize: '11px', color: '#666666', background: '#121212', padding: '4px 8px', borderRadius: '4px', border: '1px solid #222222' }}>
            Rev {settings.settings_revision}
          </span>
          <button
            onClick={fetchSettings}
            disabled={loading || saving}
            style={{
              background: 'transparent',
              border: '1px solid #282828',
              borderRadius: '6px',
              color: '#A0A0A0',
              padding: '6px 12px',
              fontSize: '12px',
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
            }}
          >
            <IconRotateCw size={13} />
            <span>Refresh</span>
          </button>
          <button
            onClick={handleSaveGlobalAndPolicies}
            disabled={saving || staleConflict}
            style={{
              background: staleConflict ? '#555555' : '#ECECEC',
              border: 'none',
              borderRadius: '6px',
              color: '#050505',
              fontWeight: 600,
              padding: '6px 16px',
              fontSize: '12px',
              cursor: staleConflict ? 'not-allowed' : 'pointer',
            }}
          >
            {saving ? 'Saving...' : 'Save Settings'}
          </button>
        </div>
      </div>

      {/* Stale revision conflict banner: requires deliberate refresh/review */}
      {staleConflict && (
        <div
          style={{
            marginBottom: '20px',
            padding: '12px 16px',
            borderRadius: '8px',
            background: '#1E1805',
            border: '1px solid #854D0E',
            color: '#FACC15',
            fontSize: '13px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: '12px',
          }}
        >
          <span>
            Settings were changed in another session. Saving is blocked so your stale copy cannot overwrite the newer
            configuration. Refresh to load the authoritative settings, review them, then retry deliberately.
          </span>
          <button
            onClick={fetchSettings}
            style={{ background: '#854D0E', border: 'none', borderRadius: '6px', color: '#FFFFFF', padding: '6px 12px', cursor: 'pointer', whiteSpace: 'nowrap' }}
          >
            Refresh &amp; Review
          </button>
        </div>
      )}

      {/* Alert banner */}
      {statusMessage && (
        <div
          style={{
            marginBottom: '20px',
            padding: '12px 16px',
            borderRadius: '8px',
            background: statusMessage.type === 'success' ? '#061A0C' : statusMessage.type === 'warning' ? '#1E1805' : '#220808',
            border: `1px solid ${statusMessage.type === 'success' ? '#166534' : statusMessage.type === 'warning' ? '#854D0E' : '#991B1B'}`,
            color: statusMessage.type === 'success' ? '#4ADE80' : statusMessage.type === 'warning' ? '#FACC15' : '#F87171',
            fontSize: '13px',
            display: 'flex',
            alignItems: 'center',
            gap: '8px',
          }}
        >
          {statusMessage.type === 'success' ? <IconCheck size={16} /> : <IconAlertCircle size={16} />}
          <span>{statusMessage.text}</span>
        </div>
      )}

      {/* SECTION 1: GLOBAL MODEL CONFIGURATION */}
      <div style={{ background: '#0D0D0D', border: '1px solid #1A1A1A', borderRadius: '10px', padding: '20px', marginBottom: '24px' }}>
        <h2 style={{ fontSize: '15px', fontWeight: 600, margin: '0 0 12px 0', color: '#F2F2F2' }}>
          Global Model Authority
        </h2>
        <p style={{ fontSize: '12px', color: '#888888', margin: '0 0 16px 0' }}>
          Default model target used by all 5 agents (CMO, Intelligence, Strategist, Creative, Performance) unless individually overridden.
        </p>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px' }}>
          <div>
            <label style={{ display: 'block', fontSize: '12px', color: '#AAAAAA', marginBottom: '6px' }}>Global Provider</label>
            <select
              value={settings.global_target.provider_id}
              onChange={(e) => handleGlobalTargetChange('provider_id', e.target.value)}
              style={{
                width: '100%',
                background: '#141414',
                border: '1px solid #282828',
                borderRadius: '6px',
                color: '#F2F2F2',
                padding: '8px 12px',
                fontSize: '13px',
                outline: 'none',
              }}
            >
              {settings.providers.map((p) => (
                <option key={p.provider_id} value={p.provider_id}>
                  {p.display_name} ({p.provider_id}) {!p.enabled ? '[Disabled]' : ''} {!p.has_credential ? '[No Key]' : ''}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label style={{ display: 'block', fontSize: '12px', color: '#AAAAAA', marginBottom: '6px' }}>Global Model Identifier</label>
            <input
              type="text"
              value={settings.global_target.model_id}
              onChange={(e) => handleGlobalTargetChange('model_id', e.target.value)}
              placeholder="e.g. gemini-flash-latest or gpt-4o-mini"
              style={{
                width: '100%',
                background: '#141414',
                border: '1px solid #282828',
                borderRadius: '6px',
                color: '#F2F2F2',
                padding: '8px 12px',
                fontSize: '13px',
                outline: 'none',
                boxSizing: 'border-box',
              }}
            />
          </div>
        </div>

        {/* Free Only Mode Toggle */}
        <div style={{ marginTop: '16px', paddingTop: '14px', borderTop: '1px solid #181818', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <div>
            <div style={{ fontSize: '13px', fontWeight: 500, color: '#ECECEC' }}>Strict Free-Only Mode (FREE_ONLY_MODE)</div>
            <div style={{ fontSize: '11px', color: '#777777', maxWidth: '640px' }}>
              When enabled, targets with PAID or UNKNOWN cost policy are blocked from execution unless explicitly
              allowed. Provider billing policies can change over time; free-only mode enforces the declared cost
              classification, it is not a billing guarantee.
            </div>
          </div>
          <input
            type="checkbox"
            checked={settings.free_only_mode}
            onChange={(e) => setSettings({ ...settings, free_only_mode: e.target.checked })}
            style={{ width: '16px', height: '16px', cursor: 'pointer' }}
          />
        </div>
      </div>

      {/* SECTION 2: FIVE LOGICAL AGENT OVERRIDES */}
      <div style={{ background: '#0D0D0D', border: '1px solid #1A1A1A', borderRadius: '10px', padding: '20px', marginBottom: '24px' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '12px' }}>
          <div>
            <h2 style={{ fontSize: '15px', fontWeight: 600, margin: '0 0 4px 0', color: '#F2F2F2' }}>
              Per-Agent Routing Overrides
            </h2>
            <p style={{ fontSize: '12px', color: '#888888', margin: 0 }}>
              Optionally route individual agents to specialized models. (Note: Final CMO automatically uses CMO settings).
            </p>
          </div>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
          {agentList.map((agent) => {
            const hasCustom = Boolean(settings.agent_overrides[agent]);
            const target = settings.agent_overrides[agent] || settings.global_target;

            return (
              <div
                key={agent}
                style={{
                  background: '#121212',
                  border: '1px solid #202020',
                  borderRadius: '8px',
                  padding: '12px 16px',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  gap: '16px',
                }}
              >
                <div style={{ minWidth: '130px' }}>
                  <div style={{ fontSize: '13px', fontWeight: 600, color: '#ECECEC' }}>{agent}</div>
                  <div style={{ fontSize: '11px', color: hasCustom ? '#4ADE80' : '#777777' }}>
                    {hasCustom ? 'Custom Override' : 'Inheriting Global'}
                  </div>
                </div>

                <div style={{ display: 'flex', alignItems: 'center', gap: '10px', flex: 1 }}>
                  {hasCustom ? (
                    <>
                      <select
                        value={target.provider_id}
                        onChange={(e) => handleAgentOverrideChange(agent, 'provider_id', e.target.value)}
                        style={{
                          background: '#181818',
                          border: '1px solid #303030',
                          borderRadius: '6px',
                          color: '#F2F2F2',
                          padding: '6px 10px',
                          fontSize: '12px',
                        }}
                      >
                        {settings.providers.map((p) => (
                          <option key={p.provider_id} value={p.provider_id}>
                            {p.display_name}
                          </option>
                        ))}
                      </select>
                      <input
                        type="text"
                        value={target.model_id}
                        onChange={(e) => handleAgentOverrideChange(agent, 'model_id', e.target.value)}
                        placeholder="Model ID"
                        style={{
                          flex: 1,
                          background: '#181818',
                          border: '1px solid #303030',
                          borderRadius: '6px',
                          color: '#F2F2F2',
                          padding: '6px 10px',
                          fontSize: '12px',
                        }}
                      />
                    </>
                  ) : (
                    <div style={{ fontSize: '12px', color: '#666666' }}>
                      Using Global Target: {settings.global_target.provider_id} :: {settings.global_target.model_id}
                    </div>
                  )}
                </div>

                <button
                  type="button"
                  onClick={() => handleAgentOverrideToggle(agent, !hasCustom)}
                  style={{
                    background: 'transparent',
                    border: '1px solid #2C2C2C',
                    borderRadius: '6px',
                    color: hasCustom ? '#F87171' : '#A0A0A0',
                    fontSize: '11px',
                    padding: '5px 10px',
                    cursor: 'pointer',
                  }}
                >
                  {hasCustom ? 'Reset to Global' : 'Customize'}
                </button>
              </div>
            );
          })}
        </div>
      </div>

      {/* SECTION 3: DETERMINISTIC FALLBACK CHAIN */}
      <div style={{ background: '#0D0D0D', border: '1px solid #1A1A1A', borderRadius: '10px', padding: '20px', marginBottom: '24px' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '12px' }}>
          <div>
            <h2 style={{ fontSize: '15px', fontWeight: 600, margin: '0 0 4px 0', color: '#F2F2F2' }}>
              Deterministic Fallback Chain
            </h2>
            <p style={{ fontSize: '12px', color: '#888888', margin: 0 }}>
              Ordered sequence of backup targets tried when a primary model encounters rate limits or network failures.
            </p>
          </div>
          <button
            onClick={handleAddFallback}
            style={{
              background: '#181818',
              border: '1px solid #2A2A2A',
              borderRadius: '6px',
              color: '#ECECEC',
              fontSize: '12px',
              padding: '5px 10px',
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
            }}
          >
            <IconPlus size={13} />
            <span>Add Fallback</span>
          </button>
        </div>

        {settings.fallback_chain.length === 0 ? (
          <div style={{ fontSize: '12px', color: '#666666', padding: '12px 0' }}>
            No fallback targets configured. Calls will fail immediately if the primary target fails.
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
            {settings.fallback_chain.map((fb, idx) => (
              <div
                key={idx}
                style={{
                  background: '#121212',
                  border: '1px solid #202020',
                  borderRadius: '6px',
                  padding: '10px 14px',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '12px',
                }}
              >
                <span style={{ fontSize: '12px', color: '#888888', width: '24px' }}>#{idx + 1}</span>
                <select
                  value={fb.provider_id}
                  onChange={(e) => handleFallbackChange(idx, 'provider_id', e.target.value)}
                  style={{
                    background: '#181818',
                    border: '1px solid #303030',
                    borderRadius: '6px',
                    color: '#F2F2F2',
                    padding: '6px 10px',
                    fontSize: '12px',
                  }}
                >
                  {settings.providers.map((p) => (
                    <option key={p.provider_id} value={p.provider_id}>
                      {p.display_name}{!p.enabled ? ' [Disabled — applies to new runs only]' : ''}
                    </option>
                  ))}
                </select>
                <input
                  type="text"
                  value={fb.model_id}
                  onChange={(e) => handleFallbackChange(idx, 'model_id', e.target.value)}
                  placeholder="Fallback Model ID"
                  style={{
                    flex: 1,
                    background: '#181818',
                    border: '1px solid #303030',
                    borderRadius: '6px',
                    color: '#F2F2F2',
                    padding: '6px 10px',
                    fontSize: '12px',
                  }}
                />
                <button
                  onClick={() => handleMoveFallback(idx, -1)}
                  disabled={idx === 0}
                  title="Move earlier (tried sooner)"
                  style={{ background: 'transparent', border: '1px solid #2A2A2A', borderRadius: '4px',
                           color: idx === 0 ? '#444444' : '#CCCCCC', cursor: idx === 0 ? 'default' : 'pointer',
                           padding: '3px 8px', fontSize: '11px' }}
                >
                  ↑
                </button>
                <button
                  onClick={() => handleMoveFallback(idx, 1)}
                  disabled={idx === settings.fallback_chain.length - 1}
                  title="Move later (tried after)"
                  style={{ background: 'transparent', border: '1px solid #2A2A2A', borderRadius: '4px',
                           color: idx === settings.fallback_chain.length - 1 ? '#444444' : '#CCCCCC',
                           cursor: idx === settings.fallback_chain.length - 1 ? 'default' : 'pointer',
                           padding: '3px 8px', fontSize: '11px' }}
                >
                  ↓
                </button>
                <button
                  onClick={() => handleRemoveFallback(idx)}
                  title="Remove Fallback"
                  style={{
                    background: 'transparent',
                    border: 'none',
                    color: '#EF4444',
                    cursor: 'pointer',
                    padding: '4px',
                  }}
                >
                  <IconTrash size={14} />
                </button>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* SECTION 4: CONFIGURED PROVIDERS & CUSTOM OPENAI PROVIDERS */}
      <div style={{ background: '#0D0D0D', border: '1px solid #1A1A1A', borderRadius: '10px', padding: '20px' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '16px' }}>
          <div>
            <h2 style={{ fontSize: '15px', fontWeight: 600, margin: '0 0 4px 0', color: '#F2F2F2' }}>
              Providers & Custom Endpoints
            </h2>
            <p style={{ fontSize: '12px', color: '#888888', margin: 0 }}>
              Manage API keys, endpoints, and enabled status. Plaintext API keys are encrypted locally and never exposed.
            </p>
          </div>
          <button
            onClick={handleStartAddProvider}
            style={{
              background: '#181818',
              border: '1px solid #2A2A2A',
              borderRadius: '6px',
              color: '#ECECEC',
              fontSize: '12px',
              padding: '6px 12px',
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
            }}
          >
            <IconPlus size={13} />
            <span>Add Custom Provider</span>
          </button>
        </div>

        {/* Provider Editor Card */}
        {editingProviderId && (
          <div style={{ background: '#121212', border: '1px solid #2C2C2C', borderRadius: '8px', padding: '18px', marginBottom: '20px' }}>
            <h3 style={{ fontSize: '14px', fontWeight: 600, margin: '0 0 14px 0', color: '#ECECEC' }}>
              {editingProviderId === '__NEW__' ? 'Add New AI Provider' : `Edit Provider: ${providerForm.display_name}`}
            </h3>

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '14px', marginBottom: '14px' }}>
              <div>
                <label style={{ display: 'block', fontSize: '11px', color: '#888888', marginBottom: '4px' }}>Provider ID (Machine Key)</label>
                <input
                  type="text"
                  disabled={editingProviderId !== '__NEW__'}
                  value={providerForm.provider_id}
                  onChange={(e) => setProviderForm({ ...providerForm, provider_id: e.target.value })}
                  placeholder="e.g. custom_openai or vllm_local"
                  style={{ width: '100%', background: '#181818', border: '1px solid #303030', borderRadius: '6px', color: '#F2F2F2', padding: '7px 10px', fontSize: '12px', boxSizing: 'border-box' }}
                />
              </div>
              <div>
                <label style={{ display: 'block', fontSize: '11px', color: '#888888', marginBottom: '4px' }}>Display Name</label>
                <input
                  type="text"
                  value={providerForm.display_name}
                  onChange={(e) => setProviderForm({ ...providerForm, display_name: e.target.value })}
                  placeholder="e.g. Local vLLM Server"
                  style={{ width: '100%', background: '#181818', border: '1px solid #303030', borderRadius: '6px', color: '#F2F2F2', padding: '7px 10px', fontSize: '12px', boxSizing: 'border-box' }}
                />
              </div>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '14px', marginBottom: '14px' }}>
              <div>
                <label style={{ display: 'block', fontSize: '11px', color: '#888888', marginBottom: '4px' }}>Provider Adapter Type</label>
                <select
                  value={providerForm.adapter_type}
                  onChange={(e) => setProviderForm({ ...providerForm, adapter_type: e.target.value })}
                  style={{ width: '100%', background: '#181818', border: '1px solid #303030', borderRadius: '6px', color: '#F2F2F2', padding: '7px 10px', fontSize: '12px' }}
                >
                  <option value="OPENAI_COMPATIBLE">OpenAI Compatible (Cloud, Local Ollama, vLLM, LiteLLM)</option>
                  <option value="GEMINI_NATIVE">Google Gemini Native</option>
                </select>
              </div>
              <div>
                <label style={{ display: 'block', fontSize: '11px', color: '#888888', marginBottom: '4px' }}>Base URL (HTTPS or loopback HTTP)</label>
                <input
                  type="text"
                  value={providerForm.base_url}
                  onChange={(e) => setProviderForm({ ...providerForm, base_url: e.target.value })}
                  placeholder="https://api.openai.com/v1 or http://127.0.0.1:8000/v1"
                  style={{ width: '100%', background: '#181818', border: '1px solid #303030', borderRadius: '6px', color: '#F2F2F2', padding: '7px 10px', fontSize: '12px', boxSizing: 'border-box' }}
                />
              </div>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '14px', marginBottom: '14px' }}>
              <div>
                <label style={{ display: 'block', fontSize: '11px', color: '#888888', marginBottom: '4px' }}>Default Model ID</label>
                <input
                  type="text"
                  value={providerForm.default_model}
                  onChange={(e) => setProviderForm({ ...providerForm, default_model: e.target.value })}
                  placeholder="e.g. gpt-4o-mini or mistral-7b"
                  style={{ width: '100%', background: '#181818', border: '1px solid #303030', borderRadius: '6px', color: '#F2F2F2', padding: '7px 10px', fontSize: '12px', boxSizing: 'border-box' }}
                />
              </div>
              <div>
                <label style={{ display: 'block', fontSize: '11px', color: '#888888', marginBottom: '4px' }}>
                  API Key {editingProviderId !== '__NEW__' && <span style={{ color: '#666666' }}>(Leave blank to keep existing)</span>}
                </label>
                <input
                  type="password"
                  value={providerForm.api_key}
                  onChange={(e) => setProviderForm({ ...providerForm, api_key: e.target.value })}
                  placeholder={editingProviderId !== '__NEW__' ? '•••••••••••• Stored securely' : 'Enter API Key (e.g. sk-...)'}
                  style={{ width: '100%', background: '#181818', border: '1px solid #303030', borderRadius: '6px', color: '#F2F2F2', padding: '7px 10px', fontSize: '12px', boxSizing: 'border-box' }}
                />
              </div>
            </div>

            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginTop: '16px', paddingTop: '12px', borderTop: '1px solid #202020' }}>
              <label style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '12px', color: '#ECECEC', cursor: 'pointer' }}>
                <input
                  type="checkbox"
                  checked={providerForm.enabled}
                  onChange={(e) => setProviderForm({ ...providerForm, enabled: e.target.checked })}
                />
                <span>Provider Enabled (Applies to new runs)</span>
              </label>

              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <button
                  type="button"
                  onClick={handleTestConnection}
                  disabled={testingConnection}
                  title="Connectivity check only — uses the values typed here transiently and never saves the provider or key."
                  style={{
                    background: '#1A1A1A',
                    border: '1px solid #333333',
                    borderRadius: '6px',
                    color: '#ECECEC',
                    fontSize: '12px',
                    padding: '6px 14px',
                    cursor: 'pointer',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '6px',
                  }}
                >
                  <IconPlug size={13} />
                  <span>{testingConnection ? 'Testing...' : 'Test Connection'}</span>
                </button>
                <button
                  type="button"
                  onClick={handleCancelProviderEdit}
                  style={{
                    background: 'transparent',
                    border: '1px solid #303030',
                    borderRadius: '6px',
                    color: '#A0A0A0',
                    fontSize: '12px',
                    padding: '6px 12px',
                    cursor: 'pointer',
                  }}
                >
                  Cancel
                </button>
                <button
                  type="button"
                  onClick={handleSaveProvider}
                  disabled={saving}
                  style={{
                    background: '#ECECEC',
                    border: 'none',
                    borderRadius: '6px',
                    color: '#050505',
                    fontWeight: 600,
                    fontSize: '12px',
                    padding: '6px 16px',
                    cursor: 'pointer',
                  }}
                >
                  {saving ? 'Saving...' : 'Save Provider'}
                </button>
              </div>
            </div>

            {/* Test Connection Output */}
            {testResult && (
              <div
                style={{
                  marginTop: '12px',
                  padding: '10px 14px',
                  borderRadius: '6px',
                  fontSize: '12px',
                  background: testResult.status === 'CONNECTED' ? '#072010' : '#220808',
                  border: `1px solid ${testResult.status === 'CONNECTED' ? '#166534' : '#991B1B'}`,
                  color: testResult.status === 'CONNECTED' ? '#4ADE80' : '#F87171',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  {testResult.status === 'CONNECTED' ? <IconCheck size={14} /> : <IconAlertCircle size={14} />}
                  <span>
                    Status: <strong>{testResult.status}</strong>
                    {' — '}
                    {describeStatus(testResult.status)}
                    {testResult.error ? ` (${testResult.error})` : ''}
                  </span>
                </div>
                {testResult.latency_ms !== undefined && (
                  <span style={{ fontSize: '11px', color: '#888888' }}>{Math.round(testResult.latency_ms)}ms</span>
                )}
              </div>
            )}
          </div>
        )}

        {/* Provider List Table */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
          {settings.providers.map((p) => (
            <div
              key={p.provider_id}
              style={{
                background: '#121212',
                border: '1px solid #1E1E1E',
                borderRadius: '8px',
                padding: '12px 16px',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
              }}
            >
              <div>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '2px' }}>
                  <span style={{ fontSize: '13px', fontWeight: 600, color: '#ECECEC' }}>{p.display_name}</span>
                  <span style={{ fontSize: '11px', color: '#666666' }}>({p.provider_id})</span>
                  <span
                    style={{
                      fontSize: '10px',
                      padding: '2px 6px',
                      borderRadius: '4px',
                      background: p.enabled ? '#072412' : '#261212',
                      color: p.enabled ? '#4ADE80' : '#F87171',
                      border: `1px solid ${p.enabled ? '#14532D' : '#7F1D1D'}`,
                    }}
                  >
                    {p.enabled ? 'Enabled' : 'Disabled'}
                  </span>
                  <span
                    style={{
                      fontSize: '10px',
                      padding: '2px 6px',
                      borderRadius: '4px',
                      background: p.has_credential ? '#0C1B2A' : '#2B1A0A',
                      color: p.has_credential ? '#60A5FA' : '#FBBF24',
                    }}
                  >
                    {p.has_credential ? 'Key Configured' : 'Missing Key'}
                  </span>
                </div>
                <div style={{ fontSize: '11px', color: '#777777' }}>
                  Model: <code>{p.default_model}</code> {p.base_url ? `| URL: ${p.base_url}` : ''} | Cost: {p.cost_policy}
                </div>
              </div>

              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <button
                  type="button"
                  onClick={() => handleProviderMutation(p.provider_id, p.enabled ? 'disable' : 'enable')}
                  disabled={saving || staleConflict}
                  title="Ordinary settings change: applies to new runs only. Does not stop an already-running execution."
                  style={{
                    background: '#181818',
                    border: '1px solid #2A2A2A',
                    borderRadius: '6px',
                    color: '#CCCCCC',
                    fontSize: '11px',
                    padding: '4px 10px',
                    cursor: saving || staleConflict ? 'not-allowed' : 'pointer',
                  }}
                >
                  {p.enabled ? 'Disable' : 'Enable'}
                </button>
                <button
                  type="button"
                  onClick={() => handleProviderMutation(p.provider_id, 'delete')}
                  disabled={saving || staleConflict}
                  title="Delete this provider (blocked while referenced by routing or an active run's pinned credentials)"
                  style={{
                    background: 'transparent',
                    border: '1px solid #3A1A1A',
                    borderRadius: '6px',
                    color: '#F87171',
                    fontSize: '11px',
                    padding: '4px 10px',
                    cursor: saving || staleConflict ? 'not-allowed' : 'pointer',
                  }}
                >
                  Delete
                </button>
                <button
                  type="button"
                  onClick={() => handleStartEditProvider(p)}
                  style={{
                    background: '#181818',
                    border: '1px solid #2A2A2A',
                    borderRadius: '6px',
                    color: '#CCCCCC',
                    fontSize: '11px',
                    padding: '4px 10px',
                    cursor: 'pointer',
                  }}
                >
                  Configure
                </button>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
