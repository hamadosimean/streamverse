import { Bookmark, BookmarkCheck, UserCheck, UserPlus } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import toast from 'react-hot-toast'
import { useNavigate } from 'react-router-dom'

import { Button } from '@/components/ui'
import { cn } from '@/lib/cn'
import { apiErrorMessage } from '@/lib/api'
import { formatCount } from '@/lib/format'
import { useToggleBookmark, useToggleFollow } from '@/features/library/api'
import { useAuthStore } from '@/stores/useAuthStore'

/**
 * Save-for-later toggle.
 *
 * The parent passes the current state from whatever payload it already has, so
 * a grid of cards costs zero extra requests. Only the toggle itself hits the
 * API, and the server is the authority on the result.
 */
export function BookmarkButton({ videoId, isBookmarked, size = 'sm', showLabel = true }) {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const user = useAuthStore((state) => state.user)
  const toggle = useToggleBookmark()

  const saved = toggle.data?.is_bookmarked ?? isBookmarked

  const onClick = async (event) => {
    event.preventDefault()
    event.stopPropagation()
    if (!user) {
      toast(t('library.loginToSave'))
      navigate('/login')
      return
    }
    try {
      const result = await toggle.mutateAsync(videoId)
      toast.success(result.is_bookmarked ? t('library.saved') : t('library.unsaved'))
    } catch (error) {
      toast.error(apiErrorMessage(error))
    }
  }

  const Icon = saved ? BookmarkCheck : Bookmark

  return (
    <Button
      variant={saved ? 'outline' : 'secondary'}
      size={showLabel ? size : 'icon'}
      onClick={onClick}
      loading={toggle.isPending}
      aria-pressed={Boolean(saved)}
      aria-label={saved ? t('library.unsave') : t('library.save')}
      title={saved ? t('library.unsave') : t('library.save')}
    >
      <Icon className={cn('size-4', saved && 'fill-brand-400/30')} aria-hidden />
      {showLabel && (saved ? t('library.saved_short') : t('library.save'))}
    </Button>
  )
}

/**
 * Follow / unfollow a channel.
 *
 * Following affects only the follower's own feed — there are no notifications,
 * so this never causes anything to be sent to the channel owner.
 */
export function FollowButton({ username, isFollowing, followerCount, isSelf,
                               size = 'md' }) {
  const { t, i18n } = useTranslation()
  const navigate = useNavigate()
  const user = useAuthStore((state) => state.user)
  const toggle = useToggleFollow()

  // Your own channel gets a count, not a button you can never press.
  if (isSelf || (user && user.username === username)) {
    return (
      <span className="text-xs text-ink-400">
        {t('library.followerCount', {
          count: formatCount(toggle.data?.follower_count ?? followerCount ?? 0,
                             i18n.language),
        })}
      </span>
    )
  }

  const following = toggle.data?.is_following ?? isFollowing
  const count = toggle.data?.follower_count ?? followerCount

  const onClick = async (event) => {
    event.preventDefault()
    event.stopPropagation()
    if (!user) {
      toast(t('library.loginToFollow'))
      navigate('/login')
      return
    }
    try {
      const result = await toggle.mutateAsync(username)
      toast.success(result.is_following
        ? t('library.nowFollowing', { channel: username })
        : t('library.unfollowed', { channel: username }))
    } catch (error) {
      toast.error(apiErrorMessage(error))
    }
  }

  return (
    <div className="flex items-center gap-2">
      <Button
        variant={following ? 'secondary' : 'primary'}
        size={size}
        onClick={onClick}
        loading={toggle.isPending}
        aria-pressed={Boolean(following)}
      >
        {following ? (
          <>
            <UserCheck className="size-4" aria-hidden />
            {t('library.following')}
          </>
        ) : (
          <>
            <UserPlus className="size-4" aria-hidden />
            {t('library.follow')}
          </>
        )}
      </Button>
      {count != null && (
        <span className="text-xs text-ink-400">
          {t('library.followerCount', { count: formatCount(count, i18n.language) })}
        </span>
      )}
    </div>
  )
}
