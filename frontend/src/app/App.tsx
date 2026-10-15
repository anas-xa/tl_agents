import { Suspense, lazy } from 'react'
import { BrowserRouter, Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { AuthProvider, useAuth } from './auth'
import { Shell } from '../shell/Shell'
import { Placeholder } from '../components/Placeholder'
import { Skeleton } from '../components/ui'
import { ROUTES, type FeatureRoute } from '../features/registry'
import '../features'

const SignIn = lazy(() => import('../shell/SignIn'))
const AuthComplete = lazy(() => import('../shell/AuthComplete'))
const StaticPage = lazy(() => import('../shell/StaticPage'))
const DemoGuide = lazy(() => import('../features/demo/DemoGuide'))

function RequireAuth({ children }: { children: React.ReactNode }) {
  const { me, loading } = useAuth()
  const loc = useLocation()
  if (loading && !me) return <div className="page"><Skeleton rows={4} /></div>
  if (!me) return <Navigate to={`/signin?return_to=${encodeURIComponent(loc.pathname + loc.search)}`} replace />
  return <>{children}</>
}

function Guarded({ route }: { route: FeatureRoute }) {
  const { me, companyId, can } = useAuth()
  const Element = route.element as React.ComponentType
  if (!me) return null
  let allowed = true
  if (route.scope === 'staff') allowed = !route.permission || me.staff_permissions.includes(route.permission)
  else if (route.scope === 'company') allowed = !!companyId && (!route.permission || can(route.permission, companyId))
  else if (route.permission) allowed = can(route.permission, companyId) || me.staff_permissions.includes(route.permission)
  if (!allowed) return <Placeholder variant={route.fallback ?? 'C'} />
  return <Element />
}

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <Suspense fallback={<div className="page"><Skeleton rows={4} /></div>}>
          <Routes>
            <Route path="/signin" element={<SignIn />} />
            <Route path="/auth/complete" element={<AuthComplete />} />
            <Route path="/privacy" element={<StaticPage page="privacy" />} />
            <Route path="/accessibility" element={<StaticPage page="accessibility" />} />
            <Route path="/verify/:code" element={<StaticPage page="verify" />} />
            <Route path="/demo" element={<DemoGuide />} />
            <Route element={<RequireAuth><Shell /></RequireAuth>}>
              {ROUTES.map((r) => (
                <Route key={r.path} path={r.path} element={<Guarded route={r} />} />
              ))}
              <Route path="*" element={<Placeholder variant="C" />} />
            </Route>
          </Routes>
        </Suspense>
      </AuthProvider>
    </BrowserRouter>
  )
}
