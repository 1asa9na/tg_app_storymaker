import { useCallback, useEffect, useState, type ReactNode } from "react";

import {
  api,
  type AssetList,
  problems,
  readFolder,
  StudioError,
  type Member,
  type TitleDetail,
  type TitleSummary,
} from "./api";

type Route = { page: "titles" } | { page: "title"; slug: string } | { page: "login" };

function parseRoute(): Route {
  const path = window.location.pathname;
  if (path === "/login") return { page: "login" };
  const match = /^\/t\/([a-z][a-z0-9_]*)$/.exec(path);
  return match ? { page: "title", slug: match[1]! } : { page: "titles" };
}

function navigate(path: string) {
  window.history.pushState(null, "", path);
  window.dispatchEvent(new PopStateEvent("popstate"));
}

const STATUS: Record<TitleSummary["status"], string> = {
  draft: "черновик",
  published: "опубликован",
  hidden: "скрыт",
};

const ROLES: Record<Member["role"], string> = {
  admin: "администратор",
  designer: "геймдизайнер",
  writer: "сценарист",
};

export function App() {
  const [route, setRoute] = useState<Route>(parseRoute);
  const [member, setMember] = useState<Member | null | undefined>(undefined);

  useEffect(() => {
    const onPop = () => setRoute(parseRoute());
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  useEffect(() => {
    if (route.page === "login") return;
    api.me().then(setMember, () => setMember(null));
  }, [route.page]);

  if (route.page === "login") {
    return <Login onDone={(m) => (setMember(m), navigate("/"))} />;
  }
  if (member === undefined) return <Shell>Загружаем…</Shell>;
  if (member === null) {
    return (
      <Shell>
        <h1>StoryMaker Studio</h1>
        <p>
          Чтобы войти, отправьте боту команду <code>/studio</code> и откройте ссылку из ответа.
        </p>
        <p className="muted">Студия доступна только команде.</p>
      </Shell>
    );
  }
  return (
    <Shell member={member} onLogout={() => api.logout().finally(() => setMember(null))}>
      {route.page === "titles" && <Titles member={member} />}
      {route.page === "title" && <Title slug={route.slug} member={member} />}
    </Shell>
  );
}

function Shell({
  children,
  member,
  onLogout,
}: {
  children: ReactNode;
  member?: Member;
  onLogout?(): void;
}) {
  return (
    <div className="shell">
      <header className="top">
        <a href="/" onClick={(e) => (e.preventDefault(), navigate("/"))}>
          StoryMaker Studio
        </a>
        {member && (
          <span className="who">
            {member.first_name} · {ROLES[member.role]}
            <button type="button" className="link" onClick={onLogout}>
              Выйти
            </button>
          </span>
        )}
      </header>
      <main>{children}</main>
    </div>
  );
}

// Токен одноразовый, а StrictMode запускает эффект дважды: второй вход был бы ошибкой.
const attempted = new Set<string>();

function Login({ onDone }: { onDone(member: Member): void }) {
  // Токен — во фрагменте URL: он не уходит на сервер с загрузкой страницы и не попадает в логи.
  const [token] = useState(() => window.location.hash.slice(1));
  const [error, setError] = useState<string | null>(
    token ? null : "В ссылке нет токена. Отправьте боту /studio ещё раз.",
  );

  useEffect(() => {
    window.history.replaceState(null, "", "/login");
    if (!token || attempted.has(token)) return;
    attempted.add(token);
    api.login(token).then(onDone, (e: unknown) => setError(problems(e)[0] ?? "Не удалось войти"));
    // Вход один раз при открытии ссылки.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <Shell>
      <h1>Вход в студию</h1>
      <p className={error ? "error" : "muted"}>{error ?? "Проверяем ссылку…"}</p>
    </Shell>
  );
}

const canEdit = (member: Member) => member.role === "admin" || member.role === "designer";

function Titles({ member }: { member: Member }) {
  const [titles, setTitles] = useState<TitleSummary[] | null>(null);
  const [slug, setSlug] = useState("");
  const [errors, setErrors] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.titles().then(setTitles, () => setTitles([]));
  }, []);

  const create = async (list: FileList | null) => {
    if (!list || !slug) return;
    setBusy(true);
    setErrors([]);
    try {
      const files = await readFolder(list);
      await api.importFiles(slug, files);
      navigate(`/t/${slug}`);
    } catch (error) {
      setErrors(problems(error));
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <h1>Тайтлы</h1>
      {titles === null ? (
        <p className="muted">Загружаем…</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>Тайтл</th>
              <th>Статус</th>
              <th>У игроков</th>
              <th>Последняя сборка</th>
            </tr>
          </thead>
          <tbody>
            {titles.map((title) => (
              <tr key={title.slug}>
                <td>
                  <a
                    href={`/t/${title.slug}`}
                    onClick={(e) => (e.preventDefault(), navigate(`/t/${title.slug}`))}
                  >
                    {title.name}
                  </a>
                  <div className="muted small">{title.slug}</div>
                </td>
                <td>{STATUS[title.status]}</td>
                <td>{title.active_version ? `версия ${title.active_version}` : "—"}</td>
                <td>{title.latest_version ? `версия ${title.latest_version}` : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {canEdit(member) && (
        <section className="card">
          <h2>Новый тайтл из папки</h2>
          <p className="muted">
            Папка в формате геймдизайнера: title.yaml, остальные разделы и scenes/*.ink — см.
            docs/TITLE_FORMAT.md.
          </p>
          <label>
            Ключ тайтла (латиницей, навсегда)
            <input
              value={slug}
              placeholder="summer_camp"
              pattern="[a-z][a-z0-9_]*"
              onChange={(e) => setSlug(e.target.value.trim())}
            />
          </label>
          <FolderInput disabled={busy || !/^[a-z][a-z0-9_]*$/.test(slug)} onPick={create}>
            Выбрать папку и импортировать
          </FolderInput>
          <Problems items={errors} />
        </section>
      )}
    </>
  );
}

function FolderInput({
  children,
  disabled,
  onPick,
}: {
  children: ReactNode;
  disabled?: boolean;
  onPick(files: FileList | null): void;
}) {
  return (
    <label className={disabled ? "button disabled" : "button"}>
      {children}
      <input
        type="file"
        hidden
        disabled={disabled}
        // Выбор папки целиком: в атрибутах React нет webkitdirectory
        ref={(input) => input?.setAttribute("webkitdirectory", "")}
        multiple
        onChange={(e) => {
          onPick(e.target.files);
          e.target.value = "";
        }}
      />
    </label>
  );
}

function Problems({ items, kind = "error" }: { items: string[]; kind?: "error" | "warning" }) {
  if (!items.length) return null;
  return (
    <ul className={`problems ${kind}`}>
      {items.map((item) => (
        <li key={item}>{item}</li>
      ))}
    </ul>
  );
}

function Title({ slug, member }: { slug: string; member: Member }) {
  const [title, setTitle] = useState<TitleDetail | null>(null);
  const [missing, setMissing] = useState(false);
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [errors, setErrors] = useState<string[]>([]);
  const [warnings, setWarnings] = useState<string[]>([]);
  const [lost, setLost] = useState<{ buildId: number; keys: string[] } | null>(null);
  const [reload, setReload] = useState(0);

  useEffect(() => {
    api.title(slug).then(setTitle, (e: unknown) => {
      if (e instanceof StudioError && e.status === 404) setMissing(true);
    });
  }, [slug, reload]);

  const run = useCallback(async (work: () => Promise<string | void>) => {
    setBusy(true);
    setMessage(null);
    setErrors([]);
    setWarnings([]);
    setLost(null);
    try {
      const text = await work();
      if (text) setMessage(text);
      setReload((n) => n + 1);
    } catch (error) {
      const detail =
        error instanceof StudioError ? (error.detail as { warnings?: string[] }) : null;
      setErrors(problems(error));
      if (detail?.warnings) setWarnings(detail.warnings);
    } finally {
      setBusy(false);
    }
  }, []);

  const publish = (buildId: number, force = false) =>
    run(async () => {
      try {
        const result = await api.publish(slug, buildId, force);
        return `У игроков теперь версия ${result.active_version}`;
      } catch (error) {
        const detail = error instanceof StudioError ? (error.detail as { lost?: string[] }) : null;
        if (detail?.lost) {
          setLost({ buildId, keys: detail.lost });
          return;
        }
        throw error;
      }
    });

  if (missing) return <p>Тайтла «{slug}» нет.</p>;
  if (!title) return <p className="muted">Загружаем…</p>;
  const editor = canEdit(member);
  const docs = Object.entries(title.documents)
    .map(([kind, count]) => `${kind}: ${count}`)
    .join(" · ");

  return (
    <>
      <h1>{title.name}</h1>
      <p className="muted">
        {title.slug} · {STATUS[title.status]} · {docs || "данных нет"} · сцен: {title.scenes}
      </p>

      <div className="actions">
        {editor && (
          <FolderInput
            disabled={busy}
            onPick={(list) =>
              list &&
              run(async () => {
                const files = await readFolder(list);
                await api.importFiles(slug, files);
                return `Импортировано файлов: ${Object.keys(files).length}. Соберите, чтобы проверить.`;
              })
            }
          >
            Импортировать папку
          </FolderInput>
        )}
        <a className="button secondary" href={api.exportUrl(slug)}>
          Скачать архивом
        </a>
        {editor && title.status === "published" && (
          <button
            type="button"
            className="secondary"
            disabled={busy}
            onClick={() => run(() => api.setStatus(slug, "hidden").then(() => "Тайтл скрыт"))}
          >
            Скрыть из каталога
          </button>
        )}
        {editor && title.status === "hidden" && (
          <button
            type="button"
            className="secondary"
            disabled={busy}
            onClick={() =>
              run(() => api.setStatus(slug, "published").then(() => "Тайтл снова в каталоге"))
            }
          >
            Вернуть в каталог
          </button>
        )}
      </div>

      {editor && (
        <section className="card">
          <h2>Сборка</h2>
          <p className="muted">
            Проверяет данные, ссылки и сцены. Игроки получат сборку только после публикации.
          </p>
          <label>
            Что изменилось
            <input value={notes} onChange={(e) => setNotes(e.target.value)} />
          </label>
          <button
            type="button"
            disabled={busy}
            onClick={() =>
              run(async () => {
                const build = await api.build(slug, notes);
                setNotes("");
                setWarnings(build.warnings);
                return `Собрана версия ${build.version}`;
              })
            }
          >
            {busy ? "Работаем…" : "Собрать"}
          </button>
        </section>
      )}

      {message && <p className="ok">{message}</p>}
      <Problems items={errors} />
      <Problems items={warnings} kind="warning" />
      {lost && (
        <div className="card danger">
          <p>
            Новая сборка теряет ключи, на которые могут ссылаться сохранения игроков. Верните их в
            данные или опубликуйте принудительно (только администратор):
          </p>
          <Problems items={lost.keys} />
          {member.role === "admin" && (
            <button type="button" onClick={() => publish(lost.buildId, true)}>
              Всё равно опубликовать
            </button>
          )}
        </div>
      )}

      <Assets slug={slug} editor={editor} />

      <h2>Версии</h2>
      {title.builds.length === 0 ? (
        <p className="muted">Сборок ещё нет.</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>Версия</th>
              <th>Когда</th>
              <th>Кто</th>
              <th>Заметка</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {title.builds.map((build) => (
              <tr key={build.id} className={build.active ? "active" : undefined}>
                <td>
                  {build.version}
                  {build.warnings.length > 0 && (
                    <span className="badge" title={build.warnings.join("\n")}>
                      ⚠ {build.warnings.length}
                    </span>
                  )}
                </td>
                <td>{new Date(build.created_at).toLocaleString("ru")}</td>
                <td>{build.created_by ?? "—"}</td>
                <td>{build.notes}</td>
                <td>
                  {build.active ? (
                    <strong>у игроков</strong>
                  ) : (
                    editor && (
                      <button
                        type="button"
                        className="small"
                        disabled={busy}
                        onClick={() => publish(build.id)}
                      >
                        Опубликовать
                      </button>
                    )
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  );
}

const AUDIO = /\.(wav|mp3|m4a|ogg|flac)$/i;
const ASSET_FILE = /\.(png|jpe?g|webp|wav|mp3|m4a|ogg|flac)$/i;

function Assets({ slug, editor }: { slug: string; editor: boolean }) {
  const [list, setList] = useState<AssetList | null>(null);
  const [progress, setProgress] = useState<string | null>(null);
  const [errors, setErrors] = useState<string[]>([]);
  const [warnings, setWarnings] = useState<string[]>([]);
  const [reload, setReload] = useState(0);

  useEffect(() => {
    api.assets(slug).then(setList, () => setList({ assets: [], missing: [] }));
  }, [slug, reload]);

  // Файлы по одному: исходники тяжёлые, а так видно, на каком файле ошибка.
  const upload = async (files: FileList | null) => {
    if (!files) return;
    const picked = Array.from(files).filter((file) => ASSET_FILE.test(file.name));
    const failed: string[] = [];
    const warned: string[] = [];
    let added = 0;
    for (const [index, file] of picked.entries()) {
      setProgress(`Загружаем ${index + 1} из ${picked.length}: ${file.name}`);
      try {
        const result = await api.uploadAsset(slug, file);
        if (!result.unchanged) added += 1;
        warned.push(...result.warnings.map((w) => `${file.name}: ${w}`));
      } catch (error) {
        failed.push(...problems(error));
      }
    }
    setProgress(`Готово: новых или обновлённых — ${added} из ${picked.length}`);
    setErrors(failed);
    setWarnings(warned);
    setReload((n) => n + 1);
  };

  return (
    <section className="card">
      <h2>Ассеты</h2>
      <p className="muted">
        Имена файлов по docs/ASSETS.md: bg_gym.png, anna_smirk.png, item_rose.png, map_city_map.png,
        cover_{slug}.png, music_calm.wav. Новая версия файла дойдёт до игроков со следующей сборкой
        и публикацией.
      </p>
      {editor && (
        <div className="actions">
          <FolderInput disabled={progress?.startsWith("Загружаем")} onPick={upload}>
            Загрузить папку
          </FolderInput>
          <label className="button secondary">
            Загрузить файлы
            <input
              type="file"
              hidden
              multiple
              accept="image/png,image/jpeg,image/webp,audio/*"
              onChange={(e) => {
                void upload(e.target.files);
                e.target.value = "";
              }}
            />
          </label>
        </div>
      )}
      {progress && <p className={progress.startsWith("Готово") ? "ok" : "muted"}>{progress}</p>}
      <Problems items={errors} />
      <Problems items={warnings} kind="warning" />

      {list && list.missing.length > 0 && (
        <>
          <h3>Не хватает — в игре будут заглушки</h3>
          <ul className="missing">
            {list.missing.map((m) => (
              <li key={`${m.kind}:${m.key}`}>
                <code>{m.file}</code>{" "}
                <span className="muted">
                  — {m.label} {m.key}
                </span>
              </li>
            ))}
          </ul>
        </>
      )}

      {list && list.assets.length > 0 && (
        <div className="assets">
          {list.assets.map((asset) => (
            <figure key={`${asset.kind}:${asset.key}`} className={asset.used ? "" : "unused"}>
              {asset.url && AUDIO.test(asset.filename) ? (
                <audio controls preload="none" src={asset.url} />
              ) : (
                asset.url && <img src={asset.url} alt={asset.key} loading="lazy" />
              )}
              <figcaption>
                <strong>{asset.key}</strong>
                <span className="muted small">
                  {asset.label}
                  {asset.width ? ` · ${asset.width}×${asset.height}` : ""} ·{" "}
                  {Math.round(asset.bytes / 1000)} КБ
                  {asset.used ? "" : " · нигде не используется"}
                </span>
                {asset.warnings.map((w) => (
                  <span key={w} className="small warning-text">
                    ⚠ {w}
                  </span>
                ))}
              </figcaption>
            </figure>
          ))}
        </div>
      )}
      {list && list.assets.length === 0 && list.missing.length === 0 && (
        <p className="muted">Ассетов пока нет.</p>
      )}
    </section>
  );
}
