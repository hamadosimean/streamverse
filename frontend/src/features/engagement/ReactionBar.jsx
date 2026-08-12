import { Flag, Share2, ThumbsDown, ThumbsUp } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import toast from 'react-hot-toast'
import { useNavigate } from 'react-router-dom'

import ReportModal from '@/features/engagement/ReportModal'
import { Button } from '@/components/ui'
import { cn } from '@/lib/cn'
import { apiErrorMessage } from '@/lib/api'
import { formatCount } from '@/lib/format'
import { useReaction, useSetReaction } from '@/features/engagement/api'
import { useAuthStore } from '@/stores/useAuthStore'

export default function ReactionBar({ video }) {
  const { t, i18n } = useTranslation()
  const navigate = useNavigate()
  const user = useAuthStore((state) => state.user)
  const [reportOpen, setReportOpen] = useState(false)

  const { data: reaction } = useReaction(video.id, { enabled: Boolean(user) })
  const setReaction = useSetReaction(video.id)

  // Counts come from the reaction endpoint once loaded, from the video payload
  // before that — so the numbers are visible immediately for signed-out viewers.
  const likeCount = reaction?.like_count ?? video.like_count
  const dislikeCount = reaction?.dislike_count ?? video.dislike_count
  const mine = reaction?.my_reaction ?? null

  const react = async (value) => {
    if (!user) {
      toast(t('engagement.loginToReact'))
      navigate('/login')
      return
    }
    try {
      await setReaction.mutateAsync(mine === value ? null : value)
    } catch (error) {
      toast.error(apiErrorMessage(error))
    }
  }

  const share = async () => {
    const url = window.location.href
    try {
      if (navigator.share) {
        await navigator.share({ title: video.title, url })
      } else {
        await navigator.clipboard.writeText(url)
        toast.success(t('engagement.linkCopied'))
      }
    } catch {
      // The user dismissing the share sheet is not an error worth reporting.
    }
  }

  return (
    <>
      <div className="flex flex-wrap items-center gap-2">
        <div className="flex items-center overflow-hidden rounded-full bg-ink-800">
          <button
            type="button"
            onClick={() => react('like')}
            disabled={setReaction.isPending}
            aria-pressed={mine === 'like'}
            aria-label={t('engagement.like')}
            className={cn(
              'flex items-center gap-2 px-4 py-2 text-sm transition hover:bg-ink-700',
              mine === 'like' ? 'text-brand-300' : 'text-ink-200',
            )}
          >
            <ThumbsUp
              className={cn('size-4', mine === 'like' && 'fill-brand-400')}
              aria-hidden
            />
            {formatCount(likeCount, i18n.language)}
          </button>

          <span className="h-5 w-px bg-ink-700" aria-hidden />

          <button
            type="button"
            onClick={() => react('dislike')}
            disabled={setReaction.isPending}
            aria-pressed={mine === 'dislike'}
            aria-label={t('engagement.dislike')}
            className={cn(
              'flex items-center gap-2 px-4 py-2 text-sm transition hover:bg-ink-700',
              mine === 'dislike' ? 'text-red-300' : 'text-ink-200',
            )}
          >
            <ThumbsDown
              className={cn('size-4', mine === 'dislike' && 'fill-red-400')}
              aria-hidden
            />
            {formatCount(dislikeCount, i18n.language)}
          </button>
        </div>

        <Button variant="secondary" size="sm" onClick={share}>
          <Share2 className="size-4" aria-hidden />
          {t('engagement.share')}
        </Button>

        {user && video.uploader?.id !== user.id && (
          <Button variant="ghost" size="sm" onClick={() => setReportOpen(true)}>
            <Flag className="size-4" aria-hidden />
            {t('engagement.report')}
          </Button>
        )}
      </div>

      <ReportModal
        open={reportOpen}
        onClose={() => setReportOpen(false)}
        targetType="video"
        targetId={video.id}
        targetLabel={video.title}
      />
    </>
  )
}
