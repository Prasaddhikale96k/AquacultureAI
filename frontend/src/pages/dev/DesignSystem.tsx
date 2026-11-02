import { useState } from "react";
import { motion } from "framer-motion";
import { Copy, Droplets, Fish, Info, Sparkles } from "lucide-react";
import { Card, CardBody, CardHeader } from "../../components/ui/Card";
import { Button } from "../../components/ui/Button";
import { Pill } from "../../components/ui/Pill";
import { Skeleton } from "../../components/ui/Skeleton";
import { useToast } from "../../components/ui/Toast";
import { AppearanceControls } from "../../components/shared/AppearanceControls";
import { useT } from "../../i18n/LanguageProvider";
import { fadeUp, listStagger, scaleIn } from "../../motion/variants";

const SURFACES = [
  { token: "--surface-0", label: "surface-0", note: "page" },
  { token: "--surface-1", label: "surface-1", note: "card" },
  { token: "--surface-2", label: "surface-2", note: "nested" },
  { token: "--surface-3", label: "surface-3", note: "raised" },
];

const SEMANTICS = [
  { token: "--accent", label: "accent", note: "actions" },
  { token: "--success", label: "success", note: "safe" },
  { token: "--warn", label: "warn", note: "watch / risk" },
  { token: "--critical", label: "critical", note: "critical" },
  { token: "--info", label: "info", note: "provisional" },
];

