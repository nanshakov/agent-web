# Agent Web

**Agent Web** — компактный web-интерфейс для работы с локальными проектами через
Codex и OpenCode. Он рассчитан на Chrome, домашнюю LAN и один компьютер, на
котором находятся папки с проектами и агенты.

Можно начать чат с Codex, продолжить его OpenCode с локальной моделью из LM
Studio, затем вернуться к Codex — переписка останется одним видимым чатом.

> Сейчас это LAN-прототип без входа по паролю. Не публикуйте порт в интернет и
> не настраивайте port forwarding.

## Возможности

- Codex и OpenCode через ACP, без разбора консольного JSON.
- OpenCode + LM Studio: локальная модель без облачного API-ключа.
- Настройки для каждого проекта: агент, модель, уровень рассуждений и доступ к
  рабочей папке.
- Логические чаты: смена агента/модели сохраняет одну ленту сообщений.
- Передача контекста при переключении; длинная история сжимается исходным
  агентом.
- Импорт и синхронизация локальных Codex-чатов из разрешённых папок проектов.
- Экспорт чата как `context.md` и `context.json`.
- SQLite + Alembic; перед каждой миграцией создаётся резервная копия БД.
- Автообновление из Git-репозитория по явному подтверждению пользователя.

## Быстрый старт

### 1. Подготовьте зависимости

