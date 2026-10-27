import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import federation from '@originjs/vite-plugin-federation'

// 构建联邦产物时剥离 Vuetify 的 .v-* / .mdi-* 规则（宿主已提供 Vuetify 样式，避免重复打包）。
// dev serve 无宿主，需要完整 Vuetify 样式，否则开关 / 输入框等结构样式缺失。
const vuetifyFilter = {
  postcssPlugin: 'vuetify-filter',
  Root(root) {
    root.walkRules(rule => {
      if (rule.selector && (rule.selector.includes('.v-') || rule.selector.includes('.mdi-'))) {
        rule.remove()
      }
    })
  },
}

export default defineConfig(({ command }) => ({
  plugins: [
    vue(),
    federation({
      name: 'MusicSubscribe',
      filename: 'remoteEntry.js',
      exposes: {
        './Page': './src/components/Page.vue',
        './Config': './src/components/Config.vue',
      },
      shared: {
        vue: {
          requiredVersion: false,
          generate: false,
        },
        vuetify: {
          requiredVersion: false,
          generate: false,
          singleton: true,
        },
        'vuetify/styles': {
          requiredVersion: false,
          generate: false,
          singleton: true,
        },
      },
      format: 'esm',
    }),
  ],
  build: {
    target: 'esnext',   // 必须设置为 esnext 以支持顶层 await
    minify: false,      // 关闭混淆，便于排错与审查
    cssCodeSplit: true,
  },
  css: {
    postcss: {
      plugins: [
        {
          postcssPlugin: 'internal:charset-removal',
          AtRule: {
            charset: (atRule) => {
              if (atRule.name === 'charset') {
                atRule.remove()
              }
            },
          },
        },
        // 仅构建时剥离 Vuetify CSS；dev serve 保留完整样式以便本地预览
        ...(command === 'build' ? [vuetifyFilter] : []),
      ],
    },
  },
  server: {
    port: 5101,
    cors: true,
    origin: 'http://localhost:5101',
  },
}))
