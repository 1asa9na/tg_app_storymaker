export interface Member {
  id: number;
  first_name: string;
  username: string | null;
  role: "admin" | "designer" | "writer";
}

export interface TitleSummary {
  slug: string;
  name: string;
  status: "draft" | "published" | "hidden";
  active_version: number | null;
  latest_version: number | null;
  updated_at: string | null;
}

export interface BuildInfo {
  id: number;
  version: number;
  hash: string;
  notes: string;
  warnings: string[];
  created_at: string;
  created_by: string | null;
  active: boolean;
}

export interface TitleDetail {
  slug: string;
  name: string;
  status: TitleSummary["status"];
  documents: Record<string, number>;
  scenes: number;
  builds: BuildInfo[];
}

/** Ошибка API: статус и detail как есть (строка или объект с errors/lost). */
export class StudioError extends Error {
  readonly status: number;
  readonly detail: unknown;

  constructor(status: number, detail: unknown) {
    super(typeof detail === "string" ? detail : `HTTP ${status}`);
    this.status = status;
    this.detail = detail;
  }
}

async function request<T>(method: "GET" | "POST", path: string, body?: unknown): Promise<T> {
  const response = await fetch(`/api/studio${path}`, {
    method,
    credentials: "same-origin",
    headers:
      method === "GET"
        ? {}
        : // X-Studio — защита от CSRF: без него сервер не примет изменяющий запрос
          { "Content-Type": "application/json", "X-Studio": "1" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) {
    let detail: unknown = null;
    try {
      detail = ((await response.json()) as { detail?: unknown }).detail;
    } catch {
      // тело не JSON — хватит статуса
    }
    throw new StudioError(response.status, detail);
  }
  return (await response.json()) as T;
}

export const api = {
  login: (token: string) => request<Member>("POST", "/login", { token }),
  logout: () => request<{ ok: boolean }>("POST", "/logout", {}),
  me: () => request<Member>("GET", "/me"),
  titles: () => request<TitleSummary[]>("GET", "/titles"),
  title: (slug: string) => request<TitleDetail>("GET", `/titles/${slug}`),
  importFiles: (slug: string, files: Record<string, string>) =>
    request<{ slug: string; name: string }>("POST", `/titles/${slug}/import`, { files }),
  build: (slug: string, notes: string) =>
    request<BuildInfo>("POST", `/titles/${slug}/builds`, { notes }),
  publish: (slug: string, buildId: number, force = false) =>
    request<{ active_version: number }>("POST", `/titles/${slug}/publish`, {
      build_id: buildId,
      force,
    }),
  setStatus: (slug: string, status: "published" | "hidden") =>
    request<{ status: string }>("POST", `/titles/${slug}/status`, { status }),
  exportUrl: (slug: string) => `/api/studio/titles/${slug}/export`,
};

/** Файлы из выбранной папки тайтла: путь без имени самой папки → текст. */
export async function readFolder(list: FileList): Promise<Record<string, string>> {
  const files: Record<string, string> = {};
  for (const file of Array.from(list)) {
    const path = (file.webkitRelativePath || file.name).split("/").slice(1).join("/");
    if (/^[^/]+\.ya?ml$/.test(path) || /^scenes\/[^/]+\.ink$/.test(path)) {
      files[path.replace(/\.yml$/, ".yaml")] = await file.text();
    }
  }
  return files;
}

export function problems(error: unknown): string[] {
  if (error instanceof StudioError) {
    const detail = error.detail as { errors?: string[]; lost?: string[] } | string | null;
    if (typeof detail === "string") return [detail];
    if (detail?.errors) return detail.errors;
    if (detail?.lost) return detail.lost.map((key) => `пропадает ${key}`);
    if (error.status === 403) return ["Недостаточно прав для этого действия"];
    return [error.message];
  }
  return ["Нет связи с сервером"];
}
