import {
  Compass,
  Crown,
  Library,
  Gavel,
  Home,
  LayoutDashboard,
  LogOut,
  Megaphone,
  Menu,
  Radio,
  Rss,
  Search,
  Upload,
  User,
  X,
} from 'lucide-react'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import toast from 'react-hot-toast'
import { Link, NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'

import { Button } from '@/components/ui'
import { cn } from '@/lib/cn'
import { useAuthStore } from '@/stores/useAuthStore'
import { useUIStore } from '@/stores/useUIStore'

function LanguageSwitcher() {
  const { language, setLanguage } = useUIStore()
  return (
    <div className="flex items-center rounded-lg border border-ink-700 p-0.5" role="group">
      {['fr', 'en'].map((code) => (
        <button
          key={code}
          type="button"
          onClick={() => setLanguage(code)}
          aria-pressed={language === code}
          className={cn(
            'rounded px-2 py-1 text-xs font-semibold uppercase transition',
            language === code
              ? 'bg-brand-600 text-white'
              : 'text-ink-400 hover:text-ink-100',
          )}
        >
          {code}
        </button>
      ))}
    </div>
  )
}

function SearchBar({ className }) {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const [query, setQuery] = useState('')

  return (
    <form
      className={cn('relative', className)}
      onSubmit={(event) => {
        event.preventDefault()
        const trimmed = query.trim()
        navigate(trimmed ? `/search?q=${encodeURIComponent(trimmed)}` : '/browse')
      }}
      role="search"
    >
      <Search
        className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-ink-400"
        aria-hidden
      />
      <input
        type="search"
        value={query}
        onChange={(event) => setQuery(event.target.value)}
        placeholder={t('nav.search')}
        aria-label={t('nav.search')}
        className="sv-input pl-9"
      />
    </form>
  )
}

const NAV_ITEMS = [
  { to: '/', labelKey: 'nav.home', icon: Home, end: true },
  { to: '/browse', labelKey: 'nav.browse', icon: Compass },
  { to: '/live', labelKey: 'nav.live', icon: Radio },
  { to: '/subscriptions', labelKey: 'nav.subscriptions', icon: Rss, auth: true },
  { to: '/library', labelKey: 'nav.library', icon: Library, auth: true },
  { to: '/premium', labelKey: 'nav.premium', icon: Crown },
  { to: '/upload', labelKey: 'nav.upload', icon: Upload, auth: true },
  { to: '/studio', labelKey: 'nav.studio', icon: LayoutDashboard, auth: true },
]

function NavItems({ onNavigate }) {
  const { t } = useTranslation()
  const user = useAuthStore((state) => state.user)

  return NAV_ITEMS.filter((item) => !item.auth || user).map(
    ({ to, labelKey, icon: Icon, end }) => (
      <NavLink
        key={to}
        to={to}
        end={end}
        onClick={onNavigate}
        className={({ isActive }) =>
          cn(
            'flex items-center gap-2 rounded-lg px-3 py-2 text-sm font-medium transition',
            isActive
              ? 'bg-brand-500/15 text-brand-300'
              : 'text-ink-300 hover:bg-ink-800 hover:text-ink-100',
          )
        }
      >
        <Icon className="size-4" aria-hidden />
        {t(labelKey)}
      </NavLink>
    ),
  )
}

export default function Layout() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const location = useLocation()
  const { user, logout } = useAuthStore()
  const { sidebarOpen, toggleSidebar, closeSidebar } = useUIStore()

  // A route change must not leave the mobile drawer covering the new page.
  useEffect(() => {
    closeSidebar()
  }, [location.pathname, closeSidebar])

  const handleLogout = () => {
    logout()
    toast.success(t('auth.loggedOut'))
    navigate('/')
  }

  return (
    <div className="flex min-h-dvh flex-col">
      <header className="sticky top-0 z-40 border-b border-ink-800 bg-ink-900/95 backdrop-blur">
        <div className="mx-auto flex h-16 max-w-[1600px] items-center gap-3 px-4">
          <button
            type="button"
            onClick={toggleSidebar}
            className="rounded-lg p-2 text-ink-300 transition hover:bg-ink-800 md:hidden"
            aria-label={t('nav.menu')}
            aria-expanded={sidebarOpen}
          >
            {sidebarOpen ? <X className="size-5" /> : <Menu className="size-5" />}
          </button>

          <Link to="/" className="flex shrink-0 items-center gap-2">
            <span className="grid size-9 place-items-center rounded-xl bg-gradient-to-br from-brand-500 to-accent-500">
              <svg viewBox="0 0 24 24" className="size-4 fill-white" aria-hidden>
                <path d="M8 5l11 7-11 7z" />
              </svg>
            </span>
            <span className="hidden text-lg font-bold tracking-tight sm:block">
              {t('app.name')}
            </span>
          </Link>

          <nav className="ml-4 hidden items-center gap-1 md:flex">
            <NavItems />
          </nav>

          <SearchBar className="ml-auto w-full max-w-md" />

          <div className="flex shrink-0 items-center gap-2">
            <LanguageSwitcher />
            {user ? (
              <div className="flex items-center gap-1">
                <Link
                  to="/account"
                  className="flex items-center gap-2 rounded-lg px-2 py-1.5 text-sm text-ink-300 transition hover:bg-ink-800 hover:text-ink-100"
                  title={user.display_name}
                >
                  <span className="grid size-7 place-items-center rounded-full bg-brand-600 text-xs font-bold text-white">
                    {(user.display_name || user.username).slice(0, 2).toUpperCase()}
                  </span>
                  <span className="hidden lg:block">{user.display_name}</span>
                </Link>
                <Button
                  variant="ghost"
                  size="icon"
                  onClick={handleLogout}
                  title={t('nav.logout')}
                  aria-label={t('nav.logout')}
                >
                  <LogOut className="size-4" />
                </Button>
              </div>
            ) : (
              <div className="flex items-center gap-2">
                <Button variant="ghost" size="sm" onClick={() => navigate('/login')}>
                  {t('nav.login')}
                </Button>
                <Button size="sm" onClick={() => navigate('/register')}>
                  <User className="size-4" />
                  <span className="hidden sm:inline">{t('nav.register')}</span>
                </Button>
              </div>
            )}
          </div>
        </div>

        {sidebarOpen && (
          <nav className="flex flex-col gap-1 border-t border-ink-800 p-3 md:hidden">
            <NavItems onNavigate={closeSidebar} />
          </nav>
        )}
      </header>

      <main className="mx-auto w-full max-w-[1600px] flex-1 px-4 py-6">
        <Outlet />
      </main>

      <footer className="border-t border-ink-800 py-6">
        <div className="mx-auto flex max-w-[1600px] flex-col items-center justify-between gap-2 px-4 text-xs text-ink-400 sm:flex-row">
          <p>
            {t('app.name')} — {t('app.tagline')}
          </p>
          <div className="flex items-center gap-4">
            <a href="/api/docs/" className="transition hover:text-ink-100">
              API
            </a>
            <a href="/admin/" className="transition hover:text-ink-100">
              {t('nav.admin')}
            </a>
            {['moderator', 'admin'].includes(user?.role) && (
              <Link to="/manage/moderation"
                    className="inline-flex items-center gap-1 transition hover:text-ink-100">
                <Gavel className="size-3.5" aria-hidden />
                {t('nav.moderation')}
              </Link>
            )}
            {user?.role === 'admin' && (
              <>
                <Link to="/manage/ads"
                      className="inline-flex items-center gap-1 transition hover:text-ink-100">
                  <Megaphone className="size-3.5" aria-hidden />
                  {t('nav.adsAdmin')}
                </Link>
                <Link to="/manage/dashboard"
                      className="inline-flex items-center gap-1 transition hover:text-ink-100">
                  <LayoutDashboard className="size-3.5" aria-hidden />
                  {t('nav.dashboard')}
                </Link>
              </>
            )}
            <span>v0.2.0</span>
          </div>
        </div>
      </footer>
    </div>
  )
}
