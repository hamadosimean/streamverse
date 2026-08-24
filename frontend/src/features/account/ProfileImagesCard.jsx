import { Camera, ImageIcon, Loader2, Trash2 } from 'lucide-react'
import { useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import toast from 'react-hot-toast'

import Avatar from '@/components/Avatar'
import { Button } from '@/components/ui'
import { apiErrorMessage } from '@/lib/api'
import { useAuthStore } from '@/stores/useAuthStore'

// Mirrors of MAX_AVATAR_BYTES / MAX_BANNER_BYTES and ALLOWED_IMAGE_MIME_TYPES
// in the backend settings. Checking here only saves the user an upload they
// were going to lose anyway — the server re-checks by decoding the file, which
// is the check that actually counts.
const LIMITS = {
  avatar: 5 * 1024 * 1024,
  banner: 10 * 1024 * 1024,
}
const ACCEPT = 'image/jpeg,image/png,image/webp,image/gif'

function ImagePicker({ kind, icon: Icon, label, hint, hasImage, children }) {
  const { t } = useTranslation()
  const inputRef = useRef(null)
  const [busy, setBusy] = useState(null) // null | 'upload' | 'remove'
  const { uploadImage, removeImage } = useAuthStore()

  const handleFile = async (event) => {
    const file = event.target.files?.[0]
    // Clearing the input lets the same file be picked again after a failure.
    event.target.value = ''
    if (!file) return

    if (!ACCEPT.split(',').includes(file.type)) {
      toast.error(t('account.imageType'))
      return
    }
    if (file.size > LIMITS[kind]) {
      toast.error(t('account.imageTooLarge', { size: LIMITS[kind] / (1024 * 1024) }))
      return
    }

    setBusy('upload')
    try {
      await uploadImage(kind, file)
      toast.success(t(`account.${kind}Updated`))
    } catch (error) {
      toast.error(apiErrorMessage(error))
    } finally {
      setBusy(null)
    }
  }

  const handleRemove = async () => {
    setBusy('remove')
    try {
      await removeImage(kind)
      toast.success(t(`account.${kind}Removed`))
    } catch (error) {
      toast.error(apiErrorMessage(error))
    } finally {
      setBusy(null)
    }
  }

  return (
    <div>
      <input
        ref={inputRef}
        type="file"
        accept={ACCEPT}
        onChange={handleFile}
        className="sr-only"
        aria-label={label}
      />

      {children({ open: () => inputRef.current?.click(), busy })}

      <div className="mt-3 flex flex-wrap items-center gap-2">
        <Button
          type="button"
          variant="secondary"
          size="sm"
          onClick={() => inputRef.current?.click()}
          loading={busy === 'upload'}
        >
          {busy !== 'upload' && <Icon className="size-4" aria-hidden />}
          {hasImage ? t('account.imageReplace') : t('account.imageAdd')}
        </Button>

        {hasImage && (
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={handleRemove}
            loading={busy === 'remove'}
          >
            {busy !== 'remove' && <Trash2 className="size-4" aria-hidden />}
            {t('common.delete')}
          </Button>
        )}

        <p className="text-xs text-ink-500">{hint}</p>
      </div>
    </div>
  )
}

/**
 * Avatar and banner, shown the way the channel page will show them.
 *
 * The preview is a scaled copy of the real channel header rather than two
 * detached thumbnails: a banner is cropped hard by that layout, and picking one
 * without seeing where the avatar sits on top of it is guesswork.
 */
export default function ProfileImagesCard() {
  const { t } = useTranslation()
  const user = useAuthStore((state) => state.user)

  return (
    <section className="sv-card p-5">
      <h2 className="mb-4 flex items-center gap-2 text-sm font-semibold">
        <ImageIcon className="size-4 text-brand-400" aria-hidden />
        {t('account.images')}
      </h2>

      <ImagePicker
        kind="banner"
        icon={ImageIcon}
        label={t('account.banner')}
        hint={t('account.bannerHint')}
        hasImage={Boolean(user?.banner_url)}
      >
        {({ open, busy }) => (
          <button
            type="button"
            onClick={open}
            className="group relative block w-full overflow-hidden rounded-card border border-ink-800"
            aria-label={t('account.banner')}
          >
            {user?.banner_url ? (
              <img
                src={user.banner_url}
                alt=""
                className="h-28 w-full object-cover sm:h-36"
              />
            ) : (
              <div className="h-28 w-full bg-gradient-to-r from-brand-700/40 via-ink-850 to-accent-500/25 sm:h-36" />
            )}

            <span className="absolute inset-0 grid place-items-center bg-ink-900/60 opacity-0 transition group-hover:opacity-100">
              <Camera className="size-6 text-white" aria-hidden />
            </span>

            {busy === 'upload' && (
              <span className="absolute inset-0 grid place-items-center bg-ink-900/70">
                <Loader2 className="size-6 animate-spin text-white" aria-hidden />
              </span>
            )}
          </button>
        )}
      </ImagePicker>

      <div className="mt-5 border-t border-ink-800 pt-5">
        <ImagePicker
          kind="avatar"
          icon={Camera}
          label={t('account.avatar')}
          hint={t('account.avatarHint')}
          hasImage={Boolean(user?.avatar_url)}
        >
          {({ open, busy }) => (
            <button
              type="button"
              onClick={open}
              className="group relative rounded-full"
              aria-label={t('account.avatar')}
            >
              <Avatar user={user} size="lg" className="border-2 border-ink-700" />
              <span className="absolute inset-0 grid place-items-center rounded-full bg-ink-900/60 opacity-0 transition group-hover:opacity-100">
                <Camera className="size-5 text-white" aria-hidden />
              </span>
              {busy === 'upload' && (
                <span className="absolute inset-0 grid place-items-center rounded-full bg-ink-900/70">
                  <Loader2 className="size-5 animate-spin text-white" aria-hidden />
                </span>
              )}
            </button>
          )}
        </ImagePicker>
      </div>
    </section>
  )
}
