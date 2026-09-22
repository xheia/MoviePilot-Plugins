import { createApp } from 'vue'
import App from './App.vue'
import { createVuetify } from 'vuetify'
import * as components from 'vuetify/components'
import * as directives from 'vuetify/directives'
import defaults from './vuetify/defaults'
import theme from './vuetify/theme'
import 'vuetify/styles'

// 仅本地开发壳使用的 Vuetify 实例；宿主运行时由宿主提供 Vuetify（shared: generate: false）
const vuetify = createVuetify({
  components,
  directives,
  theme,
  defaults,
})

createApp(App).use(vuetify).mount('#app')
