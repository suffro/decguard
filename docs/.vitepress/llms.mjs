/**
 * Build-time generation of the site's Markdown surface: `/llms.txt`, `/llms-full.txt`, and one
 * Markdown twin per page.
 *
 * A model answering a question about DecGuard fetches two or three URLs, not twenty. These files
 * say what is worth reading, following the convention at https://llmstxt.org: `/llms.txt` is the
 * map (every page, in sidebar order, with its frontmatter description) and `/llms-full.txt` is the
 * same pages' Markdown in one document.
 *
 * Everything is derived from the pages VitePress built and from the sidebar that orders them, so a
 * new page joins by existing. The only hand-written part is the header below.
 *
 * Links are absolute, on the production origin: this text is read somewhere that is not the site.
 * Each twin sits at its source path (`quickstart.md` → `/quickstart.md`), which keeps the relative
 * `.md` links between pages pointing at the neighbouring twins.
 */

import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { dirname, join } from 'node:path'

/** Pages seen by `transformPageData`, keyed by source path. */
const pages = new Map()

/** The home page is a hero and a feature grid, not prose, so it is nobody's reading. */
const HOME = 'index.md'

/** Called for every page during the build. */
export function recordPage(pageData) {
  pages.set(pageData.relativePath, {
    relativePath: pageData.relativePath,
    title: pageData.title || pageData.relativePath,
    description: (pageData.description ?? '').trim(),
  })
}

/** The rendered page for a source path, relative to the site root, as VitePress writes it without
 *  clean URLs and lists it in the sitemap: `quickstart.md` → `quickstart.html`, `index.md` → ``. */
export const pageFileFor = (relativePath) =>
  relativePath.replace(/(^|\/)index\.md$/, '$1').replace(/\.md$/, '.html')

/** Sidebar links are `/quickstart`; recorded pages are `quickstart.md`. */
const sourceOf = (link) => `${link.replace(/^\//, '').replace(/\/$/, '/index') || 'index'}.md`

/** Group the built pages by sidebar section, in sidebar order. Anything the sidebar does not
 *  mention still ships, under `Optional` — the spec's word for "skip this if context is short". */
function group(sidebar) {
  const used = new Set()
  const sections = []

  for (const entry of sidebar) {
    const items = []
    for (const path of sourcesOf(entry)) {
      const page = pages.get(path)
      if (page && !used.has(path)) {
        used.add(path)
        items.push(page)
      }
    }
    if (items.length) sections.push({ title: entry.text, items })
  }

  const rest = [...pages.values()]
    .filter((page) => !used.has(page.relativePath) && page.relativePath !== HOME)
    .sort((a, b) => a.relativePath.localeCompare(b.relativePath))
  if (rest.length) sections.push({ title: 'Optional', items: rest })

  return sections
}

function sourcesOf(node, into = []) {
  if (node.link) into.push(sourceOf(node.link))
  for (const item of node.items ?? []) sourcesOf(item, into)
  return into
}

/** What the project is, said once. The version is threaded in from pyproject.toml. */
function header(version, repository) {
  return [
    '# DecGuard',
    '',
    '> DecGuard tests, verifies and gates probabilistic AI decision models: models that answer a',
    '> typed question (choice, noul or score) and return a probability for every possible answer.',
    '> A YAML Decision Contract and a golden dataset produce one reproducible reliability report',
    '> with PASS / WARN / FAIL gates and CI-friendly exit codes.',
    '',
    `- Version ${version}, contract and report schema 0.1. Python 3.11+, Apache-2.0. Install with \`pip install decguard\`.`,
    '- Commands: `decguard validate`, `test` (with `--all`), `fuzz`, `replay`, `diff`, `report`, `check` and `run`, plus a minimal `DecGuard` Python SDK.',
    '- Measures accuracy, calibration (ECE), confidence coverage, latency and errors; checks metamorphic properties with seeded, minimized, replayable fuzzing; compares baseline and candidate runs; analyzes collected production records offline.',
    '- Backend neutral: offline `mock`, generic `http`, `systemone` (Kev, Jev through OpenRouter) and Python plugins. DecGuard does not serve models and needs no server, database or account.',
    `- Source and issues: ${repository}`,
    '',
  ]
}

