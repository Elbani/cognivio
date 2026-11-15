import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";

const css = `
.d44{color:#111;font-family:-apple-system,"Helvetica Neue",Helvetica,Arial,sans-serif;font-size:18px;line-height:1.5;background:#fff;height:100vh;height:100dvh;overflow-y:auto;overflow-x:hidden;scroll-snap-type:y mandatory;scroll-behavior:smooth;position:relative}
.d44-s{height:100vh;height:100dvh;scroll-snap-align:start;scroll-snap-stop:always;display:flex;flex-direction:column;overflow:hidden}
.d44-s.o{padding-top:0}
.d44 *{box-sizing:border-box}
.d44-nav{width:100%;max-width:1180px;margin:0 auto;padding:22px 0;flex:none;display:flex;justify-content:space-between;align-items:center;font-size:15px}
.d44-nav b{font-size:17px}
.d44-nav a{color:inherit;margin-left:20px;text-decoration:none;border-bottom:1px solid currentColor;padding-bottom:1px}
.d44-s{padding:0 24px}
.d44-s.o{background:#fff;color:#111}
.d44-s.a{background:#f3efe4;color:#111}
.d44-s.b{background:#111;color:#fff}
.d44-s.c{background:#e7eef4;color:#111}
.d44-s.e{background:#e9f0e6;color:#111}
.d44-s.d{background:#fff;color:#111}
.d44-in{width:100%;max-width:1180px;margin:0 auto;flex:1;min-height:0;display:grid;grid-template-columns:minmax(0,1.3fr) minmax(0,1fr);gap:56px;align-items:center;padding:24px 0 48px}
.d44-left{container-type:inline-size;min-width:0}
.d44-step{font-size:14px;letter-spacing:.12em;text-transform:uppercase;opacity:.55;margin:0 0 14px;font-weight:600}
.d44-word{font-size:clamp(64px,var(--w,34cqw),230px);font-weight:700;letter-spacing:-.05em;line-height:.88;margin:0;white-space:nowrap}
.d44-txt{max-width:460px}
.d44-txt p{font-size:clamp(20px,2.1vw,26px);line-height:1.35;margin:0 0 14px}
.d44-txt p:last-child{margin:0}
.d44-list{list-style:none;margin:0;padding:0}
.d44-list li{font-size:clamp(17px,1.7vw,21px);line-height:1.35;padding:10px 0;border-top:1px solid rgba(0,0,0,.15)}
.d44-list li:last-child{border-bottom:1px solid rgba(0,0,0,.15)}
.d44-list b{font-weight:700;display:block}
.d44-s.d .d44-in,.d44-s.o .d44-in{grid-template-columns:1fr;justify-items:center;text-align:center;align-content:center;gap:28px}
.d44-s.d .d44-txt,.d44-s.o .d44-txt{max-width:560px}
.d44-s.d .d44-word{font-size:clamp(40px,7vw,96px);letter-spacing:-.035em;line-height:1;white-space:normal}
.d44-s.o .d44-word{font-size:clamp(44px,8.5vw,124px);letter-spacing:-.045em;line-height:.95;white-space:normal;max-width:1000px}
.d44-cta{display:flex;gap:14px;flex-wrap:wrap;justify-content:center;margin-top:34px}
.d44-cta a,.d44-cta button{font:inherit;font-size:17px;padding:13px 24px;border:1.5px solid #111;background:#111;color:#fff;text-decoration:none;cursor:pointer;border-radius:4px}
.d44-cta button{background:#fff;color:#111}
.d44-cta button:disabled{opacity:.5}
.d44-fine{font-size:15px;color:#666;margin-top:30px}
.d44-fine a{color:#666}
.d44-dots{position:fixed;right:18px;top:50%;transform:translateY(-50%);display:flex;flex-direction:column;gap:10px;z-index:3}
.d44-dots button{width:10px;height:10px;border-radius:50%;border:1.5px solid currentColor;background:transparent;padding:0;cursor:pointer;color:#111;opacity:.45}
.d44-dots button.on{background:currentColor;opacity:1}
.d44-dots.dark button{color:#fff}
.d44-next{position:fixed;left:50%;bottom:18px;transform:translateX(-50%);z-index:3;background:none;border:0;cursor:pointer;color:#111;opacity:.5;font-size:26px;line-height:1;padding:6px 10px;animation:d44bob 1.8s ease-in-out infinite}
.d44-next.dark{color:#fff}
@keyframes d44bob{0%,100%{transform:translate(-50%,0)}50%{transform:translate(-50%,6px)}}
@media(prefers-reduced-motion:reduce){.d44{scroll-behavior:auto}.d44-next{animation:none}}
@media(max-width:720px){.d44-in{grid-template-columns:1fr;gap:22px;padding:10px 0 56px;align-content:center}.d44-word{font-size:clamp(48px,var(--w,34cqw),110px)}.d44-txt p{font-size:18px;line-height:1.4}.d44-dots{right:10px}.d44-s.d .d44-word,.d44-s.o .d44-word{font-size:clamp(34px,9vw,64px)}.d44-list li{font-size:15.5px;padding:7px 0}.d44-list b{display:inline}}
`;

