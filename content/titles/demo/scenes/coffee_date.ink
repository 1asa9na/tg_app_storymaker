INCLUDE _inky.ink
# bg: cafe
# show: anna happy center
anna: Признаюсь, я думала, ты не позовёшь.
* [Сказать правду: долго решался]
    # effect: affection anna +4
    anna: Это мило.
* [Сделать вид, что это случайность]
    # effect: affection anna +1
    # show: anna smirk
    anna: Конечно. Совершенно случайно.
* { stat("charm") >= 3 } [Пошутить про бариста-неумеху]
    # effect: affection anna +6
    anna: Ха! Ты же сам тут подрабатываешь.
- -> END
