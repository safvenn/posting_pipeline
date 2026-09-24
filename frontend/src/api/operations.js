import client from './client'

/**
 * Operations API — metrics, job tracker, fault recovery, and security health.
 */

// ── Metrics ────────────────────────────────────────────────────────
export async function getMetrics() {
  const res = await client.get('/metrics')
  return res.data
}

// ── Job Tracker & DLQ ──────────────────────────────────────────────
export async function getJobStats() {
  const res = await client.get('/jobs/stats')
  return res.data
}

export async function getJobs(params = {}) {
  const res = await client.get('/jobs', { params })
  return res.data
}

export async function getRunningJobs() {
  const res = await client.get('/jobs/running')
  return res.data
}

export async function getDeadLetterJobs() {
  const res = await client.get('/jobs/dead-letters')
  return res.data
}

export async function getCircuitBreakerStatus() {
  const res = await client.get('/jobs/circuit-breaker/status')
  return res.data
}

export async function resetCircuitBreaker() {
  const res = await client.post('/jobs/circuit-breaker/reset')
  return res.data
}

export async function requeueAllDeadLetters() {
  const res = await client.post('/jobs/requeue-all-dead-letters')
  return res.data
}

export async function getJobDetail(jobId) {
  const res = await client.get(`/jobs/${jobId}`)
  return res.data
}

export async function retryJob(jobId) {
  const res = await client.post(`/jobs/${jobId}/retry`)
  return res.data
}

export async function cancelJob(jobId) {
  const res = await client.post(`/jobs/${jobId}/cancel`)
  return res.data
}

// ── Security Health & Administration ────────────────────────────────
export async function getSecurityStatus() {
  const res = await client.get('/admin/security-status')
  return res.data
}

export async function rotateSecret(newSecret) {
  const params = newSecret ? { new_secret: newSecret } : {}
  const res = await client.post('/admin/rotate-secret', null, { params })
  return res.data
}
