import { Menu, Search, Upload, User, X } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, Outlet, useLocation, useNavigate } from 'react-router-dom'

import Logo from '@/components/Logo'
import SearchBar from '@/components/SearchBar'
import Sidebar from '@/components/Sidebar'
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

export default function Layout() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const location = useLocation()
  const user = useAuthStore((state) => state.user)
  const { sidebarOpen, toggleSidebar, closeSidebar, toggleSidebarCollapsed } =
    useUIStore()

  // Below sm the search field would leave no room for anything else, so it is
  // opened on demand as its own row.
  const [mobileSearch, setMobileSearch] = useState(false)

  // A route change must not leave the drawer covering the new page.
  useEffect(() => {
    closeSidebar()
    setMobileSearch(false)
  }, [location.pathname, closeSidebar])

  return (
    <div className="flex min-h-dvh flex-col">
      <header className="sticky top-0 z-40 border-b border-ink-800 bg-ink-900/95 backdrop-blur">
        <div className="flex h-16 items-center gap-2 px-3 sm:gap-3 sm:px-4">
          {/* One button, two jobs: it opens the drawer on mobile and collapses
              the rail on desktop — the same affordance in the same place. */}
          <button
            type="button"
            onClick={() => {
              if (window.matchMedia('(min-width: 768px)').matches) toggleSidebarCollapsed()
              else toggleSidebar()
            }}
            className="shrink-0 rounded-lg p-2 text-ink-300 transition hover:bg-ink-800"
            aria-label={t('nav.menu')}
            aria-expanded={sidebarOpen}
          >
            {sidebarOpen ? <X className="size-5" /> : <Menu className="size-5" />}
          </button>

          <Link to="/" className="flex shrink-0 items-center gap-2" aria-label={t('app.name')}>
            <Logo size={36} />
            {/* The wordmark is dropped below sm so the search field keeps its
                room; the mark alone still identifies the site. */}
            <span className="hidden text-lg font-bold tracking-tight sm:block">
              {t('app.name')}
            </span>
          </Link>

          {/* The search field is the centrepiece of the header now that the links
              have moved to the sidebar. */}
          <div className="hidden flex-1 justify-center px-2 sm:flex">
            <SearchBar className="w-full max-w-2xl" />
          </div>

          <div className="ml-auto flex shrink-0 items-center gap-2 sm:ml-0">
            <button
              type="button"
              onClick={() => setMobileSearch((open) => !open)}
              aria-label={t('nav.search')}
              aria-expanded={mobileSearch}
              className="rounded-lg p-2 text-ink-300 transition hover:bg-ink-800 sm:hidden"
            >
              <Search className="size-5" />
            </button>

            <LanguageSwitcher />

            {user ? (
              <>
                <Button
                  size="sm"
                  onClick={() => navigate('/upload')}
                  className="rounded-full"
                  title={t('nav.upload')}
                >
                  <Upload className="size-4" />
                  <span className="hidden lg:inline">{t('nav.upload')}</span>
                </Button>
                <Link
                  to="/account"
                  className="flex items-center gap-2 rounded-full p-0.5 transition hover:bg-ink-800"
                  title={user.display_name}
                >
                  <span className="grid size-8 place-items-center rounded-full bg-brand-600 text-xs font-bold text-white">
                    {(user.display_name || user.username).slice(0, 2).toUpperCase()}
                  </span>
                </Link>
              </>
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

        {mobileSearch && (
          <div className="border-t border-ink-800 p-3 sm:hidden">
            <SearchBar autoFocus onSubmitted={() => setMobileSearch(false)} />
          </div>
        )}
      </header>

      <div className="flex flex-1">
        <Sidebar />

        {/* min-w-0 so a wide child (a table, a chart) scrolls inside itself
            instead of stretching the flex row and pushing the sidebar off. */}
        <div className="flex min-w-0 flex-1 flex-col">
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
                <span>v0.2.0</span>
              </div>
            </div>
          </footer>
        </div>
      </div>
    </div>
  )
}
