<template>
  <v-app>
    <v-app-bar color="surface" flat border>
      <v-app-bar-title class="text-body-1 font-weight-bold">歌单订阅 · 组件预览（仅本地开发壳）</v-app-bar-title>
      <template #append>
        <v-btn-toggle v-model="previewWidth" density="comfortable" mandatory variant="outlined" class="mr-3">
          <v-btn :value="380" size="small">窄</v-btn>
          <v-btn :value="760" size="small">中</v-btn>
          <v-btn :value="1180" size="small">宽</v-btn>
        </v-btn-toggle>
        <v-btn
          :prepend-icon="isDark ? 'mdi-weather-night' : 'mdi-weather-sunny'"
          variant="tonal"
          @click="toggleTheme"
        >{{ isDark ? '深色' : '浅色' }}</v-btn>
      </template>
    </v-app-bar>

    <v-main>
      <div class="preview-root">
        <v-tabs v-model="tab" color="primary" class="mb-4">
          <v-tab value="config">配置页 Config</v-tab>
          <v-tab value="page">数据页 Page</v-tab>
        </v-tabs>

        <v-window v-model="tab">
          <v-window-item value="config">
            <div class="preview-frame" :style="frameStyle">
              <config-component :initial-config="mockConfig" :api="api" @save="onSave" @switch="tab = 'page'" @close="onClose" @layout="onLayout" />
            </div>
          </v-window-item>
          <v-window-item value="page">
            <div class="preview-frame" :style="frameStyle">
              <page-component :api="api" :show_switch="true" @switch="tab = 'config'" @close="onClose" />
            </div>
          </v-window-item>
        </v-window>
      </div>
    </v-main>

    <v-snackbar v-model="snackbar.show" :color="snackbar.color" :timeout="2600">{{ snackbar.text }}</v-snackbar>
  </v-app>
</template>

<script setup>
import { computed, reactive, ref } from 'vue'
import { useTheme } from 'vuetify'
import PageComponent from './components/Page.vue'
import ConfigComponent from './components/Config.vue'
import { createMockApi } from './dev/mockApi'

const theme = useTheme()
const api = createMockApi()

const tab = ref('config')
const previewWidth = ref(1180)
const snackbar = reactive({ show: false, text: '', color: 'success' })

const isDark = computed(() => theme.global.current.value.dark)
const frameStyle = computed(() => ({ maxWidth: `${previewWidth.value}px` }))

const mockConfig = {
  enabled: true,
  cron: '0 4 * * *',
  media_server: ['Plex'],
  exact_match: true,
  douban_source: true,
  ncm_api_url: 'http://192.168.1.100:1630',
  wymusic_paths: '123456789:我的收藏\n987654321:午后咖啡',
  wy_daily_list: false,
  wy_daily_song: false,
  qqmusic_paths: '8888888888:QQ 精选',
  qishui_paths: '',
}

function toggleTheme() {
  theme.global.name.value = isDark.value ? 'light' : 'dark'
}
function toast(text, color = 'success') {
  snackbar.text = text
  snackbar.color = color
  snackbar.show = true
}
function onSave(config) {
  console.log('[dev] save config:', config)
  toast('配置已保存（开发壳模拟）')
}
function onClose() { toast('close 事件', 'info') }
function onLayout(layout) { console.log('[dev] layout:', layout) }
</script>

<style scoped>
.preview-root {
  max-width: 1280px;
  margin: 0 auto;
  padding: 20px 16px 60px;
}
.preview-frame {
  margin: 0 auto;
  overflow: hidden;
  border: 1px solid rgba(var(--v-theme-on-surface), 0.12);
  border-radius: 14px;
  background: rgb(var(--v-theme-surface));
  box-shadow: 0 12px 40px rgba(var(--v-theme-on-surface), 0.08);
  transition: max-width 0.25s ease;
}
</style>
