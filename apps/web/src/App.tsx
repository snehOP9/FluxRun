import {
  createContext,
  lazy,
  Suspense,
  useContext,
  useEffect,
  useState,
  type FormEvent,
} from "react";
import {
  QueryClient,
  QueryClientProvider,
  useQueryClient,
} from "@tanstack/react-query";
import {
  BrowserRouter,
  Link,
  NavLink,
  Route,
  Routes,
  useNavigate,
  useParams,
} from "react-router-dom";
import {
  Activity,
  Box,
  Braces,
  ChevronDown,
  Database,
  FlaskConical,
  KeyRound,
  Layers3,
  LayoutDashboard,
  LogOut,
  Menu,
  Moon,
  Search,
  Settings2,
  Sun,
  Workflow,
} from "lucide-react";
import {
  api,
  ApiError,
  send,
  type User,
  type Workspace,
  type Project,
} from "./api";
import {
  Code,
  Dialog,
  Empty,
  ErrorMessage,
  Loading,
  useResource,
} from "./components/ui";
const Tracking = lazy(() => import("./features/Tracking"));
const Settings = lazy(() => import("./features/Settings"));
const Registry = lazy(() => import("./features/Registry"));
const Traces = lazy(() => import("./features/Traces"));
const Evaluations = lazy(() => import("./features/Evaluations"));
const Reviews = lazy(() => import("./features/Reviews"));
const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, staleTime: 2000 } },
});
type Context = { project: Project; workspace: Workspace; base: string };
const ProjectContext = createContext<Context | null>(null);
export function useProject() {
  const value = useContext(ProjectContext);
  if (!value) throw new Error("Project context missing");
  return value;
}

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Authentication />
      </BrowserRouter>
    </QueryClientProvider>
  );
}
function Authentication() {
  const cache = useQueryClient();
  const user = useResource<User>("/auth/me");
  if (user.isPending) return <Loading />;
  if (user.error) {
    if (user.error instanceof ApiError && user.error.status === 401)
      return <SignIn onSuccess={() => cache.invalidateQueries()} />;
    return (
      <main className="signin">
        <ErrorMessage error={user.error} />
        <button onClick={() => user.refetch()}>Retry connection</button>
      </main>
    );
  }
  return (
    <Routes>
      <Route
        path="/w/:workspaceId/p/:projectId/*"
        element={<Shell user={user.data!} />}
      />
      <Route path="*" element={<ChooseProject />} />
    </Routes>
  );
}
function SignIn({ onSuccess }: { onSuccess: () => void }) {
  const [signup, setSignup] = useState(false);
  const [error, setError] = useState<unknown>();
  const [busy, setBusy] = useState(false);
  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const d = new FormData(e.currentTarget);
    setBusy(true);
    setError(null);
    try {
      await send("/auth/" + (signup ? "signup" : "login"), {
        email: d.get("email"),
        password: d.get("password"),
        ...(signup ? { display_name: d.get("display_name") } : {}),
      });
      onSuccess();
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }
  return (
    <main className="signin">
      <section>
        <div className="brand">
          <span className="brand-mark">
            <Workflow size={20} />
          </span>
          FluxRun
        </div>
        <h1>{signup ? "Create your account" : "Sign in to your workspace"}</h1>
        <p className="muted">
          Experiment tracking and AI engineering evidence.
        </p>
        <form onSubmit={submit}>
          {signup && (
            <label>
              Your name
              <input
                name="display_name"
                autoComplete="name"
                minLength={2}
                required
              />
            </label>
          )}
          <label>
            Email
            <input name="email" type="email" autoComplete="email" required />
          </label>
          <label>
            Password
            <input
              name="password"
              type="password"
              minLength={12}
              autoComplete={signup ? "new-password" : "current-password"}
              required
              aria-describedby="password-note"
            />
          </label>
          <small id="password-note">At least 12 characters.</small>
          <ErrorMessage error={error} />
          <button disabled={busy}>
            {busy ? "Connecting…" : signup ? "Create account" : "Sign in"}
          </button>
        </form>
        <button
          className="text-button"
          onClick={() => {
            setSignup(!signup);
            setError(null);
          }}
        >
          {signup
            ? "Already have an account? Sign in"
            : "New here? Create an account"}
        </button>
        <p className="signin-foot">
          Self-hosted · Your data, your infrastructure
        </p>
      </section>
    </main>
  );
}
function ChooseProject() {
  const navigate = useNavigate();
  const spaces = useResource<Workspace[]>("/workspaces");
  const [first, setFirst] = useState("");
  const [error, setError] = useState<unknown>();
  const projects = useResource<Project[]>(
    first ? `/workspaces/${first}/projects` : "",
  );
  useEffect(() => {
    if (spaces.data?.length && !first) setFirst(spaces.data[0].id);
  }, [spaces.data, first]);
  useEffect(() => {
    if (projects.data?.length)
      navigate(`/w/${first}/p/${projects.data[0].id}/overview`, {
        replace: true,
      });
  }, [projects.data, first, navigate]);
  async function create(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const d = new FormData(e.currentTarget);
    try {
      let id = first;
      if (!id) {
        const w = await send<Workspace>("/workspaces", {
          name: d.get("workspace"),
          slug: "workspace-" + Date.now(),
        });
        id = w.id;
      }
      const p = await send<Project>(`/workspaces/${id}/projects`, {
        name: d.get("project"),
        slug: "project-" + Date.now(),
      });
      navigate(`/w/${id}/p/${p.id}/overview`);
    } catch (e) {
      setError(e);
    }
  }
  if (spaces.isPending || projects.isFetching) return <Loading />;
  return (
    <main className="onboarding">
      <div className="brand">
        <Workflow />
        FluxRun
      </div>
      <h1>Create an engineering workspace</h1>
      <p>Projects keep experiments, models, prompts and traces together.</p>
      <form onSubmit={create}>
        {!first && (
          <label>
            Workspace name
            <input name="workspace" required minLength={2} />
          </label>
        )}
        <label>
          Project name
          <input name="project" required minLength={2} />
        </label>
        <ErrorMessage error={error} />
        <button>Create project</button>
      </form>
    </main>
  );
}
const nav = [
  ["overview", "Overview", LayoutDashboard],
  ["experiments", "Experiments", FlaskConical],
  ["runs", "Runs", Activity],
  ["models", "Models", Box],
  ["datasets", "Datasets", Database],
  ["prompts", "Prompts", Braces],
  ["traces", "Traces", Workflow],
  ["evaluations", "Evaluations", FlaskConical],
  ["reviews", "Reviews", KeyRound],
  ["settings", "Settings", Settings2],
] as const;
function Shell({ user }: { user: User }) {
  const { workspaceId, projectId } = useParams();
  const navigate = useNavigate();
  const cache = useQueryClient();
  const spaces = useResource<Workspace[]>("/workspaces");
  const projects = useResource<Project[]>(
    `/workspaces/${workspaceId}/projects`,
  );
  const summary = useResource<{ project: Project }>(
    `/projects/${projectId}/summary`,
  );
  const [palette, setPalette] = useState(false);
  const [menu, setMenu] = useState(false);
  const [create, setCreate] = useState(false);
  const [error, setError] = useState<unknown>();
  const [theme, setTheme] = useState(
    localStorage.getItem("fluxrun-theme") || "dark",
  );
  const [search, setSearch] = useState("");
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem("fluxrun-theme", theme);
  }, [theme]);
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === "k") {
        e.preventDefault();
        setPalette((v) => !v);
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, []);
  const workspace = spaces.data?.find((w) => w.id === workspaceId);
  const project = summary.data?.project;
  const base = `/w/${workspaceId}/p/${projectId}`;
  if (summary.isPending) return <Loading />;
  if (!project || !workspace)
    return (
      <main className="onboarding">
        <ErrorMessage
          error={summary.error || "Workspace or project unavailable"}
        />
        <Link to="/">Choose another project</Link>
      </main>
    );
  async function switchWorkspace(id: string) {
    try {
      const ps = await api<Project[]>(`/workspaces/${id}/projects`);
      navigate(ps.length ? `/w/${id}/p/${ps[0].id}/overview` : "/");
    } catch (e) {
      setError(e);
    }
  }
  async function newProject(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const d = new FormData(e.currentTarget);
    try {
      const p = await send<Project>(`/workspaces/${workspaceId}/projects`, {
        name: d.get("name"),
        slug: d.get("slug"),
      });
      await cache.invalidateQueries();
      setCreate(false);
      navigate(`/w/${workspaceId}/p/${p.id}/overview`);
    } catch (e) {
      setError(e);
    }
  }
  return (
    <ProjectContext.Provider value={{ project, workspace, base }}>
      <div className="app-shell">
        <aside className={menu ? "sidebar open" : "sidebar"}>
          <Link className="brand" to={`${base}/overview`}>
            <span className="brand-mark">
              <Workflow size={19} />
            </span>
            FluxRun<span className="version">0.4</span>
          </Link>
          <label className="context-label">
            Workspace
            <select
              value={workspaceId}
              onChange={(e) => void switchWorkspace(e.target.value)}
            >
              {spaces.data?.map((w) => (
                <option key={w.id} value={w.id}>
                  {w.name}
                </option>
              ))}
            </select>
          </label>
          <p className="nav-label">BUILD & OBSERVE</p>
          <nav>
            {nav.map(([path, label, Icon]) => (
              <NavLink
                key={path}
                to={`${base}/${path}`}
                onClick={() => setMenu(false)}
              >
                <Icon size={17} />
                {label}
              </NavLink>
            ))}
          </nav>
          <div className="sidebar-bottom">
            <span className="local-indicator" />
            Local instance
            <button
              className="icon-button"
              aria-label="Toggle color theme"
              onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
            >
              {theme === "dark" ? <Sun size={16} /> : <Moon size={16} />}
            </button>
          </div>
        </aside>
        <div className="workspace">
          <header className="topbar">
            <button
              className="icon-button mobile-menu"
              aria-label="Toggle navigation"
              onClick={() => setMenu(!menu)}
            >
              <Menu size={18} />
            </button>
            <Layers3 size={17} />
            <select
              aria-label="Project"
              value={projectId}
              onChange={(e) =>
                navigate(`/w/${workspaceId}/p/${e.target.value}/overview`)
              }
            >
              {projects.data?.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
            <button className="quiet small" onClick={() => setCreate(true)}>
              + Project
            </button>
            {project.settings?.demo === true && (
              <span className="demo-label">DEMO</span>
            )}
            <div className="topbar-end">
              <button
                className="command-trigger quiet"
                onClick={() => setPalette(true)}
              >
                <Search size={14} />
                <span>Find anything</span>
                <kbd>Ctrl K</kbd>
              </button>
              <span className="avatar" title={user.email}>
                {user.display_name[0]}
              </span>
              <button
                className="icon-button"
                aria-label="Sign out"
                onClick={async () => {
                  await send("/auth/logout");
                  cache.clear();
                  navigate("/");
                  window.location.reload();
                }}
              >
                <LogOut size={16} />
              </button>
            </div>
          </header>
          <main className="main-content" id="main">
            <ErrorMessage error={error} />
            <Suspense fallback={<Loading />}>
              <Routes>
                <Route path="models/:id?" element={<Registry kind="model" />} />
                <Route path="datasets/:id?" element={<Registry kind="dataset" />} />
                <Route path="prompts/:id?" element={<Registry kind="prompt" />} />
                <Route path="eval-datasets/:id?" element={<Registry kind="evaluation_dataset" />} />
                <Route path="traces/:id?" element={<Traces />} />
                <Route path="evaluations/:id?" element={<Evaluations />} />
                <Route path="reviews/:id?" element={<Reviews />} />
                <Route path="settings/*" element={<Settings />} />
                <Route path="*" element={<Tracking />} />
              </Routes>
            </Suspense>
          </main>
          <footer className="app-footer">
            <span>FluxRun · Engineering evidence</span>
            <a
              href="http://localhost:8000/docs"
              target="_blank"
              rel="noreferrer"
            >
              API reference ↗
            </a>
          </footer>
        </div>
      </div>
      <Dialog
        title="Create project"
        open={create}
        onClose={() => setCreate(false)}
      >
        <form onSubmit={newProject}>
          <label>
            Name
            <input name="name" required minLength={2} />
          </label>
          <label>
            Slug
            <input name="slug" required pattern="[a-z0-9]+(-[a-z0-9]+)*" />
          </label>
          <ErrorMessage error={error} />
          <button>Create project</button>
        </form>
      </Dialog>
      <Dialog title="Go to…" open={palette} onClose={() => setPalette(false)}>
        <input
          aria-label="Search navigation"
          placeholder="Experiments, runs, settings…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <nav className="command-list">
          {nav
            .filter((n) => n[1].toLowerCase().includes(search.toLowerCase()))
            .map(([path, label, Icon]) => (
              <Link
                to={`${base}/${path}`}
                key={path}
                onClick={() => setPalette(false)}
              >
                <Icon size={16} />
                {label}
              </Link>
            ))}
        </nav>
      </Dialog>
    </ProjectContext.Provider>
  );
}
