import { readFileSync } from 'node:fs'
import { defineConfig, type HeadConfig } from 'vitepress'
import { pageFileFor, recordPage, writeLlmsFiles } from './llms.mjs'

// The nav shows the package version from pyproject.toml, so it follows each release.
const pyproject = readFileSync(new URL('../../pyproject.toml', import.meta.url), 'utf8')
const version = pyproject.match(/^version = "([^"]+)"/m)?.[1] ?? 'unknown'

// The production origin. The sitemap, the canonical links, robots.txt and the Markdown surface
// (llms.txt, the page twins) all name pages with it. No trailing slash.
const hostname = 'https://decguard.com'

const repository = 'https://github.com/suffro/decguard'
const description =
  'Reliability testing for probabilistic AI decisions: decision contracts, calibration, ' +
  'metamorphic fuzzing, regression gates and offline production checks.'

// The reading order, declared once: the theme draws it and llms.txt follows it.
const sidebar = [
  {
    text: 'Getting Started',
    items: [
      { text: 'What is DecGuard?', link: '/introduction' },
      { text: 'Installation', link: '/installation' },
      { text: 'Quickstart', link: '/quickstart' },
    ],
  },
  {
    text: 'Core Concepts',
    items: [
      { text: 'Decisions and results', link: '/decisions' },
      { text: 'Golden datasets', link: '/datasets' },
      { text: 'Requirements and warnings', link: '/gates' },
    ],
  },
  {
    text: 'Testing & Reliability',
    items: [
      { text: 'Golden tests and metrics', link: '/metrics' },
      { text: 'Metamorphic properties', link: '/properties' },
      { text: 'Fuzzing and replay', link: '/fuzzing' },
      { text: 'Regression diffs', link: '/regression' },
    ],
  },
  {
    text: 'Production',
    items: [
      { text: 'Production checks', link: '/production' },
      { text: 'Policies and Python SDK', link: '/policy' },
    ],
  },
  {
    text: 'Backends',
    items: [
      { text: 'Overview and mock', link: '/backends' },
      { text: 'System One: Kev and Jev', link: '/systemone' },
      { text: 'Generic HTTP', link: '/http' },
      { text: 'Custom backends', link: '/custom-backends' },
    ],
  },
  {
    text: 'Reference',
    items: [
      { text: 'CLI', link: '/cli' },
      { text: 'Decision Contract', link: '/contracts' },
      { text: 'Reports and formats', link: '/reports' },
    ],
  },
  {
    text: 'CI and Architecture',
    items: [
      { text: 'CI with GitHub Actions', link: '/ci' },
      { text: 'Architecture', link: '/architecture' },
    ],
  },
]

