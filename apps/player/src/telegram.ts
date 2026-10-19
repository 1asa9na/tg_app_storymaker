import {
  disableVerticalSwipes,
  expandViewport,
  init,
  isTMA,
  miniAppReady,
  mountMiniAppSync,
  mountSwipeBehavior,
  retrieveRawInitData,
  setMiniAppBackgroundColor,
  setMiniAppHeaderColor,
} from "@telegram-apps/sdk";

const BACKGROUND = "#15121c";

/** Сырой initData для авторизации в API или null, если приложение открыто вне Telegram. */
export function readInitData(): string | null {
  return isTMA() ? (retrieveRawInitData() ?? null) : null;
}

/** Настраивает окно Mini App. Ошибки здесь не должны мешать авторизации. */
export function setupTelegramUi(): void {
  init();
  mountMiniAppSync.ifAvailable();
  setMiniAppHeaderColor.ifAvailable(BACKGROUND);
  setMiniAppBackgroundColor.ifAvailable(BACKGROUND);
  // Свайп вниз во время чтения не должен сворачивать приложение.
  mountSwipeBehavior.ifAvailable();
  disableVerticalSwipes.ifAvailable();
  expandViewport.ifAvailable();
  miniAppReady.ifAvailable();
}
