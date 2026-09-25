import { readFileSync } from 'node:fs'
import { defineConfig, type HeadConfig } from 'vitepress'
import { recordPage, writeLlmsFiles } from './llms.mjs'

// The nav shows the package version from pyproject.toml, so it follows each release.
const pyproject = readFileSync(new URL('../../pyproject.toml', import.meta.url), 'utf8')
const version = pyproject.match(/^version = "([^"]+)"/m)?.[1] ?? 'unknown'

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

  // Hosting-neutral: no `base`, no sitemap hostname and no clean-URL rewrites.
  lastUpdated: true,
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
    ['meta', { name: 'twitter:card', content: 'summary' }],
    ['meta', { name: 'twitter:title', content: 'DecGuard' }],
    ['meta', { name: 'twitter:description', content: description }],
  ],

  markdown: {
    theme: { light: 'github-light', dark: 'github-dark' },
  },

  transformPageData(pageData, { siteConfig }) {
    // Recording the page is what feeds llms.txt and the Markdown twins; see ./llms.mjs.
    recordPage(pageData)

    // The Markdown twin of this page, at its source path. `PageActions.vue` reads this link rather
    // than deriving the path a second time.
    const head: HeadConfig[] = (pageData.frontmatter.head ??= [])
    head.push([
      'link',
      { rel: 'alternate', type: 'text/markdown', href: `${siteConfig.site.base}${pageData.relativePath}` },
    ])
  },

  // The Markdown surface, written after the pages are rendered: /llms.txt, /llms-full.txt and one
  // `.md` twin per page. See ./llms.mjs.
  async buildEnd(siteConfig) {
    const written = await writeLlmsFiles({
      outDir: siteConfig.outDir,
      srcDir: siteConfig.srcDir,
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

    editLink: {
      pattern: `${repository}/edit/main/docs/:path`,
      text: 'Edit this page on GitHub',
    },

    lastUpdated: {
      text: 'Last updated',
      formatOptions: { dateStyle: 'medium' },
    },

    docFooter: { prev: 'Previous', next: 'Next' },

    footer: {
      message: 'Released under the Apache-2.0 License.',
      copyright: 'DecGuard contributors',
    },
  },
})
