import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import AppShell from '../components/AppShell.vue'

const LoginView = () => import('../views/LoginView.vue')
const DashboardView = () => import('../views/DashboardView.vue')
const InternetView = () => import('../views/InternetView.vue')
const HomeNetworkView = () => import('../views/HomeNetworkView.vue')
const RulesView = () => import('../views/RulesView.vue')
const VpnView = () => import('../views/VpnView.vue')
const ManagementView = () => import('../views/ManagementView.vue')

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/login', component: LoginView, meta: { public: true } },
    {
      path: '/',
      component: AppShell,
      children: [
        {
          path: '',
          name: 'dashboard',
          component: DashboardView,
          meta: { titleKey: 'nav.dashboard' },
        },
        {
          path: 'internet',
          name: 'internet',
          component: InternetView,
          meta: { titleKey: 'nav.internet' },
        },
        {
          path: 'home-network',
          name: 'home-network',
          component: HomeNetworkView,
          meta: { titleKey: 'nav.home' },
        },
        {
          path: 'rules',
          name: 'rules',
          component: RulesView,
          meta: { titleKey: 'nav.rules' },
        },
        {
          path: 'vpn',
          name: 'vpn',
          component: VpnView,
          meta: { titleKey: 'nav.vpn' },
        },
        {
          path: 'management',
          name: 'management',
          component: ManagementView,
          meta: { titleKey: 'nav.management' },
        },
      ],
    },
    { path: '/:pathMatch(.*)*', redirect: '/' },
  ],
})

router.beforeEach(async (to) => {
  const auth = useAuthStore()
  if (to.meta.public) {
    return true
  }
  if (!auth.user) {
    const ok = await auth.fetchMe()
    if (!ok) {
      return { path: '/login', query: { redirect: to.fullPath } }
    }
  }
  return true
})

export default router