/** `/llms.txt` — the index. */
function renderIndex({ hostname, version, repository, sidebar }) {
  const lines = [
    ...header(version, repository),
    `Every page below, concatenated as one document: ${hostname}/llms-full.txt`,
    '',
    'Each link is the page as Markdown; the rendered page is at the same path with `.html` in place of `.md`.',
    '',
  ]

  for (const section of group(sidebar)) {
    lines.push(`## ${section.title}`, '')
    for (const page of section.items) {
      const description = page.description ? `: ${page.description}` : ''
      lines.push(`- [${page.title}](${hostname}/${page.relativePath})${description}`)
    }
    lines.push('')
  }

  return lines.join('\n')
}

/**
 * Reduce a page to what someone would read if the site were a text file: the frontmatter goes,
 * and the status badges become the word they display.
 */
function toPlainMarkdown(source) {
  return source
    .replace(/^---\r?\n[\s\S]*?\r?\n---\r?\n/, '')
    .replace(/<span class="dg-status \w+">([^<]*)<\/span>/g, '$1')
    .replace(/\n{3,}/g, '\n\n')
    .trim()
}

/** `/llms-full.txt` — every page's Markdown, in the index's order, each under its own source. */
async function renderFull({ hostname, version, repository, sidebar, srcDir }) {
  const parts = [
    ...header(version, repository),
    `The complete text of ${hostname}, generated at build time. Index: ${hostname}/llms.txt`,
    '',
  ]

  for (const section of group(sidebar)) {
    for (const page of section.items) {
      const body = toPlainMarkdown(await readFile(join(srcDir, page.relativePath), 'utf8'))
      // Every page opens with its own H1; keep it as the boundary and add where the page lives.
      // No `---` rule between pages: after a line of text it would be a setext heading.
      const [heading, ...rest] = body.startsWith('# ') ? body.split('\n') : [`# ${page.title}`, body]
      parts.push('', heading, '', `Source: ${hostname}/${pageFileFor(page.relativePath)}`, '', rest.join('\n').trim(), '')
    }
  }

  return parts.join('\n')
}

/** YAML is not forgiving of a colon or a quote in an unquoted scalar. */
const yamlString = (value) => `"${value.replace(/\\/g, '\\\\').replace(/"/g, '\\"')}"`

/**
 * One `.md` per page. The home page gets the llms.txt index instead of its hero: the most useful
 * Markdown a landing page can hand an agent is the map of everything behind it.
 */
async function writePageFiles({ outDir, srcDir, hostname, index, siteDescription }) {
  for (const page of pages.values()) {
    const body =
      page.relativePath === HOME
        ? index
        : toPlainMarkdown(await readFile(join(srcDir, page.relativePath), 'utf8'))
    const description = page.description || siteDescription

    const document = [
      '---',
      `title: ${yamlString(page.title)}`,
      ...(description ? [`description: ${yamlString(description)}`] : []),
      `source: ${hostname}/${pageFileFor(page.relativePath)}`,
      '---',
      '',
      body,
      '',
    ].join('\n')

    const file = join(outDir, page.relativePath)
    await mkdir(dirname(file), { recursive: true })
    await writeFile(file, document)
  }

  return pages.size
}

/** Write the generated Markdown surface into the built site. Called from `buildEnd`, so `outDir`
 *  already holds the rendered pages. */
export async function writeLlmsFiles({ outDir, srcDir, hostname, version, repository, sidebar, siteDescription }) {
  const index = renderIndex({ hostname, version, repository, sidebar })
  const full = await renderFull({ hostname, version, repository, sidebar, srcDir })

  await Promise.all([
    writeFile(join(outDir, 'llms.txt'), index),
    writeFile(join(outDir, 'llms-full.txt'), full),
  ])

  const twins = await writePageFiles({ outDir, srcDir, hostname, index, siteDescription })

  return {
    twins,
    indexed: group(sidebar).reduce((total, section) => total + section.items.length, 0),
    indexBytes: Buffer.byteLength(index),
    fullBytes: Buffer.byteLength(full),
  }
}
