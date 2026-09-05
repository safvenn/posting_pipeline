import { lazy, Suspense } from 'react'
import { BrowserRouter, Routes, Route } from 'react-router-dom'
import Layout from './components/Layout'
import ProtectedRoute from './components/ProtectedRoute'
import { AuthProvider } from './context/AuthContext'

// Lazy-load all pages
const Login = lazy(() => import('./pages/Login'))
const Dashboard = lazy(() => import('./pages/Dashboard'))
const Upload = lazy(() => import('./pages/Upload'))
const ScheduleCalendar = lazy(() => import('./pages/ScheduleCalendar'))
const ChannelStats = lazy(() => import('./pages/ChannelStats'))
const FailedJobs = lazy(() => import('./pages/FailedJobs'))
const PostDetail = lazy(() => import('./pages/PostDetail'))
const ASMRWorkflow = lazy(() => import('./pages/ASMRWorkflow'))
const NotFound = lazy(() => import('./pages/NotFound'))

function PageLoader() {
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        height: '60vh',
        color: 'var(--text-muted)',
        fontSize: 13,
        gap: 8,
      }}
    >
      <span className="spinner" style={{ width: 16, height: 16, borderWidth: 2 }} />
    </div>
  )
}

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Suspense fallback={<PageLoader />}>
          <Routes>
            <Route path="/login" element={<Login />} />
            <Route
              path="/*"
              element={
                <ProtectedRoute>
                  <Layout>
                    <Routes>
                      <Route path="/" element={<Dashboard />} />
                      <Route path="/upload" element={<Upload />} />
                      <Route path="/schedule" element={<ScheduleCalendar />} />
                      <Route path="/channels" element={<ChannelStats />} />
                      <Route path="/failed" element={<FailedJobs />} />
                      <Route path="/post/:id" element={<PostDetail />} />
                      <Route path="/asmr" element={<ASMRWorkflow />} />
                      <Route path="*" element={<NotFound />} />
                    </Routes>
                  </Layout>
                </ProtectedRoute>
              }
            />
          </Routes>
        </Suspense>
      </BrowserRouter>
    </AuthProvider>
  )
}
