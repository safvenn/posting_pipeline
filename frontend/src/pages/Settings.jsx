import React, { useState, useEffect } from 'react'
import { Settings2, Sparkles, ShieldOff, ShieldCheck, Save, RefreshCw, Info } from 'lucide-react'
import { useSettingsQuery, useUpdateSettings } from '../hooks/useSettings'

// ─── Toggle Switch Component ────────────────────────────────────────────────

function ToggleSwitch({ id, checked, onChange, disabled }) {
  return (
    <button
      id={id}
      role="switch"
      aria-checked={checked}
      onClick={() => !disabled && onChange(!checked)}
      disabled={disabled}
      style={{
        position: 'relative',
        display: 'inline-flex',
        alignItems: 'center',
        width: 52,
        height: 28,
        borderRadius: 14,
        border: 'none',
        cursor: disabled ? 'not-allowed' : 'pointer',
        padding: 0,
        backgroundColor: checked ? 'var(--accent-primary)' : 'var(--border-default, #334155)',
        transition: 'background-color 0.25s ease',
        boxShadow: checked
          ? '0 0 0 3px rgba(99,179,237,0.18), inset 0 1px 3px rgba(0,0,0,0.2)'
          : 'inset 0 1px 3px rgba(0,0,0,0.3)',
        outline: 'none',
        opacity: disabled ? 0.55 : 1,
        flexShrink: 0,
      }}
    >
      <span
        style={{
          position: 'absolute',
          left: checked ? 26 : 3,
          width: 22,
          height: 22,
          borderRadius: '50%',
          backgroundColor: '#fff',
          boxShadow: '0 1px 4px rgba(0,0,0,0.28)',
          transition: 'left 0.22s cubic-bezier(0.34,1.56,0.64,1)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
        }}
      />
    </button>
  )
}

// ─── Setting Row Component ──────────────────────────────────────────────────

function SettingRow({ icon: Icon, iconColor, title, description, warning, children }) {
  return (
    <div style={{
      display: 'flex',
      alignItems: 'flex-start',
      gap: 16,
      padding: '20px 24px',
      borderBottom: '1px solid var(--border-subtle)',
    }}>
      {/* Icon */}
      <div style={{
        width: 40,
        height: 40,
        borderRadius: 10,
        backgroundColor: 'var(--bg-elevated)',
        border: '1px solid var(--border-subtle)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        flexShrink: 0,
        marginTop: 2,
      }}>
        <Icon size={18} color={iconColor || 'var(--accent-primary)'} />
      </div>

      {/* Text */}
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{
          fontSize: 14,
          fontWeight: 600,
          color: 'var(--text-primary)',
          marginBottom: 4,
          letterSpacing: '-0.01em',
        }}>
          {title}
        </div>
        <div style={{
          fontSize: 12.5,
          color: 'var(--text-secondary)',
          lineHeight: 1.6,
          maxWidth: 520,
        }}>
          {description}
        </div>
        {warning && (
          <div style={{
            display: 'flex',
            alignItems: 'flex-start',
            gap: 6,
            marginTop: 8,
            padding: '8px 12px',
            borderRadius: 7,
            backgroundColor: 'var(--warning-subtle, rgba(245,158,11,0.1))',
            border: '1px solid var(--warning-border, rgba(245,158,11,0.25))',
          }}>
            <Info size={13} color="var(--warning, #f59e0b)" style={{ flexShrink: 0, marginTop: 1 }} />
            <span style={{ fontSize: 12, color: 'var(--warning, #f59e0b)', lineHeight: 1.5 }}>
              {warning}
            </span>
          </div>
        )}
      </div>

      {/* Control */}
      <div style={{ flexShrink: 0, display: 'flex', alignItems: 'center', marginTop: 8 }}>
        {children}
      </div>
    </div>
  )
}

// ─── Main Settings Page ─────────────────────────────────────────────────────

