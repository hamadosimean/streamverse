import { create } from 'zustand'
import { persist } from 'zustand/middleware'

/** Cross-cutting interface state: language and the mobile nav drawer. */
export const useUIStore = create()(
  persist(
    (set) => ({
      language: 'fr', // French is the default UI language
      sidebarOpen: false,

      setLanguage: (language) => set({ language }),
      toggleSidebar: () => set((state) => ({ sidebarOpen: !state.sidebarOpen })),
      closeSidebar: () => set({ sidebarOpen: false }),
    }),
    { name: 'sv.ui' },
  ),
)
