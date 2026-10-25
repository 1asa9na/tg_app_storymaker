# bg: gym
# music: upbeat
Вечерний зал почти опустел. Ты как раз собирался уходить.
# show: anna neutral left
anna: Опять ты? Я начинаю думать, что это не совпадение.
# effect: flag met_anna
me: Может, и не совпадение.
# show: anna smirk
anna: Смелое заявление для человека, который полчаса стоял у кулера.

* { has("water_bottle") } [Предложить воду]
    # effect: take water_bottle
    # effect: affection anna +3
    # show: anna happy
    anna: О, спасибо. Ты внимательный.
* [Пошутить про тренера] # effect: affection anna +1
    anna: Ха. Только не при нём.
* { affection("anna") >= 20 } [Позвать на кофе #premium: 15]
    # effect: affection anna +5
    # effect: start_quest anna_coffee
    # show: anna happy
    # fx: flash
    anna: …Давай. Но платишь ты.

- # show: anna neutral
anna: Ладно, мне пора. До завтра?
# hide: anna
Дверь хлопнула, и в зале стало совсем тихо.
-> END
