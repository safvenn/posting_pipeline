import { BrowserRouter, Routes, Route } from 'react-router-dom'
import Layout from './components/Layout'
import Dashboard from './pages/Dashboard'
import Upload from './pages/Upload'
import ScheduleCalendar from './pages/ScheduleCalendar'
import ChannelStats from './pages/ChannelStats'
import FailedJobs from './pages/FailedJobs'
import PostDetail from './pages/PostDetail'
import ASMRWorkflow from './pages/ASMRWorkflow'

export default function App() {
  return (
    <BrowserRouter>
      <Layout>
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/upload" element={<Upload />} />
          <Route path="/schedule" element={<ScheduleCalendar />} />
          <Route path="/channels" element={<ChannelStats />} />
          <Route path="/failed" element={<FailedJobs />} />
          <Route path="/post/:id" element={<PostDetail />} />
          <Route path="/asmr" element={<ASMRWorkflow />} />
        </Routes>
      </Layout>
    </BrowserRouter>
  )
}
