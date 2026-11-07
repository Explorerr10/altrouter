import { ref } from 'vue'
import en from './en'
import ru from './ru'

const dicts = { ru, en }

const saved = typeof localStorage === 'undefined' ? null : localStorage.getItem('locale')
export const locale = ref(saved === 'en' ? 'en' : 'ru')

export function setLocale(value) {
  locale.value = value
  if (typeof localStorage !== 'undefined') {
    localStorage.setItem('locale', value)
  }
}

export function t(key, vars) {
  let text = dicts[locale.value][key] ?? ru[key] ?? key
  if (vars) {
    for (const [name, value] of Object.entries(vars)) {
      text = text.replaceAll(`{${name}}`, value)
    }
  }
  return text
}
