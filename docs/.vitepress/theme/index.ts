import { h } from 'vue'
import type { Theme } from 'vitepress'
import DefaultTheme from 'vitepress/theme'
import HeroTerminal from './HeroTerminal.vue'
import PageActions from './PageActions.vue'
import './custom.css'

export default {
  extends: DefaultTheme,
  Layout() {
    return h(DefaultTheme.Layout, null, {
      'home-hero-image': () => h(HeroTerminal),
      // Every doc page, never the home page: its layout renders no `doc-before` slot.
      'doc-before': () => h(PageActions),
    })
  },
} satisfies Theme
