import { createRouter, createWebHistory } from 'vue-router'
import Overview from './pages/Overview.vue'
import Subjects from './pages/Subjects.vue'
import SampleDesk from './pages/SampleDesk.vue'
import Packs from './pages/Packs.vue'
import Checklist from './pages/Checklist.vue'
import ReleaseDesk from './pages/ReleaseDesk.vue'
import Settings from './pages/Settings.vue'

export default createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', component: Overview },
    { path: '/subjects', component: Subjects },
    { path: '/sample', component: SampleDesk },
    { path: '/packs', component: Packs },
    { path: '/checklist', component: Checklist },
    { path: '/release', component: ReleaseDesk },
    { path: '/settings', component: Settings },
  ],
})
