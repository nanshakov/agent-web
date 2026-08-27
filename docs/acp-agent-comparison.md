# Cline, OpenCode и Goose как ACP-бэкенды

Проверено по первоисточникам 27 августа 2026 года. Здесь ACP означает, что
Agent Web запускает агент как дочерний процесс по `stdio`, а не разбирает его
консольный JSON.

## Итог для Agent Web

У Cline нет важной для нашего Web UI ACP-возможности, которой не было бы у
OpenCode. Напротив, OpenCode публикует более полный жизненный цикл сессий.
Для локальной Qwen в LM Studio первым кандидатом стоит сделать **OpenCode**.
Goose тоже подходит, но его ACP-интеграция пока помечена upstream как
experimental.

| Возможность | Cline | OpenCode | Goose |
|---|---|---|---|
| Запуск ACP | `cline --acp` | `opencode acp` | `goose acp` |
| Потоковые события и отмена prompt | Да | Да | Да |
| Запросы разрешений | План/Act, по файлам и командам; auto-approve | Система permissions агента | Allow/reject once или always |
| Модель и режим во время сессии | Provider/model, Plan/Act | model/mode/set-config | model/mode |
| Сессии для UI | Заявлен resume; исходный ACP capability включает `loadSession` | new, list, load, resume, close, fork | persisted history, list (пагинация), fork; доступ истории зависит от ACP-клиента |
| Local OpenAI-compatible / LM Studio | Да, но текущий ACP блокирует `newSession` без Cline auth/API key | Да: `@ai-sdk/openai-compatible` + `baseURL` | Да: нативный OpenAI-compatible provider, `/models`, streaming |

## Что у Cline действительно своё

Cline лучше всего оформляет именно UX IDE: понятный Plan/Act, детальные
подтверждения для команд и файлов, выбор provider/model, изображения и
переключение организаций. Это удобно, но для нашего mobile-first Agent Web не
является недостающей ACP-функцией: OpenCode сохраняет инструменты, MCP,
`AGENTS.md`, formatter/linter и permissions, а Goose покрывает core-агентский
сценарий.

Критичное ограничение именно для нас: обычный Cline может использовать LM
Studio, но в текущем ACP-пути `newSession` проверяет Cline authentication или
`CLINE_API_KEY`. Поэтому это не корректный локальный backend без отдельного
входа, хотя сама модель остаётся локальной.

## Рекомендация

1. Сохраняем уже работающий Codex backend.
2. Следующим ACP-бэкендом пробуем OpenCode + LM Studio/Qwen: он не требует
   Cline account и лучше покрывает список/продолжение/ветвление чатов.
3. Goose рассматриваем вторым: особенно если понадобятся его расширения и
   более общий workflow-agent, но учитываем experimental-статус ACP.
4. Cline оставляем опциональным, пока upstream не уберёт ACP auth-gate для
   локального provider.

## Источники

- [Cline ACP](https://github.com/cline/cline/blob/main/docs/usage/acp.mdx) и [реализация ACP](https://github.com/cline/cline/blob/main/apps/cli/src/acp/acpAgent.ts)
- [Cline: OpenAI-compatible и LM Studio](https://github.com/cline/cline/blob/main/docs/provider-config/openai-compatible.mdx)
- [OpenCode ACP](https://github.com/anomalyco/opencode/blob/dev/packages/web/src/content/docs/acp.mdx) и [реализация ACP](https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/acp/agent.ts)
- [OpenCode: custom OpenAI-compatible provider](https://github.com/anomalyco/opencode/blob/dev/packages/web/src/content/docs/providers.mdx)
- [Goose ACP clients](https://github.com/aaif-goose/goose/blob/main/documentation/docs/guides/acp-clients.md), [list sessions](https://github.com/aaif-goose/goose/blob/main/crates/goose/src/acp/server/list_sessions.rs), [fork session](https://github.com/aaif-goose/goose/blob/main/crates/goose/src/acp/server/fork_session.rs)
- [Goose OpenAI-compatible provider](https://github.com/aaif-goose/goose/blob/main/crates/goose-providers/src/openai_compatible.rs)
