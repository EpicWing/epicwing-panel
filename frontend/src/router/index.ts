import { createRouter, createWebHistory } from "vue-router";

import { auth } from "../stores/auth";
import AdminOverviewView from "../views/AdminOverviewView.vue";
import AdminServersView from "../views/AdminServersView.vue";
import UsersView from "../views/UsersView.vue";
import EggsView from "../views/EggsView.vue";
import AdminLocationsView from "../views/AdminLocationsView.vue";
import AdminMailView from "../views/AdminMailView.vue";
import LoginView from "../views/LoginView.vue";
import NodeDetailView from "../views/NodeDetailView.vue";
import NodesView from "../views/NodesView.vue";
import ServersView from "../views/ServersView.vue";
import SettingsView from "../views/SettingsView.vue";
import ServerDetailView from "../views/ServerDetailView.vue";

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: "/", name: "servers", component: ServersView, meta: { requiresAuth: true } },
    { path: "/servers/:id", name: "server-detail", component: ServerDetailView, meta: { requiresAuth: true } },
    { path: "/settings", name: "settings", component: SettingsView, meta: { requiresAuth: true } },
    {
      path: "/admin",
      name: "admin",
      component: AdminOverviewView,
      meta: { requiresAuth: true, requiresAdmin: true },
    },
    {
      path: "/admin/nodes",
      name: "nodes",
      component: NodesView,
      meta: { requiresAuth: true, requiresAdmin: true },
    },
    {
      path: "/admin/nodes/:id",
      name: "node-detail",
      component: NodeDetailView,
      meta: { requiresAuth: true, requiresAdmin: true },
    },
    {
      path: "/admin/servers",
      name: "admin-servers",
      component: AdminServersView,
      meta: { requiresAuth: true, requiresAdmin: true },
    },
    {
      path: "/admin/eggs",
      name: "eggs",
      component: EggsView,
      meta: { requiresAuth: true, requiresAdmin: true },
    },
    {
      path: "/admin/mail",
      name: "admin-mail",
      component: AdminMailView,
      meta: { requiresAuth: true, requiresAdmin: true },
    },
    {
      path: "/admin/users",
      name: "admin-users",
      component: UsersView,
      meta: { requiresAuth: true, requiresAdmin: true },
    },
    {
      path: "/admin/locations",
      name: "admin-locations",
      component: AdminLocationsView,
      meta: { requiresAuth: true, requiresAdmin: true },
    },
    { path: "/nodes", redirect: "/admin/nodes" },
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
  if (to.meta.requiresAdmin && !auth.state.user?.is_admin) {
    return { name: "servers" };
  }
  if (to.name === "login" && auth.state.user) {
    return { name: "servers" };
  }
});

export default router;
