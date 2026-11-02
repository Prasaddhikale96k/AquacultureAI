/** Decorative underwater backdrop: gradients, light rays and fish silhouettes (no image asset is bundled). */
const Fish = ({ x, y, s, o, flip }: { x: string; y: string; s: number; o: number; flip?: boolean }) => (
  <svg viewBox="0 0 120 50" className="absolute" style={{ left: x, top: y, width: s, opacity: o, transform: flip ? "scaleX(-1)" : undefined }} aria-hidden>
    <path d="M4 25c14-20 46-24 70-8l30-14-8 22 8 22-30-14C50 49 18 45 4 25Z" fill="#19c8f2" />
  </svg>
);

export default function Background() {
  return (
    <div aria-hidden className="pointer-events-none fixed inset-0 -z-10 overflow-hidden bg-abyss">
      <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_70%_-10%,#0c4a6e_0%,#06314a_35%,#031321_75%)]" />
      <div className="absolute inset-x-0 top-0 h-[520px] opacity-40 [background:repeating-linear-gradient(100deg,transparent_0_70px,rgb(25_200_242/0.10)_90px,transparent_130px)] [mask-image:linear-gradient(#000,transparent)]" />
      <div className="caustics absolute inset-0" />
      <Fish x="62%" y="9%" s={150} o={0.12} />
      <Fish x="74%" y="20%" s={90} o={0.1} flip />
      <Fish x="86%" y="6%" s={70} o={0.1} />
      <Fish x="52%" y="24%" s={60} o={0.07} flip />
      <div className="absolute inset-x-0 bottom-0 h-64 bg-gradient-to-t from-abyss to-transparent" />
    </div>
  );
}
