import client from './client'

/**
 * Fetch current app-wide pipeline settings.
 * @returns {Promise<{ clean_watermark_enabled: boolean }>}
 */
export const getSettings = () => client.get('/settings').then(r => r.data)

/**
 * Update app-wide pipeline settings.
 * @param {{ clean_watermark_enabled: boolean }} payload
 * @returns {Promise<{ clean_watermark_enabled: boolean }>}
 */
export const updateSettings = (payload) =>
  client.patch('/settings', payload).then(r => r.data)
