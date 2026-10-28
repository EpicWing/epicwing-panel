import { createRouter, createWebHistory } from "vue-router";

import { auth } from "../stores/auth";
import LoginView from "../views/LoginView.vue";
import NodesView from "../views/NodesView.vue";
import ServersView from "../views/ServersView.vue";

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: "/", name: "servers", component: ServersView, meta: { requiresAuth: true } },
    { path: "/nodes", name: "nodes", component: NodesView, meta: { requiresAuth: true } },
    { path: "/login", name: "login", component: LoginView },
    { path: "/:pathMatch(.*)*", redirect: "/" },
  ],
});

// This is only for convenience, the real check always happens in the backend.
router.beforeEach(async (to) => {
  await auth.init();
  if (to.meta.requiresAuth && !auth.state.user) {
    return { name: "login" };
  }
  if (to.name === "login" && auth.state.user) {
    return { name: "servers" };
  }
});

export default router;
