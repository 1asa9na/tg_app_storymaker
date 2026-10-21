declare global {
  interface Window {
    __APP_CONFIG__?: Record<string, string | undefined>;
  }
}

function read(key: string): string | undefined {
  const value = window.__APP_CONFIG__?.[key];
  // Незаменённый плейсхолдер Caddy (локальная разработка) считаем пустым значением.
  return value && !value.startsWith("{{") ? value : undefined;
}

export const config = {
  env: read("env") ?? "local",
  sentryDsn: read("sentryDsn"),
};
