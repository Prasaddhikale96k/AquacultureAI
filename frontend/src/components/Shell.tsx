import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { AnimatePresence, motion } from "framer-motion";
import {
  Bell,
  Droplets,
  Fish,
  LayoutDashboard,
  LogOut,
  Menu,
  PanelLeftClose,
  PanelLeftOpen,
  RefreshCw,
  ScanEye,
  TrendingUp,
  Waves,
  X,
  type LucideIcon,
} from "lucide-react";
import clsx from "clsx";
import type { AuthUser } from "../types";
import { useT } from "../i18n/LanguageProvider";
import { AppearanceControls } from "./shared/AppearanceControls";
import { springSoft } from "../motion/variants";

export type Page = "overview" | "monitoring" | "sensors" | "water" | "alerts" | "predictions" | "behavior";

export const PAGES: { id: Page; icon: LucideIcon }[] = [
  { id: "overview", icon: LayoutDashboard },
  { id: "monitoring", icon: ScanEye },
  { id: "sensors", icon: Waves },
  { id: "water", icon: Droplets },
  { id: "alerts", icon: Bell },
  { id: "predictions", icon: TrendingUp },
  { id: "behavior", icon: Fish },
];

const MOBILE_PRIMARY: Page[] = ["overview", "monitoring", "sensors", "alerts"];

export type Tone = "ok" | "warn" | "bad" | "mute";
export interface StatusItem { label: string; value: string; tone: Tone }

const DOT: Record<Tone, string> = {
  ok: "bg-[var(--success)]",
  warn: "bg-[var(--warning)]",
  bad: "bg-[var(--critical)]",
  mute: "bg-[var(--text-secondary)]/60",
};

const COLLAPSE_KEY = "aqua:nav-collapsed";
const hms = (t: number) => new Date(t).toLocaleTimeString([], { hour12: false });

function initials(name?: string) {
  const parts = (name ?? "").trim().split(/\s+/).filter(Boolean);
  if (!parts.length) return "F";
  return (parts[0][0] + (parts.length > 1 ? parts[parts.length - 1][0] : "")).toUpperCase();
}

