import {
  Bookmark,
  BookmarkCheck,
  MessageSquare,
  Share2,
  ThumbsDown,
  ThumbsUp,
} from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import toast from 'react-hot-toast'
import { Link, useNavigate } from 'react-router-dom'

import { cn } from '@/lib/cn'
import { apiErrorMessage } from '@/lib/api'
import { formatCount } from '@/lib/format'
import { useSetReaction } from '@/features/engagement/api'
import { useToggleBookmark, useToggleFollow } from '@/features/library/api'
import { useAuthStore } from '@/stores/useAuthStore'

function ActionButton({ icon: Icon, label, count, active, onClick, filled }) {
  const { i18n } = useTranslation()
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={label}
      title={label}
      className="flex flex-col items-center gap-1 text-white transition hover:scale-105"
    >
      <span className="grid size-11 place-items-center rounded-full bg-black/50 backdrop-blur">
        <Icon
          className={cn('size-5', active && 'text-brand-300', filled && 'fill-current')}
          aria-hidden
        />
      </span>
      {count != null && (
        <span className="text-[11px] font-medium tabular-nums drop-shadow">
          {formatCount(count, i18n.language)}
        </span>
      )}
    </button>
  )
}

/**
 * The action rail and caption over a Short.
 *
 * Counts update optimistically from each mutation's own response rather than
 * refetching the feed — a refetch would reorder the list under the viewer's
 * thumb mid-scroll.
 */
export default function ShortOverlay({ short }) {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const user = useAuthStore((state) => state.user)

  const setReaction = useSetReaction(short.id)
  const toggleBookmark = useToggleBookmark()
  const toggleFollow = useToggleFollow()

  const [expanded, setExpanded] = useState(false)

  const reaction = setReaction.data?.my_reaction ?? short.my_reaction
  const likes = setReaction.data?.like_count ?? short.like_count
  const saved = toggleBookmark.data?.is_bookmarked ?? short.is_bookmarked
  const following = toggleFollow.data?.is_following ?? short.is_following_uploader

  const requireLogin = (message) => {
    toast(message)
    navigate('/login')
  }

  const react = async (value) => {
    if (!user) return requireLogin(t('engagement.loginToReact'))
    try {
      await setReaction.mutateAsync(reaction === value ? null : value)
    } catch (error) {
      toast.error(apiErrorMessage(error))
    }
  }

  const save = async () => {
    if (!user) return requireLogin(t('library.loginToSave'))
    try {
      const result = await toggleBookmark.mutateAsync(short.id)
      toast.success(result.is_bookmarked ? t('library.saved') : t('library.unsaved'))
    } catch (error) {
      toast.error(apiErrorMessage(error))
    }
  }

  const follow = async () => {
    if (!user) return requireLogin(t('library.loginToFollow'))
    try {
      await toggleFollow.mutateAsync(short.uploader.username)
    } catch (error) {
      toast.error(apiErrorMessage(error))
    }
  }

  const share = async () => {
    const url = `${window.location.origin}/shorts/${short.id}`
    try {
      if (navigator.share) await navigator.share({ title: short.title, url })
      else {
        await navigator.clipboard.writeText(url)
        toast.success(t('engagement.linkCopied'))
      }
    } catch {
      /* dismissed share sheet is not an error */
    }
  }

  const isOwn = user && short.uploader?.username === user.username

  return (
    <>
      {/* Action rail */}
      <div className="pointer-events-none absolute inset-y-0 right-0 z-20 flex w-16 flex-col items-center justify-end gap-4 pb-24">
        <div className="pointer-events-auto flex flex-col items-center gap-4">
          <ActionButton
            icon={ThumbsUp}
            label={t('engagement.like')}
            count={likes}
            active={reaction === 'like'}
            filled={reaction === 'like'}
            onClick={() => react('like')}
          />
          <ActionButton
            icon={ThumbsDown}
            label={t('engagement.dislike')}
            active={reaction === 'dislike'}
            filled={reaction === 'dislike'}
            onClick={() => react('dislike')}
          />
          {/* Comments live on the watch page — a threaded discussion does not
              fit a 420px-wide overlay, and duplicating it would mean two
              comment UIs to keep correct. */}
          <Link to={`/watch/${short.id}`} aria-label={t('shorts.openComments')}>
            <ActionButton
              icon={MessageSquare}
              label={t('shorts.openComments')}
              count={short.comment_count}
            />
          </Link>
          <ActionButton
            icon={saved ? BookmarkCheck : Bookmark}
            label={saved ? t('library.unsave') : t('library.save')}
            active={saved}
            onClick={save}
          />
          <ActionButton icon={Share2} label={t('engagement.share')} onClick={share} />
        </div>
      </div>

      {/* Caption + author */}
      <div className="pointer-events-none absolute inset-x-0 bottom-0 z-20 bg-gradient-to-t from-black/85 via-black/40 to-transparent p-4 pr-20 pb-6">
        <div className="pointer-events-auto">
          <div className="mb-2 flex items-center gap-2">
            <Link
              to={`/c/${short.uploader?.username}`}
              className="flex items-center gap-2 text-white"
            >
              <span className="grid size-8 place-items-center rounded-full bg-brand-600 text-[11px] font-bold">
                {(short.uploader?.display_name || short.uploader?.username || '?')
                  .slice(0, 2)
                  .toUpperCase()}
              </span>
              <span className="text-sm font-semibold drop-shadow">
                @{short.uploader?.username}
              </span>
            </Link>

            {!isOwn && (
              <button
                type="button"
                onClick={follow}
                className={cn(
                  'rounded-full border px-3 py-1 text-xs font-semibold transition',
                  following
                    ? 'border-white/40 text-white/80'
                    : 'border-white bg-white text-black hover:bg-white/90',
                )}
              >
                {following ? t('library.following') : t('library.follow')}
              </button>
            )}
          </div>

          <p className="text-sm font-medium text-white drop-shadow">{short.title}</p>

          {short.description && (
            <p
              role="button"
              tabIndex={0}
              onClick={() => setExpanded((v) => !v)}
              onKeyDown={(e) => ['Enter', ' '].includes(e.key) && setExpanded((v) => !v)}
              className={cn(
                'mt-1 cursor-pointer whitespace-pre-line text-xs text-white/80 drop-shadow',
                expanded ? 'max-h-32 overflow-y-auto' : 'line-clamp-2',
              )}
            >
              {short.description}
            </p>
          )}

          <Link
            to={`/watch/${short.id}`}
            className="mt-2 inline-block text-[11px] text-white/70 underline hover:text-white"
          >
            {t('shorts.openFullPage')}
          </Link>
        </div>
      </div>
    </>
  )
}
