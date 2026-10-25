import { lazy, Suspense, useEffect, useState } from "react";

import { ApiError, fetchMe, type Me } from "./api";

type State =
  | { kind: "outside" }
  | { kind: "loading" }
  | { kind: "ready"; me: Me }
  | { kind: "error"; message: string };

// Сцена с рантаймом ink и рендерером грузится, только когда её открыли.
const DemoScene = lazy(() => import("./demo/DemoScene").then((m) => ({ default: m.DemoScene })));

function errorMessage(error: unknown): string {
  if (error instanceof ApiError && error.status === 401) {
    return "Сессия устарела. Закройте приложение и откройте его снова.";
  }
  return "Не удалось связаться с сервером. Попробуйте позже.";
}

export function App({ initData }: { initData: string | null }) {
  const [state, setState] = useState<State>(initData ? { kind: "loading" } : { kind: "outside" });
  const [demo, setDemo] = useState(false);

  useEffect(() => {
    if (!initData) {
      return;
    }
    let cancelled = false;
    fetchMe(initData).then(
      (me) => !cancelled && setState({ kind: "ready", me }),
      (error: unknown) => !cancelled && setState({ kind: "error", message: errorMessage(error) }),
    );
    return () => {
      cancelled = true;
    };
  }, [initData]);

  if (demo) {
    return (
      <Suspense fallback={<main className="screen muted">Готовим сцену…</main>}>
        <DemoScene
          playerName={state.kind === "ready" ? state.me.first_name : undefined}
          onExit={() => setDemo(false)}
        />
      </Suspense>
    );
  }

  return (
    <main className="screen">
      {state.kind === "outside" && <p>Откройте приложение через бота в Telegram.</p>}
      {state.kind === "loading" && <p className="muted">Загружаем…</p>}
      {state.kind === "ready" && (
        <>
          <h1>Привет, {state.me.first_name}!</h1>
          <p className="muted">Скоро здесь появятся истории.</p>
        </>
      )}
      {state.kind === "error" && <p>{state.message}</p>}
      {state.kind !== "loading" && (
        <div className="actions">
          <button type="button" onClick={() => setDemo(true)}>
            Демо-сцена
          </button>
        </div>
      )}
    </main>
  );
}
