import type { Activity } from "./api";

function label(item: Activity) {
  const status = {
    running: "Running",
    completed: "Completed",
    failed: "Failed",
    interrupted: "Interrupted",
  };
  return `${item.label} — ${status[item.status]}`;
}

export function TurnActivity({
  items = [],
  running,
}: {
  items?: Activity[];
  running: boolean;
}) {
  if (!items.length) return null;
  const normalized = items.map((item) =>
    !running && item.status === "running"
      ? { ...item, status: "interrupted" as const }
      : item,
  );
  const active = normalized.filter((item) => item.status === "running");
  const finished = normalized.filter((item) => item.status !== "running");
  return (
    <div className="turn-activity">
      <div role="status" aria-live="polite" aria-atomic="true">
        {active.length > 0 && (
          <div className="activity-current">
            <span className="activity-spinner" aria-hidden="true" />
            {label(active[active.length - 1])}
            {active.length > 1 && ` (+${active.length - 1} active)`}
          </div>
        )}
      </div>
      {finished.length > 0 && (
        <details>
          <summary>
            {finished.length} recent actions
            {finished.some((item) => item.status === "failed")
              ? " · errors"
              : ""}
          </summary>
          <ul>
            {finished.map((item) => (
              <li key={item.id} data-status={item.status}>
                <span aria-hidden="true">
                  {item.status === "completed"
                    ? "✓"
                    : item.status === "failed"
                      ? "!"
                      : "–"}
                </span>{" "}
                {label(item)}
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}
