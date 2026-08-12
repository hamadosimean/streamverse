import { useTranslation } from 'react-i18next'

import logoUrl from '@/assets/images/logo.png'
import { cn } from '@/lib/cn'

/**
 * The StreamVerse mark.
 *
 * One component rather than the image repeated per screen, so the header, the
 * auth card and anything added later cannot drift apart.
 *
 * The PNG is transparent and pre-cropped to the artwork, which matters on two
 * counts: the source shipped the mark on an opaque near-black plate that would
 * read as a slightly-wrong dark square against the header, and it was mostly
 * padding — at 36px that padding is most of the logo.
 */
export default function Logo({ size = 36, withWordmark = false, className }) {
  const { t } = useTranslation()

  return (
    <span className={cn('flex shrink-0 items-center gap-2', className)}>
      <img
        src={logoUrl}
        alt={withWordmark ? '' : t('app.name')}
        // The wordmark beside it already names the product; repeating it in alt
        // makes a screen reader say "StreamVerse StreamVerse".
        aria-hidden={withWordmark || undefined}
        width={size}
        height={size}
        // Explicit dimensions rather than CSS-only sizing: the header would
        // otherwise reflow once the image decodes.
        style={{ width: size, height: size }}
        className="object-contain"
        // The logo is above the fold on every route, so it must not be lazy.
        loading="eager"
        decoding="async"
        draggable={false}
      />
      {withWordmark && (
        <span className="text-lg font-bold tracking-tight">{t('app.name')}</span>
      )}
    </span>
  )
}
