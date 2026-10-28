// Переходы внутри студии без перезагрузки страницы. Страница с несохранёнными правками
// ставит «стража»: он спрашивает, можно ли уйти, прежде чем сменится адрес.

let guard: (() => boolean) | null = null;

export function setLeaveGuard(next: (() => boolean) | null) {
  guard = next;
}

export function navigate(path: string) {
  if (guard && !guard()) return;
  window.history.pushState(null, "", path);
  window.dispatchEvent(new PopStateEvent("popstate"));
}