export default function DesignSystem() {
  const t = useT();
  const { toast } = useToast();
  const [loading, setLoading] = useState(false);

  return (
    <div className="min-h-screen bg-[var(--surface-0)] text-[var(--text-primary)]">
      <header className="sticky top-0 z-20 border-b border-[var(--border-subtle)] bg-[var(--surface-0)]/85 backdrop-blur-md">
        <div className="mx-auto flex max-w-[1200px] flex-wrap items-center gap-3 px-6 py-4">
          <span className="grid h-9 w-9 place-items-center rounded-[10px] bg-[var(--accent)]/15">
            <Fish className="h-5 w-5 text-[var(--accent)]" aria-hidden />
          </span>
          <div className="mr-auto">
            <h1 className="font-display text-lg font-semibold leading-tight">{t("designSystem.title")}</h1>
            <p className="text-xs text-[var(--text-secondary)]">{t("designSystem.subtitle")}</p>
          </div>
          <AppearanceControls />
          <a
            href="#overview"
            className="inline-flex h-9 items-center rounded-nested border border-[var(--border-subtle)] px-3 text-xs font-medium text-[var(--text-secondary)] hover:bg-[var(--surface-2)] hover:text-[var(--text-primary)]"
          >
            {t("designSystem.backToApp")}
          </a>
        </div>
      </header>

      <motion.main
        variants={listStagger}
        initial="initial"
        animate="animate"
        className="mx-auto grid max-w-[1200px] grid-cols-1 gap-6 px-6 py-8 lg:grid-cols-12"
      >
        <motion.section variants={fadeUp} className="lg:col-span-12" aria-labelledby="swatches">
          <h2 id="swatches" className="mb-3 font-display text-sm font-semibold uppercase tracking-widest text-[var(--text-secondary)]">
            {t("designSystem.surfaces")}
          </h2>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            {SURFACES.map((s) => (
              <div key={s.token} className="rounded-card border border-[var(--border-subtle)] p-3" style={{ background: `var(${s.token})` }}>
                <div className="flex items-center justify-between">
                  <span className="font-display text-sm font-semibold">{s.label}</span>
                  <Droplets className="h-3.5 w-3.5 text-[var(--text-secondary)]" aria-hidden />
                </div>
                <p className="mt-1 text-[11px] text-[var(--text-secondary)]">{s.note}</p>
                <code className="mt-2 block text-[10px] text-[var(--text-secondary)]">{s.token}</code>
              </div>
            ))}
          </div>

          <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-5">
            {SEMANTICS.map((s) => (
              <div key={s.token} className="rounded-card border border-[var(--border-subtle)] bg-[var(--surface-1)] p-3">
                <span className="block h-10 w-full rounded-nested" style={{ background: `var(${s.token})` }} />
                <div className="mt-2 flex items-center justify-between gap-2">
                  <span className="font-display text-xs font-semibold">{s.label}</span>
                  <span className="text-[10px] text-[var(--text-secondary)]">{s.note}</span>
                </div>
              </div>
            ))}
          </div>
        </motion.section>

        <motion.section variants={fadeUp} className="lg:col-span-5" aria-labelledby="type">
          <Card className="h-full">
            <CardHeader title={t("designSystem.typography")} subtitle={t("designSystem.typographySub")} />
            <CardBody className="space-y-4">
              <div>
                <p className="text-[11px] uppercase tracking-widest text-[var(--text-secondary)]">Manrope · display</p>
                <p className="mt-1 font-display text-4xl font-semibold tracking-tight">
                  {t("designSystem.sampleDisplay")}
                </p>
              </div>
              <div>
                <p className="text-[11px] uppercase tracking-widest text-[var(--text-secondary)]">Inter · body</p>
                <p className="mt-1 text-sm leading-relaxed text-[var(--text-secondary)]">
                  {t("designSystem.sampleBody")}
                </p>
              </div>
              <div className="rounded-nested border border-[var(--border-subtle)] bg-[var(--surface-2)] p-3">
                <p className="text-[11px] uppercase tracking-widest text-[var(--text-secondary)]">
                  {t("designSystem.metric")}
                </p>
                <p className="nums font-display text-5xl font-semibold leading-none">
                  6.4 <span className="text-lg font-medium text-[var(--text-secondary)]">mg/L</span>
                </p>
              </div>
            </CardBody>
          </Card>
        </motion.section>

        <motion.section variants={fadeUp} className="lg:col-span-7" aria-labelledby="buttons">
          <Card className="h-full">
            <CardHeader title={t("designSystem.buttons")} subtitle={t("designSystem.buttonsSub")} />
            <CardBody className="space-y-5">
              <div className="flex flex-wrap items-center gap-2">
                <Button>{t("designSystem.primary")}</Button>
                <Button variant="secondary">{t("designSystem.secondary")}</Button>
                <Button variant="outline">{t("designSystem.outline")}</Button>
                <Button variant="danger">{t("designSystem.danger")}</Button>
                <Button variant="ghost">{t("designSystem.ghost")}</Button>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <Button size="sm" leftIcon={<Sparkles className="h-3.5 w-3.5" />}>
                  {t("designSystem.small")}
                </Button>
                <Button size="md" loading={loading} onClick={() => { setLoading(true); setTimeout(() => setLoading(false), 1200); }}>
                  {t("designSystem.loadingDemo")}
                </Button>
                <Button size="lg" variant="secondary" disabled>
                  {t("designSystem.disabled")}
                </Button>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <Button variant="secondary" onClick={() => toast("ok", t("designSystem.toastOk"))}>
                  {t("designSystem.toastSuccess")}
                </Button>
                <Button variant="secondary" onClick={() => toast("warn", t("designSystem.toastWarn"))}>
                  {t("designSystem.toastWarning")}
                </Button>
                <Button variant="secondary" onClick={() => toast("error", t("designSystem.toastError"))}>
                  {t("designSystem.toastErrorLabel")}
                </Button>
              </div>
            </CardBody>
          </Card>
        </motion.section>

        <motion.section variants={fadeUp} className="lg:col-span-12" aria-labelledby="pills">
          <Card>
            <CardHeader
              title={t("designSystem.pills")}
              subtitle={t("designSystem.pillsSub")}
              action={<Pill variant="info">PROVISIONAL</Pill>}
            />
            <CardBody>
              <div className="flex flex-wrap items-center gap-2">
                <Pill variant="neutral">{t("pills.normal")}</Pill>
                <Pill variant="success">{t("status.connected")}</Pill>
                <Pill variant="warn">{t("status.warning")}</Pill>
                <Pill variant="critical">{t("status.critical")}</Pill>
                <Pill variant="info">{t("status.live")}</Pill>
                <Pill variant="info" icon={<Info className="h-3 w-3" aria-hidden />}>EXPERIMENTAL</Pill>
              </div>
              <p className="mt-3 flex items-start gap-2 rounded-nested border border-[var(--border-subtle)] bg-[var(--surface-2)] p-3 text-xs text-[var(--text-secondary)]">
                <Info className="mt-0.5 h-4 w-4 shrink-0 text-[var(--info)]" aria-hidden />
                {t("designSystem.pillRule")}
              </p>
            </CardBody>
          </Card>
        </motion.section>

        <motion.section variants={fadeUp} className="lg:col-span-7" aria-labelledby="cards">
          <div className="grid gap-4 sm:grid-cols-2">
            <Card>
              <CardHeader title={t("designSystem.cardDefault")} subtitle={t("designSystem.cardDefaultSub")} />
              <CardBody className="text-sm text-[var(--text-secondary)]">{t("designSystem.cardBody")}</CardBody>
            </Card>
            <Card variant="nested">
              <CardHeader title={t("designSystem.cardNested")} subtitle={t("designSystem.cardNestedSub")} />
              <CardBody className="text-sm text-[var(--text-secondary)]">{t("designSystem.cardBody")}</CardBody>
            </Card>
            <Card variant="glass" className="sm:col-span-2">
              <CardBody className="flex items-center gap-3">
                <span className="grid h-10 w-10 place-items-center rounded-nested bg-[var(--accent)]/15">
                  <Copy className="h-5 w-5 text-[var(--accent)]" aria-hidden />
                </span>
                <div>
                  <p className="font-display text-sm font-semibold">{t("designSystem.cardGlass")}</p>
                  <p className="text-xs text-[var(--text-secondary)]">{t("designSystem.cardGlassSub")}</p>
                </div>
              </CardBody>
            </Card>
          </div>
        </motion.section>

        <motion.section variants={fadeUp} className="lg:col-span-5" aria-labelledby="loading">
          <Card className="h-full">
            <CardHeader title={t("designSystem.loading")} subtitle={t("designSystem.loadingSub")} />
            <CardBody className="space-y-3">
              <Skeleton className="h-6 w-2/3" />
              <Skeleton className="h-3 w-full" />
              <Skeleton className="h-3 w-5/6" />
              <div className="flex items-center gap-3 pt-1">
                <Skeleton circle className="h-10 w-10" />
                <div className="flex-1 space-y-2">
                  <Skeleton className="h-3 w-1/2" />
                  <Skeleton className="h-3 w-1/3" />
                </div>
              </div>
            </CardBody>
          </Card>
        </motion.section>

        <motion.section variants={scaleIn} className="lg:col-span-12">
          <div className="flex flex-wrap items-center gap-3 rounded-card border border-[var(--border-subtle)] bg-[var(--surface-1)] p-4 text-xs text-[var(--text-secondary)]">
            <Info className="h-4 w-4 text-[var(--info)]" aria-hidden />
            <span>{t("designSystem.motionNote")}</span>
          </div>
        </motion.section>
      </motion.main>
    </div>
  );
}
