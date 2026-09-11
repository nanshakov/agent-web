import { test, expect, type Page, type WebSocketRoute } from "@playwright/test";
async function fixture(page: Page) {
  const project = {
    id: "p1",
    name: "Example project",
    path: "/dev/example",
    agent: "codex",
    model: "test-model",
    reasoning: "high",
    sandbox: "read_only",
  };
  const session = {
    ...project,
    id: "s1",
    title: "Existing conversation",
    source: "codex",
    created_at: "2026-09-10T10:00:00Z",
    last_activity_at: "2026-09-10T10:00:00Z",
  };
  let messages: any[] = [
    { role: "user", content: "Earlier question" },
    {
      role: "assistant",
      content: "Earlier answer",
      rendered_content: "<p>Earlier answer</p>",
    },
  ];
  let sockets: WebSocketRoute[] = [];
  let connections = 0,
    creates = 0,
    posts = 0;
  await page.routeWebSocket("**/api/v1/ws/sessions/*", (ws) => {
    connections++;
    sockets.push(ws);
  });
  await page.route("**/api/v1/**", async (route) => {
    const path = new URL(route.request().url()).pathname.replace("/api/v1", "");
    let body: unknown = {};
    if (path === "/projects") body = [project];
    else if (
      path === "/projects/p1/sessions" &&
      route.request().method() === "POST"
    ) {
      creates++;
      body = { id: "s2" };
    } else if (path === "/projects/p1/sessions")
      body = [
        session,
        ...(creates
          ? [{ ...session, id: "s2", title: "New conversation" }]
          : []),
      ];
    else if (path === "/agents")
      body = {
        codex: {
          ready: true,
          models: [
            {
              id: "test-model",
              name: "Test model",
              reasoning_efforts: ["low", "high"],
            },
          ],
          usage: { available: false, message: "Test usage" },
        },
      };
    else if (path === "/health") body = { status: "ready" };
    else if (path === "/update") body = { state: "up_to_date" };
    else if (path.endsWith("/messages")) body = messages;
    else if (path.endsWith("/turns")) {
      posts++;
      messages.push({
        role: "user",
        content: "A new instruction",
        turn_id: "t1",
        status: "running",
      });
      body = { id: "t1", status: "running" };
    }
    await route.fulfill({ json: body });
  });
  return {
    setMessages(value: typeof messages) {
      messages = value;
    },
    get connections() {
      return connections;
    },
    get creates() {
      return creates;
    },
    get posts() {
      return posts;
    },
    emit(event: unknown) {
      sockets.forEach((s) => s.send(JSON.stringify(event)));
    },
    disconnect() {
      sockets.forEach((s) => s.close());
      sockets = [];
    },
    finish() {
      messages = messages.map((m) =>
        m.turn_id === "t1" ? { ...m, status: "completed" } : m,
      );
      messages.push({
        role: "assistant",
        content: "Completed response",
        rendered_content: "<p>Completed response</p>",
        turn_id: "t1",
        status: "completed",
      });
    },
  };
}
test("mobile tool activity updates without replacing text and survives reconnect and reload", async ({
  page,
}) => {
  const f = await fixture(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/projects/p1/chats/s1");
  await expect.poll(() => f.connections).toBeGreaterThan(0);
  const command = {
    id: "c1",
    kind: "commandExecution",
    label: "Command",
    status: "running",
  };
  const mcp = {
    id: "m1",
    kind: "mcpToolCall",
    label: "MCP · docs / search",
    status: "running",
  };
  const send = (activities: unknown[]) =>
    f.emit({
      type: "turn.activity",
      turn_id: "t1",
      status: "running",
      content: "Checking the project",
      activities,
    });
  send([command]);
  await expect(page.locator(".activity-current")).toHaveText(
    "Command — Running",
  );
  send([{ ...command, status: "completed" }, mcp]);
  await expect(page.locator(".activity-current")).toHaveText(
    "MCP · docs / search — Running",
  );
  await expect(
    page.getByText("Checking the project", { exact: true }),
  ).toHaveCount(1);
  await page.locator(".turn-activity summary").click();
  await expect(page.locator(".turn-activity li")).toHaveText(
    "✓ Command — Completed",
  );
  const count = f.connections;
  f.disconnect();
  await expect.poll(() => f.connections).toBeGreaterThan(count);
  send([{ ...command, status: "completed" }, mcp]);
  await expect(page.locator(".activity-current")).toHaveCount(1);
  const activities = [
    { ...command, status: "completed" },
    { ...mcp, status: "failed" },
  ];
  f.setMessages([
    {
      role: "assistant",
      turn_id: "t1",
      content: "Finished checking",
      status: "completed",
      activities,
    },
  ]);
  f.emit({
    type: "turn.completed",
    turn_id: "t1",
    status: "completed",
    content: "Finished checking",
    activities,
  });
  await expect(page.locator(".activity-current")).toHaveCount(0);
  await expect(page.locator(".turn-activity summary")).toHaveText(
    "2 recent actions · errors",
  );
  await page.reload();
  await page.locator(".turn-activity summary").click();
  await expect(page.locator(".turn-activity li")).toHaveCount(2);
  await expect(
    page.locator(".turn-activity li[data-status=failed]"),
  ).toContainText("MCP · docs / search — Failed");
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(
    390,
  );
  await page.screenshot({
    path: "test-results/mobile-tool-activity.png",
    fullPage: true,
  });
});
test("addressable chat restores settings, navigation, browser history and unavailable links", async ({
  page,
}) => {
  const f = await fixture(page);
  await page.goto("/projects/p1/chats/s1");
  await expect(page.locator("#messages")).toContainText("Earlier answer");
  await page.reload();
  await expect(page.locator("#session-title")).toHaveText(
    "Existing conversation",
  );
  await expect(page.locator("#project-form")).toHaveCount(0);
  await expect(page.locator(".project-list")).toHaveCount(0);
  await page.locator("#chat-settings summary").click();
  await expect(page.locator("select[name=model]")).toHaveValue("test-model");
  await expect(page.locator("select[name=sandbox]")).toHaveValue("read_only");
  expect(f.creates).toBe(0);
  await page.getByRole("button", { name: "Open navigation" }).click();
  await page
    .getByRole("link", { name: "Example project", exact: true })
    .click();
  await expect(page).toHaveURL(/\/projects\/p1$/);
  await page.goBack();
  await expect(page.locator("#messages")).toContainText("Earlier answer");
  await page.goto("/projects/p1/chats/missing");
  await expect(page).toHaveURL("/");
  await expect(page.getByRole("alert")).toContainText("no longer available");
  expect(f.creates).toBe(0);
});
test("live send, cumulative updates, reconnect replay and completion stay unique", async ({
  page,
}) => {
  const f = await fixture(page);
  await page.goto("/projects/p1/chats/s1");
  await expect(page.getByRole("status")).toHaveText("Live");
  await page.getByLabel("Message", { exact: true }).fill("A new instruction");
  await page.getByRole("button", { name: "Send", exact: true }).click();
  await expect.poll(() => f.posts).toBe(1);
  f.emit({
    type: "turn.delta",
    turn_id: "t1",
    status: "running",
    content: "Partial response",
  });
  await expect(page.locator("#messages")).toContainText("Partial response");
  await expect(
    page.getByRole("button", { name: "Send", exact: true }),
  ).toBeDisabled();
  const count = f.connections;
  f.disconnect();
  await expect.poll(() => f.connections).toBeGreaterThan(count);
  f.emit({
    type: "turn.delta",
    turn_id: "t1",
    status: "running",
    content: "Partial response",
  });
  await expect(page.getByText("Partial response", { exact: true })).toHaveCount(
    1,
  );
  f.finish();
  f.emit({
    type: "turn.completed",
    turn_id: "t1",
    status: "completed",
    content: "Completed response",
    rendered_content: "<p>Completed response</p>",
  });
  await expect(
    page.getByText("Completed response", { exact: true }),
  ).toHaveCount(1);
  await expect(page.getByText("Partial response", { exact: true })).toHaveCount(
    0,
  );
  await expect(
    page.getByText("A new instruction", { exact: true }),
  ).toHaveCount(1);
  f.emit({
    type: "turn.failed",
    turn_id: "failed",
    status: "failed",
    content: "Agent failed",
  });
  await expect(page.getByText("Agent failed", { exact: true })).toBeVisible();
  await page.reload();
  await expect(
    page.getByText("Completed response", { exact: true }),
  ).toHaveCount(1);
});
test("mobile drawer leaves full chat width and new chat is created only on submit", async ({
  page,
}) => {
  const f = await fixture(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/projects/p1/chats/s1");
  await expect(page.locator("#messages")).toContainText("Earlier answer");
  const width = await page
    .locator("#chat")
    .evaluate((el) => el.getBoundingClientRect().width);
  expect(width).toBe(390);
  await page.getByRole("button", { name: "Open navigation" }).click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page
    .getByRole("button", { name: "New chat in Example project" })
    .click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(page).toHaveURL(/\/chats\/new$/);
  expect(f.creates).toBe(0);
  await page.getByLabel("Message", { exact: true }).fill("A new instruction");
  await page.getByRole("button", { name: "Send", exact: true }).click();
  await expect(page).toHaveURL(/\/chats\/s2$/);
  expect(f.creates).toBe(1);
  expect(f.posts).toBe(1);
  await page.reload();
  await expect(page.locator("#messages")).toContainText("A new instruction");
  expect(f.creates).toBe(1);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(
    390,
  );
});
