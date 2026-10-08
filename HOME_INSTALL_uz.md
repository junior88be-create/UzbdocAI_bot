# Уй серверига ўрнатиш (Docker Desktop'сиз, Windows)

«Юрист 24» ботидек: Windows ёқилганда бот **ўзи ишга тушади**, ўчса қайта тирилади ва
GitHub'га янги код тушса, **ҳар 5 дақиқада ўзи янгиланади**.

Бу вариантда Docker, Redis ва Celery керак эмас: бот ҳужжатларни ўзи қайта ишлайди
(`TASK_BACKEND=inline`). Керак бўладиганлар — Python 3.12, PostgreSQL 16 ва Git;
скрипт уларни `winget` орқали ўзи ўрнатади (интернет керак).

## Ўрнатиш (бир марта)

1. Zip'ни очинг, масалан `C:\UzbdocAI_bot` папкасига (ичида `scripts`, `app`, `alembic` бўлсин).
2. PowerShell'ни **Administrator сифатида** очинг ва ёзинг:

   ```powershell
   cd C:\UzbdocAI_bot
   powershell -ExecutionPolicy Bypass -File .\scripts\windows_setup.ps1
   ```

3. Скрипт сўрайдиган нарсалар:
   - PostgreSQL учун админ парол (ўзингиз ўйлаб топинг, ёзиб қўйинг);
   - `BOT_TOKEN` (BotFather'дан);
   - `GEMINI_API_KEY` (https://aistudio.google.com);
   - Ўзингизнинг Telegram ID рақамингиз (админ бўлади).
4. Охирида `Bot ishlayapti!` чиқади. Telegram'да ботга `/start` юборинг.

Скриптни қайта ишга тушириш хавфсиз: мавжуд `.env` ва база сақланади.

## Нималарни ўзи қилади

- **`UzbdocAI_bot`** вазифаси (Task Scheduler): Windows ёқилганда, ҳеч ким кирмаса ҳам, ботни
  ойнасиз ишга туширади; бот ўчса 10 сонияда қайта тирилади.
- **`UzbdocAI_bot_Update`** вазифаси: ҳар 5 дақиқада GitHub'дан янги кодни текширади. Янги
  версия бўлса: кодни олади → синтаксис ва `import app.main` текширувидан ўтказади → ботни
  тўхтатиб, база миграциясини қўллайди → қайта ишга туширади. **Текширув ёки миграция хато
  берса, аввалги ишлаётган версияга қайтади** ва шу бузуқ версияни қайта синамайди
  (кейинги тузатилган версияни кутади). Журнал: `update.log`.
- Компьютер уйқуга/гибернацияга кетмайди (қувват уланганда).
- Маълумотлар: база — PostgreSQL хизматида, юкланган файллар — `storage\` папкасида.

Демак ишлаш тартиби: **ноутбукда таҳрирланг → `git push` → уй сервери ўзи янгиланади.**

## Бошқариш

```powershell
# Ботни тўхтатиш (шу папкадагини):
powershell -ExecutionPolicy Bypass -File .\scripts\stop_bot.ps1
# Тўхтатиш + автоматик ишга тушириш ва янгиланишни ўчириш:
powershell -ExecutionPolicy Bypass -File .\scripts\stop_bot.ps1 -Disable
# Қўлда ишга тушириш / қўлда дарҳол янгилаш:
Start-ScheduledTask -TaskName UzbdocAI_bot
powershell -ExecutionPolicy Bypass -File .\scripts\update.ps1
# Логлар:
Get-Content .\bot.log -Tail 50
Get-Content .\update.log -Tail 20
```

Қайта ёқиш (`-Disable`'дан кейин): `Enable-ScheduledTask UzbdocAI_bot; Enable-ScheduledTask UzbdocAI_bot_Update`.

## Муҳим

- Битта `BOT_TOKEN` билан **бир вақтда фақат битта бот** ишлаши керак. Railway'даги ва
  ноутбукдаги нусхалар ўчиқ бўлиши шарт.
- Уй серверидаги папкада кодни қўлда таҳрирламанг — янгилашда GitHub'дагига қайтарилади.
- Сервер `main` шохидаги ҳар бир кодни ишга туширади, шунинг учун GitHub ҳисобингизни
  (2 босқичли тасдиқ) ва олдин чатга ташланган токенларни (Settings → Developer settings)
  ҳимоя қилинг/бекор қилинг.
- Агар шу компьютерда бошқа бот ҳам ишласа: бу бот 8081 портда соғлиқ текшируви (`/health`)
  очади; тўқнашса `.env`га `HEALTH_PORT=8082` қўшинг.
- Ойлик Gemini лимитини https://ai.studio/spend да назорат қилиб туринг.
