import { Compass } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'

import { Button, EmptyState } from '@/components/ui'

export default function NotFoundPage() {
  const { t } = useTranslation()
  const navigate = useNavigate()

  return (
    <div className="mx-auto max-w-xl py-16">
      <EmptyState
        icon={Compass}
        title={t('notFound.title')}
        description={t('notFound.subtitle')}
        action={<Button onClick={() => navigate('/')}>{t('notFound.cta')}</Button>}
      />
    </div>
  )
}