export default function Landing() {
  const [active, setActive] = useState(0);
  const root = useRef<HTMLDivElement>(null);
  const DARK = [false, false, true, false, false, false];

  useEffect(() => {
    const el = root.current;
    if (!el) return;
    const sections = Array.from(el.querySelectorAll<HTMLElement>(".d44-s"));
    const io = new IntersectionObserver(
      (entries) => {
        entries.forEach((e) => {
          if (e.isIntersecting) setActive(sections.indexOf(e.target as HTMLElement));
        });
      },
      { root: el, threshold: 0.6 }
    );
    sections.forEach((sct) => io.observe(sct));
    return () => io.disconnect();
  }, []);

  function go(i: number) {
    const el = root.current;
    if (!el) return;
    const sections = el.querySelectorAll<HTMLElement>(".d44-s");
    const target = sections[Math.max(0, Math.min(sections.length - 1, i))];
    target?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "ArrowDown" || e.key === "PageDown") { e.preventDefault(); go(active + 1); }
      if (e.key === "ArrowUp" || e.key === "PageUp") { e.preventDefault(); go(active - 1); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [active]);

  return (
    <div className="d44" ref={root}>
      <style>{css}</style>
      <div className={"d44-dots" + (DARK[active] ? " dark" : "")}>
        {[0, 1, 2, 3, 4, 5].map((i) => <button key={i} type="button" className={i === active ? "on" : ""} onClick={() => go(i)} aria-label={`screen ${i + 1}`} />)}
      </div>
      {active < 5 && <button type="button" className={"d44-next" + (DARK[active] ? " dark" : "")} onClick={() => go(active + 1)} aria-label="next screen">↓</button>}

      <section className="d44-s o">
        <nav className="d44-nav"><b>Cognivio</b><span><Link to="/login">Log in</Link><Link to="/register">Sign up</Link></span></nav>
        <div className="d44-in">
          <h1 className="d44-word">Memory for AI coding tools.</h1>
          <div className="d44-txt">
            <p>Claude Code, Cursor and Codex forget your project every session. Cognivio is where they keep what they learn.</p>
            <p>Three steps. Scroll.</p>
          </div>
        </div>
      </section>

      <section className="d44-s a">
        <div className="d44-in">
          <div className="d44-left"><div className="d44-step">Before the work</div><h2 className="d44-word" style={{ ["--w" as string]: "38cqw" }}>Read.</h2></div>
          <div className="d44-txt">
            <p>Before it touches a file, your tool reads your team's notes. The decisions, the gotchas, the layout.</p>
            <p>Then it gets to work, already knowing the project.</p>
          </div>
        </div>
      </section>

      <section className="d44-s b">
        <div className="d44-in">
          <div className="d44-left"><div className="d44-step">After the work</div><h2 className="d44-word" style={{ ["--w" as string]: "33cqw" }}>Write.</h2></div>
          <div className="d44-txt">
            <p>When it is done, it writes a short note about what it learned.</p>
            <p>One note per topic. Old notes get updated, not repeated.</p>
          </div>
        </div>
      </section>

      <section className="d44-s c">
        <div className="d44-in">
          <div className="d44-left"><div className="d44-step">Next time</div><h2 className="d44-word" style={{ ["--w" as string]: "38cqw" }}>Know.</h2></div>
          <div className="d44-txt">
            <p>What it learns today, it knows tomorrow. So does every other tool on your team.</p>
            <p>Nothing gets explained twice. The notes outlast the session, the branch, and the person who wrote them.</p>
          </div>
        </div>
      </section>

      <section className="d44-s e">
        <div className="d44-in">
          <div className="d44-left"><div className="d44-step">What you get</div><h2 className="d44-word" style={{ ["--w" as string]: "42cqw" }}>Why.</h2></div>
          <div className="d44-txt">
            <ul className="d44-list">
              <li><b>Lower bills.</b> Every file your tool re-reads costs tokens. A few notes cost far less than the whole project.</li>
              <li><b>Less waiting.</b> It gets to work in seconds instead of reading around for minutes.</li>
              <li><b>Fewer repeat mistakes.</b> A choice you made once stays made. No more undoing a refactor you never asked for.</li>
              <li><b>One shared memory.</b> Everyone's tool knows the same things. New teammates too.</li>
              <li><b>Notes you can trust.</b> Wrong ones get flagged. Old ones get checked.</li>
            </ul>
          </div>
        </div>
      </section>

      <section className="d44-s d">
        <div className="d44-in">
          <h2 className="d44-word">Your team's memory, in one place.</h2>
          <div className="d44-txt">
            <p>Setup takes two minutes. Your tool writes the first notes itself. You fix the mistakes.</p>
            <p>Your code stays with you. Free for one person.</p>
          </div>
          <div className="d44-cta">
            <Link to="/register">Create a free account</Link>
          </div>
        </div>
      </section>
    </div>
  );
}
