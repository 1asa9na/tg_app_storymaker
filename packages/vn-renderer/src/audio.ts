/** Музыка и звуки сцены. Браузеры разрешают звук только после жеста пользователя. */
export class AudioPlayer {
  private current: HTMLAudioElement | null = null;
  private currentUrl: string | null = null;

  music(url: string | null | undefined): void {
    if ((url ?? null) === this.currentUrl) {
      return;
    }
    this.current?.pause();
    this.current = null;
    this.currentUrl = url ?? null;
    if (url) {
      this.current = new Audio(url);
      this.current.loop = true;
      this.current.volume = 0.6;
      this.current.play().catch(() => undefined);
    }
  }

  sfx(url: string): void {
    new Audio(url).play().catch(() => undefined);
  }

  stop(): void {
    this.music(null);
  }
}
