import { useEffect } from 'react'

/**
 * Keep the document head in step with the route.
 *
 * A SPA serves one index.html for every URL, so without this every page shares
 * one title and one description — worthless in a search result, and unreadable
 * in a browser's tab strip or history. Google renders JavaScript, so the tags
 * written here are the ones it indexes. (Social crawlers do *not* run scripts;
 * they are served pre-rendered tags by the backend instead — see apps/seo.)
 *
 * Written directly against the DOM rather than through a helmet library: the
 * whole job is a handful of setAttribute calls, and the tags must be removed
 * again on unmount so a stale og:image does not leak onto the next route.
 */

const MANAGED = 'data-sv-meta'

function upsert(selector, create) {
  let node = document.head.querySelector(selector)
  if (!node) {
    node = create()
    node.setAttribute(MANAGED, '')
    document.head.appendChild(node)
  }
  return node
}

function setMeta(attr, key, content) {
  const selector = `meta[${attr}="${key}"]`
  if (content == null || content === '') {
    document.head.querySelector(`${selector}[${MANAGED}]`)?.remove()
    return
  }
  const node = upsert(selector, () => {
    const el = document.createElement('meta')
    el.setAttribute(attr, key)
    return el
  })
  node.setAttribute('content', content)
}

function setLink(rel, href) {
  const selector = `link[rel="${rel}"]`
  if (!href) {
    document.head.querySelector(`${selector}[${MANAGED}]`)?.remove()
    return
  }
  const node = upsert(selector, () => {
    const el = document.createElement('link')
    el.setAttribute('rel', rel)
    return el
  })
  node.setAttribute('href', href)
}

function setJsonLd(payload) {
  document.head.querySelector('script[data-sv-jsonld]')?.remove()
  if (!payload) return
  const script = document.createElement('script')
  script.type = 'application/ld+json'
  script.setAttribute('data-sv-jsonld', '')
  script.textContent = JSON.stringify(payload)
  document.head.appendChild(script)
}

/**
 * @param {object} meta
 * @param {string}  meta.title        Page title, without the site suffix.
 * @param {string}  [meta.description]
 * @param {string}  [meta.image]      Absolute URL for the social card.
 * @param {string}  [meta.canonical]  Defaults to the current URL, query dropped.
 * @param {string}  [meta.type]       Open Graph type. Defaults to "website".
 * @param {boolean} [meta.noindex]    Set for pages that must not be indexed.
 * @param {object}  [meta.jsonLd]     Structured data for this page.
 */
export function useDocumentMeta({
  title,
  description,
  image,
  canonical,
  type = 'website',
  noindex = false,
  jsonLd,
} = {}) {
  // jsonLd is an object literal in most call sites, so a new reference every
  // render; comparing the serialised form keeps the effect from thrashing.
  const jsonLdKey = jsonLd ? JSON.stringify(jsonLd) : ''

  useEffect(() => {
    const siteName = 'StreamVerse'
    const fullTitle = title ? `${title} — ${siteName}` : siteName
    // Query strings produce a distinct URL per filter combination for the same
    // content; the canonical points at the bare path unless told otherwise.
    const url = canonical || `${window.location.origin}${window.location.pathname}`

    const previousTitle = document.title
    document.title = fullTitle

    setMeta('name', 'description', description)
    setMeta('name', 'robots', noindex ? 'noindex, nofollow' : 'index, follow')
    setLink('canonical', url)

    setMeta('property', 'og:title', fullTitle)
    setMeta('property', 'og:description', description)
    setMeta('property', 'og:type', type)
    setMeta('property', 'og:url', url)
    setMeta('property', 'og:site_name', siteName)
    setMeta('property', 'og:image', image)

    setMeta('name', 'twitter:card', image ? 'summary_large_image' : 'summary')
    setMeta('name', 'twitter:title', fullTitle)
    setMeta('name', 'twitter:description', description)
    setMeta('name', 'twitter:image', image)

    setJsonLd(jsonLdKey ? JSON.parse(jsonLdKey) : null)

    return () => {
      document.title = previousTitle
      // Only tags this hook created are removed; anything hard-coded in
      // index.html is left alone as the fallback for the next route.
      document.head
        .querySelectorAll(`[${MANAGED}], script[data-sv-jsonld]`)
        .forEach((node) => node.remove())
    }
  }, [title, description, image, canonical, type, noindex, jsonLdKey])
}

export default useDocumentMeta
