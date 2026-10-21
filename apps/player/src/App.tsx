import { useEffect, useState } from "react";

import { ApiError, fetchMe, type Me } from "./api";

type State =
  | { kind: "outside" }
  | { kind: "loading" }
  | { kind: "ready"; me: Me }
  | { kind: "error"; message: string };

function errorMessage(error: unknown): string {
  if (error instanceof ApiError && error.status === 401) {
    return "Сессия устарела. Закройте приложение и откройте его снова.";
  }
  return "Не удалось связаться с сервером. Попробуйте позже.";
}

export function App({ initData }: { initData: string | null }) {
  const [state, setState] = useState<State>(initData ? { kind: "loading" } : { kind: "outside" });

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
    </main>
  );
}
