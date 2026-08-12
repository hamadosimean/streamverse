import i18n from 'i18next'
import { initReactI18next } from 'react-i18next'

import en from '@/locales/en.json'
import fr from '@/locales/fr.json'

/**
 * Translation lives entirely here — the API returns canonical labels and stable
 * slugs, never parallel `*_fr` / `*_en` columns. `categoryLabel` below is the
 * bridge: it looks a category up by slug and falls back to the server's label so
 * a category added by an admin still renders without a code change.
 */
const stored = (() => {
  try {
    return JSON.parse(localStorage.getItem('sv.ui') || '{}')?.state?.language
  } catch {
    return null
  }
})()

i18n.use(initReactI18next).init({
  resources: {
    fr: { translation: fr },
    en: { translation: en },
  },
  lng: stored || 'fr', // French is the default
  fallbackLng: 'fr',
  interpolation: { escapeValue: false },
  returnNull: false,
})

export function setLanguage(language) {
  i18n.changeLanguage(language)
  document.documentElement.lang = language
}

/** Localised category name, with the server-provided label as fallback. */
export function categoryLabel(category, t) {
  if (!category) return null
  const key = `catalog.category.${category.slug}`
  const translated = t(key)
  return translated === key ? category.name : translated
}

export default i18n