export default function Settings() {
  const { data: settings, isFetching, isError, refetch } = useSettingsQuery()
  const updateSettings = useUpdateSettings()

  // Local draft state — tracks pending changes before save
  const [draft, setDraft] = useState(null)
  const [saveMsg, setSaveMsg] = useState(null) // { type: 'success' | 'error', text: string }

  // Sync draft from server state when first loaded
  useEffect(() => {
    if (settings && draft === null) {
      setDraft({ ...settings })
    }
  }, [settings, draft])

  const isDirty = draft !== null && settings !== undefined &&
    draft.clean_watermark_enabled !== settings.clean_watermark_enabled

  async function handleSave() {
    if (!isDirty || updateSettings.isPending) return
    try {
      await updateSettings.mutateAsync(draft)
      setSaveMsg({ type: 'success', text: 'Settings saved successfully.' })
    } catch (err) {
      setSaveMsg({
        type: 'error',
        text: err?.response?.data?.detail || err.message || 'Failed to save settings.',
      })
    } finally {
      setTimeout(() => setSaveMsg(null), 4000)
    }
  }

  const isLoading = !settings && isFetching
  const saving = updateSettings.isPending

  return (
    <div>
      {/* Page Header */}
      <div className="page-header">
        <div>
          <h1 className="page-title">
            <Settings2 size={22} color="var(--accent-primary)" />
            Settings
          </h1>
          <div className="page-subtitle">
            Configure global pipeline behaviour and processing options.
          </div>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <button
            className="btn btn-secondary"
            onClick={() => { refetch(); setDraft(null) }}
            disabled={isFetching}
            aria-label="Refresh settings"
          >
            <RefreshCw size={14} className={isFetching ? 'spinner' : ''} />
            <span>Refresh</span>
          </button>

          <button
            className="btn btn-primary"
            onClick={handleSave}
            disabled={!isDirty || saving}
            id="settings-save-btn"
          >
            {saving ? (
              <>
                <span className="spinner" style={{ width: 14, height: 14, borderWidth: 2 }} />
                <span>Saving…</span>
              </>
            ) : (
              <>
                <Save size={14} />
                <span>Save Changes</span>
              </>
            )}
          </button>
        </div>
      </div>

      {/* Save feedback banner */}
      {saveMsg && (
        <div style={{
          margin: '0 0 16px',
          padding: '10px 16px',
          borderRadius: 8,
          fontSize: 13,
          fontWeight: 500,
          backgroundColor: saveMsg.type === 'success'
            ? 'var(--success-subtle, rgba(16,185,129,0.1))'
            : 'var(--error-subtle, rgba(239,68,68,0.1))',
          border: `1px solid ${saveMsg.type === 'success'
            ? 'var(--success-border, rgba(16,185,129,0.3))'
            : 'var(--error-border, rgba(239,68,68,0.3))'}`,
          color: saveMsg.type === 'success' ? 'var(--success)' : 'var(--error)',
        }}>
          {saveMsg.type === 'success' ? '✓ ' : '✕ '}{saveMsg.text}
        </div>
      )}

      {/* Error state */}
      {isError && !isLoading && (
        <div className="card" style={{
          padding: '24px',
          borderColor: 'var(--error-border)',
          color: 'var(--error)',
          fontSize: 13,
          marginBottom: 16,
        }}>
          Failed to load settings. Check your API connection and try refreshing.
        </div>
      )}

      {/* Skeleton loader */}
      {isLoading && (
        <div className="card" style={{ padding: '20px 24px' }}>
          <div className="skeleton" style={{ height: 20, width: '40%', marginBottom: 12 }} />
          <div className="skeleton" style={{ height: 60, width: '100%' }} />
        </div>
      )}

      {/* ── Watermark Cleaning Section ───────────────────────────── */}
      {!isLoading && draft !== null && (
        <>
          {/* Section Card */}
          <div className="card" style={{ padding: 0, marginBottom: 16, overflow: 'hidden' }}>
            {/* Section Header */}
            <div style={{
              padding: '16px 24px',
              borderBottom: '1px solid var(--border-subtle)',
              display: 'flex',
              alignItems: 'center',
              gap: 10,
              backgroundColor: 'var(--bg-subtle)',
            }}>
              <Sparkles size={15} color="var(--accent-primary)" />
              <span style={{
                fontSize: 12,
                fontWeight: 700,
                color: 'var(--text-muted)',
                textTransform: 'uppercase',
                letterSpacing: '0.06em',
              }}>
                Watermark Processing
              </span>
            </div>

            {/* Toggle Row */}
            <SettingRow
              icon={draft.clean_watermark_enabled ? ShieldCheck : ShieldOff}
              iconColor={draft.clean_watermark_enabled
                ? 'var(--success, #10b981)'
                : 'var(--text-muted)'}
              title="Clean Gemini Watermark"
              description={
                draft.clean_watermark_enabled
                  ? 'Watermark removal is ON. Each uploaded video is processed through the Gemini Watermark Remover (gwr) via SSH before enrichment and scheduling.'
                  : 'Watermark removal is OFF. Newly uploaded videos skip the cleaning step and go directly to enrichment and scheduling using the original file.'
              }
              warning={
                !draft.clean_watermark_enabled
                  ? 'When OFF, videos will be published with any existing Gemini watermarks intact. Already-running cleaning jobs are not interrupted.'
                  : null
              }
            >
              <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 6 }}>
                <ToggleSwitch
                  id="toggle-clean-watermark"
                  checked={draft.clean_watermark_enabled}
                  onChange={(val) => setDraft(prev => ({ ...prev, clean_watermark_enabled: val }))}
                  disabled={saving}
                />
                <span style={{
                  fontSize: 11,
                  fontWeight: 600,
                  color: draft.clean_watermark_enabled ? 'var(--success)' : 'var(--text-muted)',
                  textTransform: 'uppercase',
                  letterSpacing: '0.04em',
                }}>
                  {draft.clean_watermark_enabled ? 'Enabled' : 'Disabled'}
                </span>
              </div>
            </SettingRow>
          </div>

          {/* Unsaved changes notice */}
          {isDirty && (
            <div style={{
              padding: '10px 16px',
              borderRadius: 8,
              backgroundColor: 'var(--accent-subtle)',
              border: '1px solid var(--accent-border, rgba(99,179,237,0.3))',
              fontSize: 12.5,
              color: 'var(--accent-primary)',
              fontWeight: 500,
              display: 'flex',
              alignItems: 'center',
              gap: 8,
            }}>
              <span style={{
                width: 6,
                height: 6,
                borderRadius: '50%',
                backgroundColor: 'var(--accent-primary)',
                display: 'inline-block',
                flexShrink: 0,
              }} />
              You have unsaved changes. Click <strong style={{ marginLeft: 3 }}>Save Changes</strong> to apply.
            </div>
          )}
        </>
      )}
    </div>
  )
}
