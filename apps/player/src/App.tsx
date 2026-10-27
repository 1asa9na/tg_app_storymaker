import { lazy, Suspense, useEffect, useMemo, useState } from "react";

import { Api, ApiError, type CatalogEntry, type Me, type Profile } from "./api";
import { haptic, readStartParam, setBackButton } from "./telegram";

// Экран игры с рантаймом ink и рендерером сцен грузится, только когда открыли тайтл.
const GameScreen = lazy(() =>
  import("@storymaker/game-ui").then((m) => ({ default: m.GameScreen })),
);

type Screen =
  | { kind: "catalog" }
  | { kind: "profile" }
  | { kind: "game"; slug: string }
  | { kind: "preview"; token: string };

type Load =
  | { kind: "loading" }
  | { kind: "ready"; me: Me; catalog: CatalogEntry[] }
  | { kind: "error"; message: string };

function errorMessage(error: unknown): string {
  if (error instanceof ApiError && error.status === 401) {
    return "Сессия устарела. Закройте приложение и откройте его снова.";
  }
  return "Не удалось связаться с сервером. Попробуйте позже.";
}

/**
 * Куда открыться сразу:
 * - диплинк startapp=title_<slug> — тайтл;
 * - кнопка превью из бота (?preview=<токен>) или startapp=preview_<токен> — песочница сборки.
 */
function initialScreen(): Screen {
  const preview = new URLSearchParams(window.location.search).get("preview");
  if (preview) return { kind: "preview", token: preview };
  const start = readStartParam();
  if (start?.startsWith("preview_")) return { kind: "preview", token: start.slice(8) };
  return start?.startsWith("title_") ? { kind: "game", slug: start.slice(6) } : { kind: "catalog" };
}

export function App({ initData }: { initData: string | null }) {
  if (!initData) {
    return (
      <main className="screen">
        <p>Откройте приложение через бота в Telegram.</p>
      </main>
    );
  }
  return <Platform initData={initData} />;
}

function Platform({ initData }: { initData: string }) {
  const api = useMemo(() => new Api(initData), [initData]);
  const [load, setLoad] = useState<Load>({ kind: "loading" });
  const [screen, setScreen] = useState<Screen>(initialScreen);
  const [reload, setReload] = useState(0);
  const slug = screen.kind === "game" ? screen.slug : null;
  const previewToken = screen.kind === "preview" ? screen.token : null;
  const client = useMemo(() => {
    if (previewToken) return api.preview(previewToken);
    return slug ? api.title(slug) : null;
  }, [api, slug, previewToken]);

  useEffect(() => {
    let cancelled = false;
    Promise.all([api.me(), api.catalog()]).then(
      ([me, catalog]) => !cancelled && setLoad({ kind: "ready", me, catalog }),
      (error: unknown) => !cancelled && setLoad({ kind: "error", message: errorMessage(error) }),
    );
    return () => {
      cancelled = true;
    };
  }, [api, reload]);

  // Каталог — корень: кнопка «назад» видна только на вложенных экранах.
  useEffect(() => {
    if (screen.kind === "profile") setBackButton(() => setScreen({ kind: "catalog" }));
    else if (screen.kind === "catalog") setBackButton(null);
  }, [screen]);

  const toCatalog = () => {
    setScreen({ kind: "catalog" });
    setReload((n) => n + 1);
  };

  if (client) {
    return (
      <Suspense fallback={<main className="screen muted">Загружаем…</main>}>
        <GameScreen
          client={client}
          playerName={load.kind === "ready" ? load.me.first_name : undefined}
          haptic={haptic}
          onBackHandler={setBackButton}
          onExit={toCatalog}
          badge={screen.kind === "preview" ? "Превью" : undefined}
        />
      </Suspense>
    );
  }

  if (load.kind === "loading") return <main className="screen muted">Загружаем…</main>;
  if (load.kind === "error") return <main className="screen">{load.message}</main>;

  if (screen.kind === "profile") return <ProfileScreen api={api} me={load.me} />;

  return (
    <main className="page">
      <header className="page-header">
        <div>
          <h1>Истории</h1>
          <p className="muted">Привет, {load.me.first_name}!</p>
        </div>
        <button type="button" className="chip" onClick={() => setScreen({ kind: "profile" })}>
          Ур. {load.me.level}
        </button>
      </header>
      {load.catalog.length === 0 && <p className="muted">Историй пока нет — скоро появятся.</p>}
      <ul className="titles">
        {load.catalog.map((title) => (
          <li key={title.slug}>
            <button
              type="button"
              className="title-card"
              style={
                title.cover
                  ? {
                      backgroundImage: `linear-gradient(transparent 40%, rgb(21 18 28 / 0.9)), url("${title.cover.preview ?? title.cover.full}")`,
                    }
                  : undefined
              }
              onClick={() => {
                haptic("tap");
                setScreen({ kind: "game", slug: title.slug });
              }}
            >
              <strong>{title.name}</strong>
              <span className="muted">
                {title.save
                  ? title.save.finished
                    ? "Пройдено"
                    : `День ${title.save.day}${title.days ? ` из ${title.days}` : ""}`
                  : title.days
                    ? `${title.days} дней`
                    : "Новая история"}
              </span>
              <span className="title-action">{title.save ? "Продолжить" : "Начать"}</span>
            </button>
          </li>
        ))}
      </ul>
    </main>
  );
}

function ProfileScreen({ api, me }: { api: Api; me: Me }) {
  const [profile, setProfile] = useState<Profile | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    api.profile().then(setProfile, () => setFailed(true));
  }, [api]);

  if (failed) return <main className="screen">Не удалось загрузить профиль.</main>;
  if (!profile) return <main className="screen muted">Загружаем…</main>;

  const span = profile.next_level_xp - profile.level_xp;
  return (
    <main className="page">
      <header className="page-header">
        <div>
          <h1>{me.first_name}</h1>
          <p className="muted">Уровень {profile.level}</p>
        </div>
      </header>
      <section className="panel">
        <meter min={0} max={span} value={profile.xp - profile.level_xp} />
        <p className="muted">
          Опыт {profile.xp} · до уровня {profile.level + 1} — {profile.next_level_xp - profile.xp}
        </p>
      </section>
      <h2>Достижения</h2>
      {profile.achievements.length === 0 ? (
        <p className="muted">Пока нет — они приходят за квесты и важные моменты историй.</p>
      ) : (
        <ul className="achievements">
          {profile.achievements.map((achievement) => (
            <li key={`${achievement.title}:${achievement.key}`} className="panel">
              <strong>{achievement.name}</strong>
              <span className="muted">
                {new Date(achievement.unlocked_at).toLocaleDateString("ru")}
              </span>
            </li>
          ))}
        </ul>
      )}
    </main>
  );
}
