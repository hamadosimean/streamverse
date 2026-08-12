import { Flag, MessageSquare, Pencil, Reply, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import toast from 'react-hot-toast'
import { Link } from 'react-router-dom'

import ReportModal from '@/features/engagement/ReportModal'
import { Button, EmptyState, LoadingBlock } from '@/components/ui'
import { apiErrorMessage } from '@/lib/api'
import { formatCount, formatRelative } from '@/lib/format'
import {
  useComments,
  useCreateComment,
  useDeleteComment,
  useUpdateComment,
} from '@/features/engagement/api'
import { useAuthStore } from '@/stores/useAuthStore'

const MAX_LENGTH = 2000

function Avatar({ user, size = 'md' }) {
  const dimension = size === 'sm' ? 'size-7 text-[10px]' : 'size-9 text-xs'
  if (!user) {
    return <span className={`${dimension} shrink-0 rounded-full bg-ink-700`} />
  }
  return (
    <Link
      to={`/c/${user.username}`}
      className={`grid ${dimension} shrink-0 place-items-center rounded-full bg-brand-600 font-bold text-white`}
      title={user.display_name}
    >
      {(user.display_name || user.username).slice(0, 2).toUpperCase()}
    </Link>
  )
}

/**
 * One form, three jobs: new top-level comment, reply, or edit.
 *
 * `editCommentId` is what selects edit mode — passing the id explicitly rather
 * than inferring it from the presence of initial text, so an edit that clears
 * the box still behaves as an edit.
 */
function CommentForm({
  videoId,
  parentId,
  editCommentId,
  initialValue = '',
  onDone,
  onCancel,
  autoFocus,
}) {
  const { t } = useTranslation()
  const user = useAuthStore((state) => state.user)
  const [value, setValue] = useState(initialValue)

  const create = useCreateComment(videoId)
  const update = useUpdateComment(videoId)
  const isEdit = Boolean(editCommentId)
  const pending = create.isPending || update.isPending

  const submit = async (event) => {
    event.preventDefault()
    const content = value.trim()
    if (!content) return
    try {
      if (isEdit) {
        await update.mutateAsync({ commentId: editCommentId, content })
      } else {
        await create.mutateAsync({ content, parentComment: parentId ?? null })
        setValue('')
      }
      onDone?.()
    } catch (error) {
      toast.error(apiErrorMessage(error))
    }
  }

  if (!user) return null

  return (
    <form onSubmit={submit} className="flex gap-3">
      <Avatar user={user} size={parentId ? 'sm' : 'md'} />
      <div className="min-w-0 flex-1">
        <textarea
          rows={parentId ? 2 : 3}
          maxLength={MAX_LENGTH}
          autoFocus={autoFocus}
          className="sv-input resize-y"
          placeholder={parentId ? t('engagement.replyPlaceholder') : t('engagement.commentPlaceholder')}
          value={value}
          onChange={(event) => setValue(event.target.value)}
        />
        <div className="mt-2 flex items-center gap-2">
          <Button type="submit" size="sm" loading={pending} disabled={!value.trim()}>
            {isEdit ? t('common.save') : parentId ? t('engagement.reply') : t('engagement.comment')}
          </Button>
          {onCancel && (
            <Button type="button" variant="ghost" size="sm" onClick={onCancel}>
              {t('common.cancel')}
            </Button>
          )}
          <span className="ml-auto text-[11px] text-ink-500">
            {value.length}/{MAX_LENGTH}
          </span>
        </div>
      </div>
    </form>
  )
}

function CommentNode({ comment, videoId, depth = 0 }) {
  const { t, i18n } = useTranslation()
  const user = useAuthStore((state) => state.user)
  const [replying, setReplying] = useState(false)
  const [editing, setEditing] = useState(false)
  const [reportOpen, setReportOpen] = useState(false)
  const remove = useDeleteComment(videoId)

  const doDelete = async () => {
    if (!window.confirm(t('engagement.deleteConfirm'))) return
    try {
      await remove.mutateAsync(comment.id)
      toast.success(t('engagement.commentDeleted'))
    } catch (error) {
      toast.error(apiErrorMessage(error))
    }
  }

  // Deleted nodes stay in the tree so their replies keep their context, but the
  // text and the author are gone — the server never sends them.
  if (comment.is_deleted) {
    return (
      <div className={depth > 0 ? 'ml-10' : ''}>
        <p className="py-2 text-xs italic text-ink-500">
          {t('engagement.commentRemoved')}
        </p>
        {comment.replies?.map((reply) => (
          <CommentNode key={reply.id} comment={reply} videoId={videoId} depth={1} />
        ))}
      </div>
    )
  }

  return (
    <div className={depth > 0 ? 'ml-10' : ''}>
      <div className="flex gap-3 py-3">
        <Avatar user={comment.author} size={depth > 0 ? 'sm' : 'md'} />

        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-baseline gap-2">
            <Link
              to={`/c/${comment.author.username}`}
              className="text-sm font-semibold hover:text-brand-300"
            >
              {comment.author.display_name}
            </Link>
            <span className="text-xs text-ink-500">
              {formatRelative(comment.created_at, i18n.language)}
              {comment.updated_at !== comment.created_at && ` (${t('engagement.edited')})`}
            </span>
          </div>

          {editing ? (
            <div className="mt-2">
              <CommentForm
                videoId={videoId}
                editCommentId={comment.id}
                initialValue={comment.content}
                autoFocus
                onDone={() => setEditing(false)}
                onCancel={() => setEditing(false)}
              />
            </div>
          ) : (
            <p className="mt-1 whitespace-pre-line break-words text-sm text-ink-200">
              {comment.content}
            </p>
          )}

          {!editing && (
            <div className="mt-1.5 flex flex-wrap items-center gap-1">
              {depth === 0 && user && (
                <Button variant="ghost" size="sm" onClick={() => setReplying((v) => !v)}>
                  <Reply className="size-3.5" aria-hidden />
                  {t('engagement.reply')}
                </Button>
              )}
              {comment.can_edit && (
                <Button variant="ghost" size="sm" onClick={() => setEditing(true)}>
                  <Pencil className="size-3.5" aria-hidden />
                  {t('common.edit')}
                </Button>
              )}
              {comment.can_delete && (
                <Button variant="ghost" size="sm" onClick={doDelete} loading={remove.isPending}>
                  <Trash2 className="size-3.5 text-red-400" aria-hidden />
                  {t('common.delete')}
                </Button>
              )}
              {user && !comment.can_edit && (
                <Button variant="ghost" size="sm" onClick={() => setReportOpen(true)}>
                  <Flag className="size-3.5" aria-hidden />
                  {t('engagement.report')}
                </Button>
              )}
            </div>
          )}

          {replying && (
            <div className="mt-3">
              <CommentForm
                videoId={videoId}
                parentId={comment.id}
                autoFocus
                onDone={() => setReplying(false)}
                onCancel={() => setReplying(false)}
              />
            </div>
          )}
        </div>
      </div>

      {comment.replies?.map((reply) => (
        <CommentNode key={reply.id} comment={reply} videoId={videoId} depth={1} />
      ))}

      <ReportModal
        open={reportOpen}
        onClose={() => setReportOpen(false)}
        targetType="comment"
        targetId={comment.id}
        targetLabel={comment.content?.slice(0, 80)}
      />
    </div>
  )
}

export default function CommentSection({ videoId, commentCount }) {
  const { t, i18n } = useTranslation()
  const user = useAuthStore((state) => state.user)
  const { data, isLoading, isError, fetchNextPage, hasNextPage, isFetchingNextPage } =
    useComments(videoId)

  const comments = data?.pages.flatMap((page) => page.results) ?? []
  const total = data?.pages[0]?.count ?? commentCount ?? 0

  return (
    <section className="mt-6 rounded-card border border-ink-800 bg-ink-850 p-4">
      <h2 className="mb-4 flex items-center gap-2 text-sm font-semibold">
        <MessageSquare className="size-4 text-brand-400" aria-hidden />
        {formatCount(commentCount ?? total, i18n.language)} {t('common.comments')}
      </h2>

      {user ? (
        <div className="mb-4 border-b border-ink-800 pb-4">
          <CommentForm videoId={videoId} />
        </div>
      ) : (
        <p className="mb-4 rounded-lg border border-ink-700 bg-ink-800 p-3 text-xs text-ink-400">
          <Link to="/login" className="text-brand-300 hover:underline">
            {t('nav.login')}
          </Link>{' '}
          {t('engagement.loginToComment')}
        </p>
      )}

      {isLoading && <LoadingBlock />}
      {isError && (
        <p className="py-6 text-center text-sm text-red-300">{t('common.errorRetry')}</p>
      )}

      {!isLoading && comments.length === 0 && (
        <EmptyState
          icon={MessageSquare}
          title={t('engagement.noComments')}
          description={t('engagement.noCommentsHint')}
          className="border-none py-8"
        />
      )}

      <div className="divide-y divide-ink-800">
        {comments.map((comment) => (
          <CommentNode key={comment.id} comment={comment} videoId={videoId} />
        ))}
      </div>

      {hasNextPage && (
        <div className="mt-4 text-center">
          <Button
            variant="secondary"
            size="sm"
            loading={isFetchingNextPage}
            onClick={() => fetchNextPage()}
          >
            {t('engagement.loadMoreComments')}
          </Button>
        </div>
      )}
    </section>
  )
}
