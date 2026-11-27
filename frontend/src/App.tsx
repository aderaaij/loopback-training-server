import { BrowserRouter, Navigate, Outlet, Route, Routes, useLocation } from 'react-router-dom'
import type { ReactNode } from 'react'
import { Layout } from './components/Layout'
import { PageHeaderProvider } from './components/PageHeader'
import { AuthProvider, useAuth } from './lib/auth'
import { Calendar } from './screens/Calendar'
import { Health } from './screens/Health'
import { Login } from './screens/Login'
import { Notes } from './screens/Notes'
import { OAuthConsent } from './screens/OAuthConsent'
import { Overview } from './screens/Overview'
import { PlanDetail } from './screens/PlanDetail'
import { Plans } from './screens/Plans'
import { Queue } from './screens/Queue'
import { Settings } from './screens/Settings'
import { System } from './screens/System'
import { Users } from './screens/Users'
import { WorkoutDetail } from './screens/WorkoutDetail'
import { Workouts } from './screens/Workouts'

function RequireAuth({ children }: { children: ReactNode }) {
  const { user } = useAuth()
  const location = useLocation()
  // Where they were headed goes along, so signing in lands them there. It
  // matters for the page an assistant sends them to (/oauth/consent), whose
  // address carries the request they came to answer.
  if (!user) return <Navigate to="/login" replace state={{ from: location.pathname + location.search }} />
  return children
}

/** Admins manage accounts, they aren't athletes — athlete screens have no data for them. */
function AthleteOnly() {
  const { user } = useAuth()
  if (user?.role === 'admin') return <Navigate to="/users" replace />
  return <Outlet />
}

export default function App() {
  return (
    <AuthProvider>
      <PageHeaderProvider>
        <BrowserRouter>
          <Routes>
            <Route path="/login" element={<Login />} />
            <Route
              path="/oauth/consent"
              element={
                <RequireAuth>
                  <OAuthConsent />
                </RequireAuth>
              }
            />
            <Route
              element={
                <RequireAuth>
                  <Layout />
                </RequireAuth>
              }
            >
              <Route element={<AthleteOnly />}>
                <Route path="/" element={<Overview />} />
                <Route path="/calendar" element={<Calendar />} />
                <Route path="/workouts" element={<Workouts />} />
                <Route path="/workouts/:id" element={<WorkoutDetail />} />
                <Route path="/plans" element={<Plans />} />
                <Route path="/plans/:id" element={<PlanDetail />} />
                <Route path="/notes" element={<Notes />} />
                <Route path="/health" element={<Health />} />
                <Route path="/queue" element={<Queue />} />
              </Route>
              <Route path="/settings" element={<Settings />} />
              <Route path="/users" element={<Users />} />
              <Route path="/system" element={<System />} />
              <Route path="*" element={<Navigate to="/" replace />} />
            </Route>
          </Routes>
        </BrowserRouter>
      </PageHeaderProvider>
    </AuthProvider>
  )
}
