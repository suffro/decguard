import { readFileSync } from 'node:fs'
import { defineConfig } from 'vitepress'

// The nav shows the package version from pyproject.toml, so it follows each release.
const pyproject = readFileSync(new URL('../../pyproject.toml', import.meta.url), 'utf8')
const version = pyproject.match(/^version = "([^"]+)"/m)?.[1] ?? 'unknown'

const repository = 'https://github.com/suffro/decguard'
const description =
  'Reliability testing for probabilistic AI decisions: decision contracts, calibration, ' +
  'metamorphic fuzzing, regression gates and offline production checks.'

export default defineConfig({
  lang: 'en-US',
  title: 'DecGuard',
  titleTemplate: ':title · DecGuard',
  description,

  // Hosting-neutral: no `base`, no sitemap hostname and no clean-URL rewrites.
  lastUpdated: true,
  metaChunk: true,

  head: [
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

  themeConfig: {
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

    sidebar: [
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
    ],

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
