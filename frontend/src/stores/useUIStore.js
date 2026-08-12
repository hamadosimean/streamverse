import { create } from 'zustand'
import { persist } from 'zustand/middleware'

/** Cross-cutting interface state: language and the two sidebar states. */
export const useUIStore = create()(
  persist(
    (set) => ({
      language: 'fr', // French is the default UI language
      // Mobile drawer (transient) and the desktop icon rail (a preference, so
      // it is persisted alongside the language).
      sidebarOpen: false,
      sidebarCollapsed: false,

      setLanguage: (language) => set({ language }),
      toggleSidebar: () => set((state) => ({ sidebarOpen: !state.sidebarOpen })),
      closeSidebar: () => set({ sidebarOpen: false }),
      toggleSidebarCollapsed: () =>
        set((state) => ({ sidebarCollapsed: !state.sidebarCollapsed })),
    }),
    { name: 'sv.ui' },
  ),
)
