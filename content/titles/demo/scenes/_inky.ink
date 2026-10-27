// Заглушки функций игры для превью в Inky. Это не сцена: игра этот файл не загружает.
// Подключение — первой строкой сцены: INCLUDE _inky.ink
// В игре вместо этих функций работает настоящее состояние игрока.
// Чтобы проверить в Inky другую ветку, поменяйте значения ниже. Например, Анне — 30 симпатии:
//   === function affection(who) ===
//   { who == "anna":
//       ~ return 30
//   }
//   ~ return 0
// А флаг met_anna стоит:
//   === function flag(name) ===
//   ~ return name == "met_anna"

=== function affection(who) ===
~ return 0

=== function has(item) ===
~ return false

=== function flag(name) ===
~ return false

=== function stat(name) ===
~ return 0

=== function global_level() ===
~ return 1
