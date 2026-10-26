import {
  bindViewportCssVars,
  disableVerticalSwipes,
  expandViewport,
  hapticFeedbackImpactOccurred,
  hapticFeedbackNotificationOccurred,
  hideBackButton,
  init,
  isTMA,
  miniAppReady,
  mountBackButton,
  mountMiniAppSync,
  mountSwipeBehavior,
  mountViewport,
  offBackButtonClick,
  onBackButtonClick,
  requestFullscreen,
  retrieveLaunchParams,
  retrieveRawInitData,
  setMiniAppBackgroundColor,
  setMiniAppHeaderColor,
  showBackButton,
} from "@telegram-apps/sdk";
import type { Haptic } from "@storymaker/game-ui/types";

const BACKGROUND = "#15121c";

let inTelegram = false;

/** Сырой initData для авторизации в API или null, если приложение открыто вне Telegram. */
export function readInitData(): string | null {
  return isTMA() ? (retrieveRawInitData() ?? null) : null;
}

/** Параметр диплинка `startapp`: `title_<slug>` открывает тайтл сразу. */
export function readStartParam(): string | null {
  if (!inTelegram) return null;
  try {
    return retrieveLaunchParams().tgWebAppStartParam ?? null;
  } catch {
    return null;
  }
}

/** Настраивает окно Mini App. Ошибки здесь не должны мешать авторизации. */
export function setupTelegramUi(): void {
  init();
  inTelegram = true;
  mountMiniAppSync.ifAvailable();
  setMiniAppHeaderColor.ifAvailable(BACKGROUND);
  setMiniAppBackgroundColor.ifAvailable(BACKGROUND);
  // Свайп вниз во время чтения не должен сворачивать приложение.
  mountSwipeBehavior.ifAvailable();
  disableVerticalSwipes.ifAvailable();
  mountBackButton.ifAvailable();
  expandViewport.ifAvailable();
  // Отступы под вырез и кнопки Telegram в полноэкранном режиме — CSS-переменными.
  const [mounting, viewport] = mountViewport.ifAvailable();
  if (mounting) {
    void viewport
      .then(() => {
        bindViewportCssVars.ifAvailable();
        // На телефоне — полный экран, как в играх; на десктопе Telegram откажет, и это нормально.
        const [requested, fullscreen] = requestFullscreen.ifAvailable();
        return requested ? fullscreen : undefined;
      })
      .catch(() => undefined);
  }
  miniAppReady.ifAvailable();
}

let backHandler: (() => void) | null = null;
const onBack = () => backHandler?.();

/** Системная кнопка «назад»: null — спрятать. */
export function setBackButton(handler: (() => void) | null): void {
  if (!inTelegram) return;
  if (backHandler === null && handler) onBackButtonClick.ifAvailable(onBack);
  if (backHandler && handler === null) offBackButtonClick.ifAvailable(onBack);
  backHandler = handler;
  if (handler) showBackButton.ifAvailable();
  else hideBackButton.ifAvailable();
}

export function haptic(kind: Haptic): void {
  if (!inTelegram) return;
  if (kind === "tap") hapticFeedbackImpactOccurred.ifAvailable("light");
  else hapticFeedbackNotificationOccurred.ifAvailable(kind);
}