export default function Shell({
  page,
  setPage,
  status,
  fetchedAt,
  lastReadingAt,
  pollSeconds,
  canRefresh,
  busy,
  onRefresh,
  user,
  onLogout,
  children,
}: {
  page: Page;
  setPage: (p: Page) => void;
  status: StatusItem[];
  fetchedAt: number | null;
  lastReadingAt: number | null;
  pollSeconds: number;
  canRefresh: boolean;
  busy: boolean;
  onRefresh: () => void;
  user: AuthUser;
  onLogout: () => void;
  children: ReactNode;
}) {
  const t = useT();
  const [collapsed, setCollapsed] = useState(() => localStorage.getItem(COLLAPSE_KEY) === "1");
  const [drawer, setDrawer] = useState(false);
  const closeRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    localStorage.setItem(COLLAPSE_KEY, collapsed ? "1" : "0");
  }, [collapsed]);

  useEffect(() => {
    if (!drawer) return;
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setDrawer(false);
    };
    window.addEventListener("keydown", onKey);
    const id = window.setTimeout(() => closeRef.current?.focus(), 80);
    return () => {
      document.body.style.overflow = previous;
      window.removeEventListener("keydown", onKey);
      window.clearTimeout(id);
    };
  }, [drawer]);

  const title = t(`shell.${page}Title`);
  const subtitle = user.tankId ? `${t("shell.tank")} ${user.tankId}` : t("app.subtitle");
  const phone = user.phone ? `${user.phone.slice(0, 4)}••••${user.phone.slice(-3)}` : t("shell.signedIn");
  const liveLabel = t("shell.live", { seconds: pollSeconds });

  const navigate = (id: Page) => {
    setPage(id);
    setDrawer(false);
  };

  const navItem = (id: Page, variant: "sidebar" | "drawer") => {
    const Icon = PAGES.find((p) => p.id === id)!.icon;
    const active = page === id;
    return (
      <button
        key={id}
        type="button"
        onClick={() => navigate(id)}
        aria-current={active ? "page" : undefined}
        title={variant === "sidebar" && collapsed ? t(`shell.${id}`) : undefined}
        className={clsx(
          "group relative flex h-10 w-full items-center gap-3 rounded-nested px-3 text-sm transition-colors",
          active
            ? "text-[var(--text-primary)]"
            : "text-[var(--text-secondary)] hover:bg-[var(--surface-2)] hover:text-[var(--text-primary)]",
          variant === "sidebar" && collapsed && "justify-center px-0"
        )}
      >
        {active && (
          <motion.span
            layoutId={variant === "sidebar" ? "nav-indicator" : undefined}
            className="absolute inset-0 rounded-nested border border-[var(--accent)]/25 bg-[var(--accent)]/10"
            transition={springSoft}
          />
        )}
        <Icon className="relative z-10 h-[18px] w-[18px] shrink-0" aria-hidden />
        <span className={clsx("relative z-10 truncate", variant === "sidebar" && collapsed && "sr-only")}>
          {t(`shell.${id}`)}
        </span>
      </button>
    );
  };

  const statusList = (vertical = true) => (
    <ul className={clsx("space-y-1.5", !vertical && "flex flex-wrap items-center gap-x-3 gap-y-1.5 space-y-0")}>
      {status.map((item) => (
        <li
          key={item.label}
          title={`${item.label}: ${item.value}`}
          className={clsx(
            "flex items-center gap-2 text-[11px] text-[var(--text-secondary)]",
            vertical ? "justify-between" : ""
          )}
        >
          <span className="flex min-w-0 items-center gap-1.5">
            <span className={clsx("h-1.5 w-1.5 shrink-0 rounded-full", DOT[item.tone])} aria-hidden />
            <span className="truncate">{item.label}</span>
          </span>
          {vertical && (
            <span className="shrink-0 font-medium text-[var(--text-primary)]">{item.value}</span>
          )}
        </li>
      ))}
    </ul>
  );

  const userBlock = (compact: boolean) => (
    <div className={clsx("border-t border-[var(--border-subtle)] pt-3", compact && "px-1")}>
      {compact ? (
        <div className="flex flex-col items-center gap-2">
          <span
            title={user.name || t("shell.farmer")}
            className="grid h-8 w-8 place-items-center rounded-full bg-[var(--accent)]/15 text-[11px] font-semibold text-[var(--accent)]"
          >
            {initials(user.name)}
          </span>
          <button
            type="button"
            onClick={onLogout}
            aria-label={t("auth.logout")}
            title={t("auth.logout")}
            className="grid h-8 w-8 place-items-center rounded-nested text-[var(--text-secondary)] hover:bg-[var(--surface-2)] hover:text-[var(--text-primary)]"
          >
            <LogOut className="h-4 w-4" aria-hidden />
          </button>
        </div>
      ) : (
        <div className="flex items-center gap-2.5">
          <span className="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-[var(--accent)]/15 text-xs font-semibold text-[var(--accent)]">
            {initials(user.name)}
          </span>
          <div className="min-w-0 flex-1">
            <p className="truncate text-xs font-semibold text-[var(--text-primary)]">{user.name || t("shell.farmer")}</p>
            <p className="nums truncate text-[11px] text-[var(--text-secondary)]">{phone}</p>
          </div>
          <button
            type="button"
            onClick={onLogout}
            aria-label={t("auth.logout")}
            title={t("auth.logout")}
            className="grid h-8 w-8 shrink-0 place-items-center rounded-nested text-[var(--text-secondary)] hover:bg-[var(--surface-2)] hover:text-[var(--text-primary)]"
          >
            <LogOut className="h-4 w-4" aria-hidden />
          </button>
        </div>
      )}
    </div>
  );

  const drawerContent = useMemo(() => {
    if (!drawer) return null;
    return (
      <motion.aside
        role="dialog"
        aria-modal="true"
        aria-label={t("shell.pagesNav")}
        initial={{ x: "-100%" }}
        animate={{ x: 0 }}
        exit={{ x: "-100%" }}
        transition={springSoft}
        className="fixed inset-y-0 left-0 z-50 flex w-[86%] max-w-xs flex-col border-r border-[var(--border-subtle)] bg-[var(--surface-1)] p-4 shadow-2xl lg:hidden"
      >
        <div className="mb-5 flex items-center justify-between">
          <a href="#/overview" onClick={() => setDrawer(false)} className="flex items-center gap-2.5 text-[var(--text-primary)]">
            <span className="grid h-9 w-9 place-items-center rounded-xl bg-[var(--accent)]/12 text-[var(--accent)]">
              <Fish className="h-5 w-5" aria-hidden />
            </span>
            <span className="font-display text-sm font-semibold">
              Aquaculture<span className="text-[var(--accent)]">AI</span>
            </span>
          </a>
          <button
            ref={closeRef}
            type="button"
            onClick={() => setDrawer(false)}
            aria-label={t("shell.closeMenu")}
            className="grid h-9 w-9 place-items-center rounded-nested text-[var(--text-secondary)] hover:bg-[var(--surface-2)] hover:text-[var(--text-primary)]"
          >
            <X className="h-5 w-5" aria-hidden />
          </button>
        </div>

        <nav className="space-y-1" aria-label={t("shell.pagesNav")}>
          {PAGES.map((p) => navItem(p.id, "drawer"))}
        </nav>

        <div className="mt-auto space-y-4 pt-4">
          <div className="rounded-nested border border-[var(--border-subtle)] bg-[var(--surface-2)]/60 p-3">
            <p className="mb-2 text-[10px] font-semibold uppercase tracking-[0.16em] text-[var(--text-secondary)]">
              {t("shell.integrations")}
            </p>
            {statusList()}
          </div>
          <AppearanceControls />
          {userBlock(false)}
        </div>
      </motion.aside>
    );
  }, [drawer, page, collapsed, status, user]);

  return (
    <div className="min-h-screen bg-[var(--surface-0)] text-[var(--text-primary)]">
      <a
        href="#main-content"
        className="sr-only rounded-nested bg-[var(--accent)] px-3 py-2 text-sm font-semibold text-[var(--accent-contrast)] focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-[60]"
      >
        {t("shell.skipToContent")}
      </a>

      <motion.aside
        initial={false}
        animate={{ width: collapsed ? 76 : 248 }}
        transition={springSoft}
        className="fixed inset-y-0 left-0 z-40 hidden flex-col border-r border-[var(--border-subtle)] bg-[var(--surface-1)] p-3 lg:flex"
        aria-label={t("shell.primaryNav")}
      >
        <div className={clsx("mb-5 flex items-center gap-2.5", collapsed ? "justify-center" : "px-1")}>
          <span className="grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-[var(--accent)]/12 text-[var(--accent)]">
            <Fish className="h-5 w-5" aria-hidden />
          </span>
          {!collapsed && (
            <span className="truncate font-display text-sm font-semibold tracking-tight">
              Aquaculture<span className="text-[var(--accent)]">AI</span>
            </span>
          )}
        </div>

        <nav className="space-y-1" aria-label={t("shell.pagesNav")}>
          {PAGES.map((p) => navItem(p.id, "sidebar"))}
        </nav>

        <div className="mt-auto space-y-3">
          {!collapsed && (
            <div>
              <p className="mb-2 px-1 text-[10px] font-semibold uppercase tracking-[0.16em] text-[var(--text-secondary)]">
                {t("shell.integrations")}
              </p>
              {statusList()}
            </div>
          )}
          {userBlock(collapsed)}
        </div>

        <button
          type="button"
          onClick={() => setCollapsed((value) => !value)}
          aria-label={collapsed ? t("nav.expand") : t("nav.collapse")}
          title={collapsed ? t("nav.expand") : t("nav.collapse")}
          className={clsx(
            "mt-3 grid h-9 w-full place-items-center rounded-nested text-[var(--text-secondary)] transition-colors hover:bg-[var(--surface-2)] hover:text-[var(--text-primary)]",
            collapsed && "w-9 self-center"
          )}
        >
          {collapsed ? <PanelLeftOpen className="h-4 w-4" aria-hidden /> : <PanelLeftClose className="h-4 w-4" aria-hidden />}
        </button>
      </motion.aside>

      <div className={clsx("min-h-screen min-w-0 transition-[padding] duration-300", collapsed ? "lg:pl-[76px]" : "lg:pl-[248px]")}>
        <header className="sticky top-0 z-30 border-b border-[var(--border-subtle)] bg-[var(--surface-0)]/85 backdrop-blur-md">
          <div className="mx-auto flex h-16 max-w-[1600px] items-center gap-3 px-4 sm:px-6">
            <button
              type="button"
              onClick={() => setDrawer(true)}
              aria-label={t("shell.openMenu")}
              aria-expanded={drawer}
              className="grid h-9 w-9 shrink-0 place-items-center rounded-nested text-[var(--text-secondary)] hover:bg-[var(--surface-2)] hover:text-[var(--text-primary)] lg:hidden"
            >
              <Menu className="h-5 w-5" aria-hidden />
            </button>

            <div className="min-w-0">
              <h1 className="truncate font-display text-base font-semibold tracking-tight sm:text-lg">{title}</h1>
              <p className="hidden truncate text-[11px] text-[var(--text-secondary)] sm:block">{subtitle}</p>
            </div>

            <div className="ml-auto flex items-center gap-2">
              <div className="hidden items-center gap-2 2xl:flex">{statusList(false)}</div>

              {canRefresh && (
                <span className="hidden items-center gap-1.5 rounded-full border border-[var(--success)]/25 bg-[var(--success)]/10 px-2.5 py-1 text-[10px] font-medium text-[var(--success)] sm:inline-flex">
                  <span className="h-1.5 w-1.5 rounded-full bg-[var(--success)]" aria-hidden />
                  {liveLabel}
                </span>
              )}

              <span className="hidden text-[11px] text-[var(--text-secondary)] xl:inline" title={t("shell.updated")}>
                {fetchedAt ? (
                  <>
                    {t("shell.updated")} <b className="font-semibold text-[var(--text-primary)]">{hms(fetchedAt)}</b>
                    {lastReadingAt ? (
                      <>
                        {" · "}
                        {t("shell.lastReading")}{" "}
                        <b className="font-semibold text-[var(--text-primary)]">{hms(lastReadingAt)}</b>
                      </>
                    ) : null}
                  </>
                ) : (
                  t("shell.noFetch")
                )}
              </span>

              <AppearanceControls compact />

              <button
                type="button"
                onClick={onRefresh}
                disabled={!canRefresh || busy}
                aria-label={t("shell.refreshAria")}
                className="inline-flex h-9 items-center gap-2 rounded-nested bg-[var(--accent)] px-2.5 text-xs font-semibold text-[var(--accent-contrast)] transition-colors hover:bg-[var(--accent-strong)] hover:text-white disabled:cursor-not-allowed disabled:opacity-50 sm:px-3"
              >
                <RefreshCw className={clsx("h-4 w-4", busy && "animate-spin")} aria-hidden />
                <span className="hidden sm:inline">{t("shell.refresh")}</span>
              </button>
            </div>
          </div>
        </header>

        <main id="main-content" className="mx-auto min-w-0 max-w-[1600px] overflow-x-clip px-4 pb-28 pt-5 sm:px-6 lg:pb-10">
          {children}
        </main>
      </div>

      <nav
        className="fixed inset-x-0 bottom-0 z-40 border-t border-[var(--border-subtle)] bg-[var(--surface-1)]/95 pb-[env(safe-area-inset-bottom)] backdrop-blur-md lg:hidden"
        aria-label={t("shell.mobileNav")}
      >
        <div className="grid grid-cols-5">
          {MOBILE_PRIMARY.map((id) => {
            const Icon = PAGES.find((p) => p.id === id)!.icon;
            const active = page === id;
            return (
              <button
                key={id}
                type="button"
                onClick={() => setPage(id)}
                aria-current={active ? "page" : undefined}
                className={clsx(
                  "flex flex-col items-center gap-0.5 py-2 text-[10px] transition-colors",
                  active ? "font-semibold text-[var(--accent)]" : "text-[var(--text-secondary)]"
                )}
              >
                <Icon className="h-5 w-5" aria-hidden />
                {t(`shell.${id}`)}
              </button>
            );
          })}
          <button
            type="button"
            onClick={() => setDrawer(true)}
            aria-expanded={drawer}
            className="flex flex-col items-center gap-0.5 py-2 text-[10px] text-[var(--text-secondary)]"
          >
            <Menu className="h-5 w-5" aria-hidden />
            {t("shell.more")}
          </button>
        </div>
      </nav>

      <AnimatePresence>
        {drawer && (
          <>
            <motion.div
              key="scrim"
              className="fixed inset-0 z-50 bg-black/55 backdrop-blur-[2px] lg:hidden"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              onClick={() => setDrawer(false)}
              aria-hidden
            />
            {drawerContent}
          </>
        )}
      </AnimatePresence>
    </div>
  );
}