| Что | Windows | macOS |
| --- | --- | --- |
| Git | `winget install Git.Git` | `xcode-select --install` или `brew install git` |
| uv | `winget install astral-sh.uv` | `brew install uv` |
| Node.js — нужен для OpenCode | `winget install OpenJS.NodeJS.LTS` | `brew install node` |
| Chrome | обычная установка Chrome | обычная установка Chrome |
| LM Studio — только для локальных моделей | [lmstudio.ai](https://lmstudio.ai) | [lmstudio.ai](https://lmstudio.ai) |

`uv` сам установит подходящий Python для этого проекта. Если команда `uv` не
находится сразу после установки, откройте новое окно терминала.

### 2. Склонируйте проект и создайте окружение

Замените URL на адрес своего репозитория.

Windows PowerShell:

```powershell
git clone https://github.com/your-account/agent-web.git
Set-Location agent-web
uv sync --extra dev
```

macOS Terminal:

```bash
git clone https://github.com/your-account/agent-web.git
cd agent-web
uv sync --extra dev
```

### 3. Разрешите папки с проектами

Agent Web не принимает произвольный путь из браузера: проект должен быть
существующей папкой внутри заранее разрешённого корня.

Windows:

```powershell
uv run agent-web init --root 'C:\dev'
```

macOS:

```bash
uv run agent-web init --root "$HOME/dev"
```

Для нескольких корней укажите их одной командой:

```bash
uv run agent-web init --root "$HOME/dev" --root "$HOME/work"
```

Также можно импортировать существующие локальные Codex-чаты, если их рабочие
папки уже находятся внутри указанных корней:

```bash
uv run agent-web init --root "$HOME/dev" --discover-codex
```

### 4. Запустите интерфейс

Для работы только с этого компьютера:

```bash
uv run agent-web serve
```

Откройте <http://127.0.0.1:8765> в Chrome.

Для телефона или другого устройства в домашней сети:

Windows:

```powershell
.\scripts\restart-agent-web.ps1
ipconfig
```

macOS:

```bash
./scripts/restart-agent-web.sh
ipconfig getifaddr en0
```

Откройте в Chrome на телефоне `http://<LAN-IP>:8765`, например
`http://192.168.1.25:8765`.

Скрипты запускают сервер на `0.0.0.0`, перезапускают прежний экземпляр и пишут
логи в `data/logs/`.

### 5. Если Windows Firewall блокирует телефон

Запустите PowerShell **от имени администратора** и откройте только TCP-порт
Agent Web для публичного профиля сети:

```powershell
New-NetFirewallRule -DisplayName 'Agent Web LAN (TCP 8765)' -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8765 -Profile Public
```

Удалить правило можно так:

```powershell
Remove-NetFirewallRule -DisplayName 'Agent Web LAN (TCP 8765)'
```

Не создавайте правило для широкого диапазона портов.

## OpenCode + LM Studio

Этот раздел нужен, если хотите использовать локальную Qwen или другую модель из
LM Studio. Codex можно использовать без него.

### Установите OpenCode

```bash
npm install -g opencode-ai
opencode --version
```

### Запустите локальный сервер LM Studio

1. Откройте LM Studio.
2. Загрузите coding-модель. В текущей конфигурации используется
   `qwen/qwen3.8-27b`.
3. В разделе Developer включите Local Server.
4. Убедитесь, что endpoint отвечает по `http://127.0.0.1:1234/v1`.

### Настройте OpenCode на локальную модель

Создайте файл `~/.config/opencode/opencode.json`.

Windows: `%USERPROFILE%\.config\opencode\opencode.json`
macOS: `~/.config/opencode/opencode.json`

```json
{
  "$schema": "https://opencode.ai/config.json",
  "provider": {
    "lm-studio": {
      "npm": "@ai-sdk/openai-compatible",
      "name": "LM Studio (local)",
      "options": {
        "baseURL": "http://127.0.0.1:1234/v1"
      },
      "models": {
        "qwen/qwen3.8-27b": {
          "name": "Qwen 3.8 27B"
        }
      }
    }
  },
  "enabled_providers": ["lm-studio"],
  "model": "lm-studio/qwen/qwen3.8-27b",
  "small_model": "lm-studio/qwen/qwen3.8-27b",
  "share": "disabled"
}
```

Проверьте конфигурацию:

```bash
opencode debug config
opencode models lm-studio
```

После перезапуска Agent Web выберите у проекта **OpenCode · LM Studio**. ACP
запускается автоматически; вручную `opencode acp` запускать не нужно.

## Как пользоваться

1. Добавьте папку проекта через поле **Add project**.
2. Откройте **Agent defaults** и выберите Codex или OpenCode.
3. Для Codex выберите модель и доступный ей reasoning: низкий, средний,
   высокий, очень высокий, максимальный или ультра.
4. Нажмите **New chat**.
5. В открытом чате можно изменить агента, модель, reasoning и доступ, затем
   нажать **Switch for next message**.
6. При смене модели внутри одного агента, например Codex Sol на Terra, Agent Web
   продолжает тот же native thread: Codex сохраняет контекст самостоятельно.
7. При смене агента, например Codex на OpenCode, Agent Web явно спрашивает,
   передавать ли историю. Можно передать контекст или начать новый сегмент без него.

Режимы доступа:

- **Read only** — OpenCode не получает прав на запись, shell-команды и
  подагентов.
- **Write in project** — автономная работа в выбранном проекте; внешние папки
  запрещены настройками OpenCode.

Только после явного согласия Agent Web переносит другому агенту уже показанное
содержимое переписки, включая секреты, если они там есть. Он не сканирует `.env`
и переменные окружения специально. Отказ от передачи не отменяет переключение:
новый агент начинает без прошлого контекста.

Нативное продолжение Codex основано на поддерживаемом App Server механизме:
`turn/start` принимает новый `model` для существующего `threadId`.
См. [официальную документацию OpenAI](https://developers.openai.com/codex/app-server/).

## Обновление из Git

Сначала запустите тесты на своём компьютере:

```bash
uv run agent-web run-tests
```

### Первое подключение обновлений

Один раз укажите публичный репозиторий и ветку из корня проекта.

Windows:

```powershell
.\scripts\configure-update.ps1 -RepositoryUrl "https://github.com/nanshakov/agent-web.git" -Branch main
.\scripts\restart-agent-web.ps1
```

macOS:

```bash
chmod +x scripts/*.sh
./scripts/configure-update.sh https://github.com/nanshakov/agent-web.git main
./scripts/restart-agent-web.sh
```

Команда `chmod` нужна только в том случае, если macOS сообщает, что скрипты
нельзя выполнить. После первой настройки повторять `configure-update` не нужно.

После настройки при каждом запуске Agent Web в фоне выполняет `git fetch` и
сравнивает текущий commit с указанной веткой. Если появилась новая версия,
интерфейс показывает её короткий commit. Код автоматически не заменяется:
применение обновления всегда запускает человек.

Проверка и применение:

Windows:

```powershell
.\scripts\check-update.ps1
.\scripts\apply-update.ps1
```

macOS:

```bash
./scripts/check-update.sh
./scripts/apply-update.sh
```

Перед применением обновления на другом компьютере стоит запустить `uv run
agent-web run-tests`. Если тесты не проходят, не применяйте обновление:
рабочая версия и папка проекта останутся нетронутыми.

`apply-update` принимает только fast-forward обновления и откажется работать,
если в папке установки есть локальные изменения. После обновления сервис
перезапускается, а миграции базы данных запускаются при старте.

Если обновление добавило или изменило Python-зависимости, перед применением
выполните `uv sync --extra dev`: скрипт обновления сам зависимости не
устанавливает.

## Диагностика

```bash
uv run agent-web doctor
uv run agent-web run-tests
```

Логи запущенного через скрипт сервера:

```text
data/logs/agent-web.out.log
data/logs/agent-web.err.log
```

## Частые вопросы

### Что такое `uv`?

Это менеджер Python-окружений и зависимостей. Он создаёт `.venv`, ставит нужные
пакеты и запускает команды проекта одинаково на Windows и macOS.

### Почему телефон не открывает адрес Mac или Windows?

Проверьте, что оба устройства в одной сети, сервер запущен с `--allow-lan`, вы
используете LAN-IP компьютера, а firewall пропускает TCP 8765. Адрес
`127.0.0.1` доступен только на самом компьютере.

### Нужен ли Tailscale Serve, HTTPS или пароль?

Нет для текущего домашнего LAN-сценария. Прямой локальный IP допустим. HTTPS,
аутентификация, CSRF, CSP, защита от clickjacking и DNS rebinding пока являются
техническим долгом; не выводите сервис за пределы доверенной сети.

### Где лежат настройки и база данных?

При запуске через скрипты — в папке репозитория `data/`. Там находятся
`agent-web.sqlite3`, резервные копии в `data/backups/`, конфигурация и логи.
При запуске обычной командой без `--data-dir` используется системная папка
данных Agent Web для вашей ОС.

### Где лежат прикреплённые файлы?

Вложения сохраняются внутри проекта в `.agent-web/attachments/<chat-id>/` и
удаляются вместе с чатом. Для Git-проектов Agent Web добавляет `.agent-web/` в
локальный `.git/info/exclude`, не изменяя репозиторный `.gitignore`. Текстовые
файлы передаются агенту вместе с первыми 100 000 символов, изображения — путём
к исходному файлу.

### Почему проект нельзя добавить?

Путь должен указывать на существующую папку, а сам проект должен лежать внутри
одного из корней, заданных в `agent-web init --root ...`.

### Можно ли продолжить работу другого агента?

Да, в пределах Codex и OpenCode. Откройте проект и выберите нового агента в
чате. Agent Web создаст новый внутренний сегмент и передаст ему историю. Для
внешнего переноса используйте экспорт `context.md` или `context.json`.

### Почему не видна модель LM Studio?

Проверьте, что LM Studio Local Server запущен на порту 1234, имя модели в
`opencode.json` совпадает с именем из LM Studio и `opencode models lm-studio`
показывает эту модель. Затем перезапустите Agent Web.

### Как остановить сервер?

Если сервер запущен в текущем терминале, нажмите `Ctrl+C`. Если запускали через
скрипт, повторный запуск того же скрипта безопасно перезапустит сервер на порту
8765.

## Разработка

```bash
uv sync --extra dev
uv run pytest
```

Изменения схемы БД оформляются Alembic-миграцией. Не удаляйте `data/` ради
повторной миграции: там находится история чатов и резервные копии.

## Лицензия

MIT. Вы несёте ответственность за действия агентов и за доступ, предоставленный
им к вашим проектам и сети.
