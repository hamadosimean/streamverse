import NProgress from 'nprogress'
import { Suspense, lazy, useEffect } from 'react'
import { Navigate, Route, Routes, useLocation } from 'react-router-dom'

import Layout from '@/components/Layout'
import { LoadingBlock } from '@/components/ui'
import { useAuthStore } from '@/stores/useAuthStore'

// Route-level code splitting: the watch page pulls in hls.js and the studio
// pulls in recharts, neither of which the home feed needs.
const HomePage = lazy(() => import('@/features/videos/HomePage'))
const BrowsePage = lazy(() => import('@/features/videos/BrowsePage'))
const WatchPage = lazy(() => import('@/features/videos/WatchPage'))
const SearchPage = lazy(() => import('@/features/search/SearchPage'))
const ChannelPage = lazy(() => import('@/features/channel/ChannelPage'))
const ShortsPage = lazy(() => import('@/features/shorts/ShortsPage'))
const LivePage = lazy(() => import('@/features/live/LivePage'))
const LiveWatchPage = lazy(() => import('@/features/live/LiveWatchPage'))
const StudioLivePage = lazy(() => import('@/features/live/StudioLivePage'))
const PlansPage = lazy(() => import('@/features/monetization/PlansPage'))
const LibraryPage = lazy(() => import('@/features/library/LibraryPage'))
const SubscriptionsPage = lazy(() =>
  import('@/features/library/SubscriptionsPage'))
const AdCampaignsPage = lazy(() => import('@/features/admin/AdCampaignsPage'))
const AdminDashboardPage = lazy(() => import('@/features/admin/AdminDashboardPage'))
const ModerationQueuePage = lazy(() =>
  import('@/features/moderation/ModerationQueuePage'))
const UploadPage = lazy(() => import('@/features/upload/UploadPage'))
const StudioPage = lazy(() => import('@/features/studio/StudioPage'))
const StudioVideoEditPage = lazy(() => import('@/features/studio/StudioVideoEditPage'))
const AccountPage = lazy(() => import('@/features/account/AccountPage'))
const LoginPage = lazy(() => import('@/features/auth/LoginPage'))
const RegisterPage = lazy(() => import('@/features/auth/RegisterPage'))
const ActivatePage = lazy(() => import('@/features/auth/ActivatePage'))
const ForgotPasswordPage = lazy(() => import('@/features/auth/ForgotPasswordPage'))
const ResetPasswordPage = lazy(() => import('@/features/auth/ResetPasswordPage'))
const NotFoundPage = lazy(() => import('@/features/NotFoundPage'))

NProgress.configure({ showSpinner: false, minimum: 0.15 })

function RouteProgress() {
  const location = useLocation()
  useEffect(() => {
    NProgress.start()
    // Let the lazy chunk settle before completing, so the bar is not a flicker.
    const timer = setTimeout(() => NProgress.done(), 250)
    return () => {
      clearTimeout(timer)
      NProgress.done()
    }
  }, [location.pathname])
  return null
}

/**
 * Client-side gate. It only decides what to *render*; every endpoint behind
 * these routes independently enforces authentication server-side.
 */
function RequireAuth({ children }) {
  const { user, status } = useAuthStore()
  const location = useLocation()

  // Wait for the boot-time /accounts/me/ call rather than bouncing a user who
  // is in fact signed in.
  if (status === 'idle' || status === 'loading') return <LoadingBlock />
  if (!user) return <Navigate to="/login" state={{ from: location }} replace />
  return children
}

/**
 * Admin gate. Like RequireAuth this only decides what to *render* — every
 * campaign endpoint independently enforces the admin role server-side.
 */
function RequireAdmin({ children }) {
  const { user, status } = useAuthStore()
  const location = useLocation()

  if (status === 'idle' || status === 'loading') return <LoadingBlock />
  if (!user) return <Navigate to="/login" state={{ from: location }} replace />
  if (user.role !== 'admin') return <Navigate to="/" replace />
  return children
}

/** Moderator *or* admin — admins inherit every moderator capability. */
function RequireModerator({ children }) {
  const { user, status } = useAuthStore()
  const location = useLocation()

  if (status === 'idle' || status === 'loading') return <LoadingBlock />
  if (!user) return <Navigate to="/login" state={{ from: location }} replace />
  if (!['moderator', 'admin'].includes(user.role)) return <Navigate to="/" replace />
  return children
}

function GuestOnly({ children }) {
  const user = useAuthStore((state) => state.user)
  return user ? <Navigate to="/" replace /> : children
}

export default function AppRoutes() {
  return (
    <>
      <RouteProgress />
      <Suspense fallback={<LoadingBlock />}>
        <Routes>
          <Route element={<Layout />}>
            <Route index element={<HomePage />} />
            <Route path="browse" element={<BrowsePage />} />
            <Route path="watch/:videoId" element={<WatchPage />} />
            <Route path="search" element={<SearchPage />} />
            <Route path="c/:username" element={<ChannelPage />} />
            <Route path="shorts" element={<ShortsPage />} />
            <Route path="shorts/:videoId" element={<ShortsPage />} />
            <Route path="live" element={<LivePage />} />
            <Route path="live/:slug" element={<LiveWatchPage />} />
            <Route path="premium" element={<PlansPage />} />

            <Route
              path="login"
              element={
                <GuestOnly>
                  <LoginPage />
                </GuestOnly>
              }
            />
            <Route
              path="register"
              element={
                <GuestOnly>
                  <RegisterPage />
                </GuestOnly>
              }
            />
            <Route path="activate/:uid/:token" element={<ActivatePage />} />
            <Route path="password/forgot" element={<ForgotPasswordPage />} />
            <Route path="password/reset/:uid/:token" element={<ResetPasswordPage />} />

            <Route
              path="library"
              element={
                <RequireAuth>
                  <LibraryPage />
                </RequireAuth>
              }
            />
            <Route
              path="subscriptions"
              element={
                <RequireAuth>
                  <SubscriptionsPage />
                </RequireAuth>
              }
            />
            <Route
              path="upload"
              element={
                <RequireAuth>
                  <UploadPage />
                </RequireAuth>
              }
            />
            <Route
              path="studio"
              element={
                <RequireAuth>
                  <StudioPage />
                </RequireAuth>
              }
            />
            <Route
              path="studio/live"
              element={
                <RequireAuth>
                  <StudioLivePage />
                </RequireAuth>
              }
            />
            <Route
              path="studio/videos/:videoId"
              element={
                <RequireAuth>
                  <StudioVideoEditPage />
                </RequireAuth>
              }
            />
            {/* `/admin/` belongs to Django (nginx proxies that prefix), so the
                React admin views live under /manage/ to avoid the collision. */}
            <Route
              path="manage/moderation"
              element={
                <RequireModerator>
                  <ModerationQueuePage />
                </RequireModerator>
              }
            />
            <Route
              path="manage/dashboard"
              element={
                <RequireAdmin>
                  <AdminDashboardPage />
                </RequireAdmin>
              }
            />
            <Route
              path="manage/ads"
              element={
                <RequireAdmin>
                  <AdCampaignsPage />
                </RequireAdmin>
              }
            />
            <Route
              path="account"
              element={
                <RequireAuth>
                  <AccountPage />
                </RequireAuth>
              }
            />

            <Route path="*" element={<NotFoundPage />} />
          </Route>
        </Routes>
      </Suspense>
    </>
  )
}
