import { createRouter, createWebHistory } from "vue-router";

import { auth } from "../stores/auth";
import LoginView from "../views/LoginView.vue";
import ServersView from "../views/ServersView.vue";

const AdminOverviewView = () => import("../views/AdminOverviewView.vue");
const AdminServersView = () => import("../views/AdminServersView.vue");
const UsersView = () => import("../views/UsersView.vue");
const EggsView = () => import("../views/EggsView.vue");
const AdminLocationsView = () => import("../views/AdminLocationsView.vue");
const AdminNotificationsView = () => import("../views/AdminNotificationsView.vue");
const NodeDetailView = () => import("../views/NodeDetailView.vue");
const NodesView = () => import("../views/NodesView.vue");
const SettingsView = () => import("../views/SettingsView.vue");
const ServerDetailView = () => import("../views/ServerDetailView.vue");
const AdminDatabasesView = () => import("../views/AdminDatabasesView.vue");

const ApiKeysView = () => import("../views/ApiKeysView.vue");
const SshKeysView = () => import("../views/SshKeysView.vue");

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: "/", name: "servers", component: ServersView, meta: { requiresAuth: true } },
    { path: "/servers/:id", name: "server-detail", component: ServerDetailView, meta: { requiresAuth: true } },
    { path: "/settings", name: "settings", component: SettingsView, meta: { requiresAuth: true } },
    { path: "/api-keys", name: "api-keys", component: ApiKeysView, meta: { requiresAuth: true } },
    { path: "/ssh-keys", name: "ssh-keys", component: SshKeysView, meta: { requiresAuth: true } },
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
      path: "/admin/notifications",
      name: "admin-mail",
      component: AdminNotificationsView,
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
    {
      path: "/admin/databases",
      name: "admin-databases",
      component: AdminDatabasesView,
      meta: { requiresAuth: true, requiresAdmin: true },
    },
    { path: "/nodes", redirect: "/admin/nodes" },
    { path: "/admin/mail", redirect: "/admin/notifications" },
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
