# Уй серверига ўрнатиш (Docker Desktop'сиз, Windows)

Бу вариантда Docker, Redis ва Celery керак эмас: бот ҳужжатларни ўзи қайта ишлайди
(`TASK_BACKEND=inline`). Керак бўладиган нарсалар: Python 3.12 ва PostgreSQL 16 —
скрипт уларни `winget` орқали ўзи ўрнатади (интернет керак).

## Қадамлар

1. Zip'ни очинг, масалан `C:\UzbdocAI_bot` папкасига (ичида `scripts`, `app`, `alembic` бўлсин).
2. Бошлаш менюсидан **PowerShell**ни топиб, ўнг тугма → **Administrator сифатида ишга тушириш**.
3. Қуйидагини ёзинг:

   ```powershell
   cd C:\UzbdocAI_bot
   powershell -ExecutionPolicy Bypass -File scripts\windows_setup.ps1
   ```

4. Скрипт сўрайдиган нарсалар:
   - PostgreSQL учун админ парол (ўзингиз ўйлаб топинг, ёзиб қўйинг);
   - `BOT_TOKEN` (BotFather'дан);
   - `GEMINI_API_KEY` (https://aistudio.google.com);
   - Ўзингизнинг Telegram ID рақамингиз (админ бўлади).
5. Охирида скрипт `bot.log`нинг охирги қаторларини ва `Health check: 200` ни кўрсатади.
   Кейин Telegram'да ботга `/start` юборинг.

Скрипт қайта ишга туширилса хавфсиз: мавжуд `.env` ва база сақланади.

## Нималарни ўзи қилади

- бот компьютер ёқилганда **ўзи ишга тушади** (Task Scheduler, `UzbdocAI_bot`) ва ўчиб қолса 10 сонияда қайта тирилади;
- компьютер уйқуга/гибернацияга кетмайди (қувват уланганда);
- маълумотлар: база — PostgreSQL хизматида, юкланган файллар — `storage\` папкасида.

## Бошқариш

```powershell
Stop-ScheduledTask  -TaskName UzbdocAI_bot     # тўхтатиш
Start-ScheduledTask -TaskName UzbdocAI_bot     # ишга тушириш
Get-Content C:\UzbdocAI_bot\bot.log -Tail 50   # логни кўриш
```

## Янгилаш (GitHub орқали)

Янгиланишлар GitHub'га (`junior88be-create/UzbdocAI_bot`) юклангач, уй серверига **ўзи
келмайди** — уни олиш учун Administrator PowerShell'да:

```powershell
cd C:\UzbdocAI_bot
powershell -ExecutionPolicy Bypass -File scripts\update.ps1
```

Скрипт `git`'дан охирги версияни олади, ботни тўхтатади, кутубхона ва база
миграцияларини янгилайди, ботни қайта ишга туширади. `.env`, `storage` ва `bot.log`
тегмайди. (Zip'дан ўрнатилган папка биринчи ишга туширишда ўзи `git` папкага айланади.)
Янгилаш бўлмаса "Already up to date" деб чиқади.

Ҳар тун 04:00'да **автоматик** янгилаш хоҳласангиз, бир марта `-Schedule` билан ишга
туширинг:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\update.ps1 -Schedule
```

Эътибор: автоматик янгилаш хато чиққан версияни ҳам олиб ботни тўхтатиб қўйиши мумкин,
шунинг учун қўлда янгилаган маъқул. Автоматикани ўчириш:
`Unregister-ScheduledTask -TaskName UzbdocAI_update -Confirm:$false`.

Кодни шу папкада қўлда таҳрирламанг — янгилашда GitHub'дагига қайтарилади.

## Муҳим

- Битта `BOT_TOKEN` билан **бир вақтда фақат битта бот** ишлаши керак. Railway'даги
  нусха ўчиқ бўлиши шарт.
- Windows Update компьютерни қайта юклаши мумкин — бот ўзи қайта туради.
- Ойлик Gemini лимитини https://ai.studio/spend да назорат қилиб туринг.
