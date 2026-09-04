import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClientProvider } from '@tanstack/react-query'
import { PersistQueryClientProvider } from '@tanstack/react-query-persist-client'
import { createSyncStoragePersister } from '@tanstack/query-sync-storage-persister'
import './index.css'
import App from './App.jsx'
import { queryClient } from './lib/queryClient.js'

// localStorage persister — safe data only (no credentials, no OAuth tokens)
// Falls back silently if localStorage is unavailable or quota exceeded
let persister = null
try {
  persister = createSyncStoragePersister({
    storage: window.localStorage,
    key: 'yt-pipeline-cache',
  })
} catch {
  // localStorage unavailable — operate without persistence
}

const MAX_CACHE_AGE = 24 * 60 * 60 * 1000 // 24 hours

// Queries that should NOT be persisted to disk:
// - runningJob: must always be live
// - channelStats: YouTube API data, stale after 3 min
const PERSIST_EXCLUDED = new Set(['runningJob', 'channelStats'])

function shouldDehydrate(query) {
  // Only persist queries that have succeeded and are not real-time
  if (query.state.status !== 'success') return false
  const key = query.queryKey?.[0]
  if (PERSIST_EXCLUDED.has(key)) return false
  return true
}

const Root = persister ? (
  <PersistQueryClientProvider
    client={queryClient}
    persistOptions={{
      persister,
      maxAge: MAX_CACHE_AGE,
      dehydrateOptions: {
        shouldDehydrateQuery: shouldDehydrate,
      },
    }}
  >
    <App />
  </PersistQueryClientProvider>
) : (
  <QueryClientProvider client={queryClient}>
    <App />
  </QueryClientProvider>
)

createRoot(document.getElementById('root')).render(
  <StrictMode>
    {Root}
  </StrictMode>,
)

