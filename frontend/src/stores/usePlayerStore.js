import { create } from 'zustand'
import { persist } from 'zustand/middleware'

/**
 * Playback preferences that must survive navigation between videos.
 *
 * Volume and the manual quality choice are persisted; transient per-playback
 * state (currentTime, buffering, levels) stays inside the player component,
 * because lifting it here would re-render the whole tree on every timeupdate.
 */
export const usePlayerStore = create()(
  persist(
    (set) => ({
      volume: 1,
      muted: false,
      // -1 means "let hls.js pick" — the ABR default.
      preferredLevel: -1,
      autoplay: false,

      setVolume: (volume) => set({ volume, muted: volume === 0 }),
      toggleMuted: () => set((state) => ({ muted: !state.muted })),
      setPreferredLevel: (preferredLevel) => set({ preferredLevel }),
      setAutoplay: (autoplay) => set({ autoplay }),
    }),
    { name: 'sv.player' },
  ),
)
