<script setup>
import { locale, setLocale } from '../i18n'
</script>

<template>
  <div class="lang-switch">
    <button
      class="btn small"
      :class="{ primary: locale === 'ru' }"
      @click="setLocale('ru')"
    >
      RU
    </button>
    <button
      class="btn small"
      :class="{ primary: locale === 'en' }"
      @click="setLocale('en')"
    >
      EN
    </button>
  </div>
</template>

<style scoped>
.lang-switch {
  display: inline-flex;
  gap: 4px;
}
</style>
