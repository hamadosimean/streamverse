import { useEffect, useState } from 'react'

import { cn } from '@/lib/cn'

const SIZES = {
  xs: 'size-6 text-[10px]',
  sm: 'size-8 text-xs',
  md: 'size-10 text-sm',
  lg: 'size-16 text-lg',
  xl: 'size-20 text-xl sm:size-24 sm:text-2xl',
}

/** Two letters for the fallback tile — the same rule everywhere. */
export function initials(user) {
  return (user?.display_name || user?.username || '?').slice(0, 2).toUpperCase()
}

/**
 * A user's profile picture, with the initials tile as the fallback.
 *
 * The fallback covers three cases that used to be one: no picture uploaded, a
 * picture whose object has gone missing from the bucket, and the moment before
 * a slow image decodes. `onError` handles the middle one — a broken-image glyph
 * next to someone's name looks like the account is broken.
 */
export default function Avatar({ user, src, size = 'md', className, ...props }) {
  const url = src ?? user?.avatar_url
  const [failed, setFailed] = useState(false)

  // A new URL deserves a new attempt; without this, one failure would stick
  // even after the user uploads a replacement.
  useEffect(() => setFailed(false), [url])

  const shared = cn(
    'shrink-0 rounded-full object-cover',
    SIZES[size] ?? SIZES.md,
    className,
  )

  if (!url || failed) {
    return (
      <span
        className={cn(shared, 'grid place-items-center bg-brand-600 font-bold text-white')}
        aria-hidden
        {...props}
      >
        {initials(user)}
      </span>
    )
  }

  return (
    <img
      src={url}
      alt=""
      loading="lazy"
      decoding="async"
      onError={() => setFailed(true)}
      className={cn(shared, 'bg-ink-800')}
      {...props}
    />
  )
}
