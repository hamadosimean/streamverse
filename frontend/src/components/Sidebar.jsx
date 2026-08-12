import {
  Clapperboard,
  Compass,
  Crown,
  Gavel,
  Home,
  LayoutDashboard,
  Library,
  Megaphone,
  Radio,
  Rss,
  Settings,
  SlidersHorizontal,
  Upload,
} from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { Link, NavLink } from 'react-router-dom'

import { cn } from '@/lib/cn'
import { useAuthStore } from '@/stores/useAuthStore'
import { useUIStore } from '@/stores/useUIStore'

/**
 * Navigation lives here rather than in the header, so the header can give the
 * search field the room it needs. Items are grouped by intent — what there is
 * to watch, what belongs to you, what you administer — because a flat list of
 * eleven links reads as noise.
 *
 * `role: null` = everyone. `auth: true` = signed in. `roles` = those roles only.
 */
const SECTIONS = [
  {
    titleKey: 'nav.sections.discover',
    items: [
      { to: '/', labelKey: 'nav.home', icon: Home, end: true },
      { to: '/browse', labelKey: 'nav.browse', icon: Compass },
      { to: '/shorts', labelKey: 'nav.shorts', icon: Clapperboard },
      { to: '/live', labelKey: 'nav.live', icon: Radio },
      { to: '/premium', labelKey: 'nav.premium', icon: Crown },
    ],
  },
  {
    titleKey: 'nav.sections.you',
    auth: true,
    items: [
      { to: '/subscriptions', labelKey: 'nav.subscriptions', icon: Rss },
      { to: '/library', labelKey: 'nav.library', icon: Library },
      { to: '/upload', labelKey: 'nav.upload', icon: Upload },
      { to: '/studio', labelKey: 'nav.studio', icon: LayoutDashboard },
    ],
  },
  {
    titleKey: 'nav.sections.manage',
    roles: ['moderator', 'admin'],
    items: [
      { to: '/manage/moderation', labelKey: 'nav.moderation', icon: Gavel,
        roles: ['moderator', 'admin'] },
      { to: '/manage/dashboard', labelKey: 'nav.dashboard', icon: SlidersHorizontal,
        roles: ['admin'] },
      { to: '/manage/ads', labelKey: 'nav.adsAdmin', icon: Megaphone,
        roles: ['admin'] },
      // Django admin is a server-rendered page, so a real anchor — not a Link.
      { href: '/admin/', labelKey: 'nav.admin', icon: Settings, roles: ['admin'] },
    ],
  },
]

function itemClasses(isActive, collapsed) {
  return cn(
    'flex items-center rounded-lg text-sm font-medium transition',
    collapsed ? 'justify-center px-0 py-2.5' : 'gap-3 px-3 py-2',
    isActive
      ? 'bg-brand-500/15 text-brand-300'
      : 'text-ink-300 hover:bg-ink-800 hover:text-ink-100',
  )
}

function SidebarNav({ collapsed, onNavigate }) {
  const { t } = useTranslation()
  const user = useAuthStore((state) => state.user)

  const visible = SECTIONS.filter((section) => {
    if (section.auth && !user) return false
    if (section.roles && !section.roles.includes(user?.role)) return false
    return true
  })

  return (
    <nav className="flex flex-col gap-1 p-3">
      {visible.map((section, index) => {
        const items = section.items.filter(
          (item) => !item.roles || item.roles.includes(user?.role),
        )
        if (items.length === 0) return null

        return (
          <div key={section.titleKey} className={cn(index > 0 && 'mt-4')}>
            {index > 0 && <hr className="mb-3 border-ink-800" />}
            {/* The heading is dropped in the rail — at 68px wide there is no room
                for it — but stays in the accessibility tree as a group label. */}
            {collapsed ? (
              <span className="sr-only">{t(section.titleKey)}</span>
            ) : (
              <p className="px-3 pb-1 text-[11px] font-semibold uppercase tracking-wider text-ink-500">
                {t(section.titleKey)}
              </p>
            )}

            <div className="flex flex-col gap-0.5">
              {items.map(({ to, href, labelKey, icon: Icon, end }) =>
                href ? (
                  <a
                    key={href}
                    href={href}
                    onClick={onNavigate}
                    title={collapsed ? t(labelKey) : undefined}
                    className={itemClasses(false, collapsed)}
                  >
                    <Icon className="size-5 shrink-0" aria-hidden />
                    {!collapsed && <span className="truncate">{t(labelKey)}</span>}
                  </a>
                ) : (
                  <NavLink
                    key={to}
                    to={to}
                    end={end}
                    onClick={onNavigate}
                    title={collapsed ? t(labelKey) : undefined}
                    className={({ isActive }) => itemClasses(isActive, collapsed)}
                  >
                    <Icon className="size-5 shrink-0" aria-hidden />
                    {!collapsed && <span className="truncate">{t(labelKey)}</span>}
                  </NavLink>
                ),
              )}
            </div>
          </div>
        )
      })}

      {!user && !collapsed && (
        <div className="mt-4 rounded-lg border border-ink-800 bg-ink-850 p-3">
          <p className="text-xs text-ink-400">{t('nav.signedOutHint')}</p>
          <Link
            to="/login"
            onClick={onNavigate}
            className="mt-2 inline-flex rounded-full border border-brand-500 px-3 py-1 text-xs font-semibold text-brand-300 transition hover:bg-brand-500/10"
          >
            {t('nav.login')}
          </Link>
        </div>
      )}
    </nav>
  )
}

export default function Sidebar() {
  const { sidebarOpen, closeSidebar, sidebarCollapsed } = useUIStore()

  return (
    <>
      {/* Desktop: a column that stays put while the page scrolls. Collapsed it
          becomes an icon rail, which is what gives wide pages (the studio charts,
          the shorts feed) their room back. */}
      <aside
        className={cn(
          'sticky top-16 hidden h-[calc(100dvh-4rem)] shrink-0 overflow-y-auto',
          'border-r border-ink-800 bg-ink-900 transition-[width] duration-200 md:block',
          sidebarCollapsed ? 'w-[68px]' : 'w-60',
        )}
      >
        <SidebarNav collapsed={sidebarCollapsed} />
      </aside>

      {/* Mobile: a drawer over the content. */}
      {sidebarOpen && (
        <>
          <button
            type="button"
            aria-hidden
            tabIndex={-1}
            onClick={closeSidebar}
            className="fixed inset-x-0 bottom-0 top-16 z-30 bg-black/60 md:hidden"
          />
          <aside className="fixed bottom-0 left-0 top-16 z-40 w-64 overflow-y-auto border-r border-ink-800 bg-ink-900 md:hidden">
            <SidebarNav collapsed={false} onNavigate={closeSidebar} />
          </aside>
        </>
      )}
    </>
  )
}
