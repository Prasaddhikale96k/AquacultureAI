export default function EngineBadge({ engine, detail, live }: { engine: string; detail?: string | null; live: boolean }) {
  return (
    <span role="status" aria-label={`Detection engine: ${engine}`} title={detail ?? undefined}
      className="inline-flex items-center gap-2 rounded-full border border-[var(--border-subtle)] bg-[var(--surface-1)] px-2.5 py-1 text-[11px] font-medium text-[var(--text-secondary)]">
      <span aria-hidden className={`h-1.5 w-1.5 rounded-full ${live ? "bg-[var(--success)]" : "bg-[var(--text-secondary)]/50"}`} />
      <span className="text-[var(--text-primary)]">{engine}</span>
      {detail && <span className="hidden max-w-40 truncate sm:inline">{detail}</span>}
    </span>
  );
}
