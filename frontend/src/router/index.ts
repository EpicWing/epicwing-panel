import { createRouter, createWebHistory } from "vue-router";

import { auth } from "../stores/auth";
import DashboardView from "../views/DashboardView.vue";
import LoginView from "../views/LoginView.vue";
import NodesView from "../views/NodesView.vue";

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: "/", name: "dashboard", component: DashboardView, meta: { requiresAuth: true } },
    { path: "/nodes", name: "nodes", component: NodesView, meta: { requiresAuth: true } },
    { path: "/login", name: "login", component: LoginView },
    { path: "/:pathMatch(.*)*", redirect: "/" },
  ],
});

// Das ist nur Komfort, die eigentliche Prüfung passiert immer im Backend.
router.beforeEach(async (to) => {
  await auth.init();
  if (to.meta.requiresAuth && !auth.state.user) {
    return { name: "login" };
  }
  if (to.name === "login" && auth.state.user) {
    return { name: "dashboard" };
  }
});

export default router;