export default defineConfig({
  lang: 'en-US',
  title: 'DecGuard',
  titleTemplate: ':title · DecGuard',
  description,

  // No `base` and no clean-URL rewrites: pages are `/quickstart.html`, and the sitemap lists them so.
  sitemap: { hostname },
  metaChunk: true,

  head: [
    // The mark is black on transparent. The SVG icon turns it white under a dark color scheme, so it
    // stays visible on a dark tab; `/favicon.ico` sits at the root for browsers that read no SVG and
    // probe that exact path.
    ['link', { rel: 'icon', href: '/favicon.ico', sizes: '256x256' }],
    ['link', { rel: 'icon', type: 'image/svg+xml', href: '/static/svg/favicon.svg' }],
    ['meta', { name: 'theme-color', content: '#0e7c66' }],
    ['meta', { property: 'og:type', content: 'website' }],
    ['meta', { property: 'og:site_name', content: 'DecGuard' }],
    ['meta', { property: 'og:title', content: 'DecGuard' }],
    ['meta', { property: 'og:description', content: description }],
    // The same 1280×640 card as the GitHub repository's social preview. Crawlers need an absolute URL.
    ['meta', { property: 'og:image', content: `${hostname}/static/png/social-preview.png` }],
    ['meta', { property: 'og:image:type', content: 'image/png' }],
    ['meta', { property: 'og:image:width', content: '1280' }],
    ['meta', { property: 'og:image:height', content: '640' }],
    ['meta', { property: 'og:image:alt', content: 'DecGuard: reliability testing for probabilistic AI decisions' }],
    ['meta', { name: 'twitter:card', content: 'summary_large_image' }],
    ['meta', { name: 'twitter:title', content: 'DecGuard' }],
    ['meta', { name: 'twitter:description', content: description }],
    ['meta', { name: 'twitter:image', content: `${hostname}/static/png/social-preview.png` }],
  ],

  markdown: {
    theme: { light: 'github-light', dark: 'github-dark' },
  },

  transformPageData(pageData) {
    // Recording the page is what feeds llms.txt and the Markdown twins; see ./llms.mjs.
    recordPage(pageData)

    const head: HeadConfig[] = (pageData.frontmatter.head ??= [])
    head.push(
      // The same URL the sitemap lists, so a preview deployment is never indexed as a second copy.
      ['link', { rel: 'canonical', href: `${hostname}/${pageFileFor(pageData.relativePath)}` }],
      ['meta', { property: 'og:url', content: `${hostname}/${pageFileFor(pageData.relativePath)}` }],
      // The Markdown twin of this page, at its source path. `PageActions.vue` reads this link rather
      // than deriving the path a second time.
      ['link', { rel: 'alternate', type: 'text/markdown', href: `${hostname}/${pageData.relativePath}` }],
    )
  },

  // The Markdown surface, written after the pages are rendered: /llms.txt, /llms-full.txt and one
  // `.md` twin per page. See ./llms.mjs.
  async buildEnd(siteConfig) {
    const written = await writeLlmsFiles({
      outDir: siteConfig.outDir,
      srcDir: siteConfig.srcDir,
      hostname,
      version,
      repository,
      sidebar,
      siteDescription: description,
    })
    console.log(
      `generated llms.txt (${written.indexed} pages, ${Math.round(written.indexBytes / 1024)} kB), ` +
        `llms-full.txt (${Math.round(written.fullBytes / 1024)} kB) ` +
        `and ${written.twins} Markdown page twins`,
    )
  },

  themeConfig: {
    // The dark mark on a light background, the light mark on a dark one.
    logo: {
      light: '/static/svg/logo-dark.svg',
      dark: '/static/svg/logo-light.svg',
      alt: 'DecGuard logo',
    },
    siteTitle: 'DecGuard',

    nav: [
      { text: 'Guide', link: '/quickstart', activeMatch: '^/(introduction|installation|quickstart|decisions|datasets|gates|metrics|properties|fuzzing|regression|production|policy|ci|architecture)' },
      { text: 'Backends', link: '/backends', activeMatch: '^/(backends|systemone|http|custom-backends)' },
      {
        text: 'Reference',
        activeMatch: '^/(cli|contracts|reports)',
        items: [
          { text: 'CLI', link: '/cli' },
          { text: 'Decision Contract', link: '/contracts' },
          { text: 'Reports and formats', link: '/reports' },
        ],
      },
      {
        text: `v${version}`,
        items: [
          { text: 'Changelog', link: `${repository}/blob/main/CHANGELOG.md` },
          { text: 'PyPI', link: 'https://pypi.org/project/decguard/' },
          { text: 'Contributing', link: `${repository}/blob/main/CONTRIBUTING.md` },
        ],
      },
    ],

    sidebar,

    outline: { level: [2, 3], label: 'On this page' },

    search: { provider: 'local' },

    socialLinks: [{ icon: 'github', link: repository }],

    docFooter: { prev: 'Previous', next: 'Next' },

    footer: {
      message: 'Released under the Apache-2.0 License.',
      copyright: 'DecGuard contributors',
    },
  },
})
