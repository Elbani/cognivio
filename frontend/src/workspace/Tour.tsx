import { useEffect, useLayoutEffect, useRef, useState } from "react";

type Placement = "center" | "right" | "left" | "top" | "bottom";
export type TourStep = { sel?: string; title: string; body: string; place?: Placement };

export function Tour({ steps, onFinish, onStep }: { steps: TourStep[]; onFinish: () => void; onStep?: (step: TourStep) => void }) {
  const [i, setI] = useState(0);
  const [rect, setRect] = useState<DOMRect | null>(null);
  const [pos, setPos] = useState<{ top: number; left: number }>({ top: -9999, left: -9999 });
  const tipRef = useRef<HTMLDivElement>(null);

  const step = steps[i];
  const place: Placement = step.place ?? (step.sel ? "right" : "center");
  const last = i >= steps.length - 1;

  const measureTarget = () => {
    const el = step.sel ? (document.querySelector(step.sel) as HTMLElement | null) : null;
    if (el) el.scrollIntoView({ block: "nearest" });
    setRect(el ? el.getBoundingClientRect() : null);
  };

  useLayoutEffect(measureTarget, [i, step.sel]);

  // Tell the workspace which step is showing, so it can open the menu drawer on a phone,
  // then measure again once the drawer has finished sliding.
  useEffect(() => {
    onStep?.(step);
    const t = window.setTimeout(measureTarget, 280);
    return () => window.clearTimeout(t);
  }, [i]);

  useLayoutEffect(() => {
    const tip = tipRef.current;
    if (!tip) return;
    const tw = tip.offsetWidth;
    const th = tip.offsetHeight;
    const vw = window.innerWidth, vh = window.innerHeight, m = 12, gap = 14;
    let top: number, left: number;
    // On a phone there is no room beside the target, so the tip goes under it, or over
    // it when it would not fit underneath.
    const narrow = vw < 700 && rect && place !== "center";
    if (!rect || place === "center") {
      top = (vh - th) / 2; left = (vw - tw) / 2;
    } else if (narrow) {
      left = rect.left;
      top = rect.bottom + gap + th <= vh - m ? rect.bottom + gap : rect.top - th - gap;
    } else if (place === "right") { left = rect.right + gap; top = rect.top; }
    else if (place === "left") { left = rect.left - tw - gap; top = rect.top; }
    else if (place === "bottom") { top = rect.bottom + gap; left = rect.left; }
    else { top = rect.top - th - gap; left = rect.left; }
    left = Math.max(m, Math.min(left, vw - tw - m));
    top = Math.max(m, Math.min(top, vh - th - m));
    setPos({ top, left });
  }, [rect, i, place]);

  useEffect(() => {
    const onResize = () => measureTarget();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onFinish();
      else if (e.key === "ArrowRight") next();
      else if (e.key === "ArrowLeft") setI((x) => Math.max(0, x - 1));
    };
    window.addEventListener("resize", onResize);
    window.addEventListener("keydown", onKey);
    return () => { window.removeEventListener("resize", onResize); window.removeEventListener("keydown", onKey); };
  });

  function next() { if (last) onFinish(); else setI(i + 1); }

  const spot = rect && place !== "center";
  const pad = 6;

  return (
    <div className="tour-root">
      <div className="tour-block" />
      {spot ? (
        <div
          className="tour-spot"
          style={{ left: rect!.left - pad, top: rect!.top - pad, width: rect!.width + pad * 2, height: rect!.height + pad * 2 }}
        />
      ) : (
        <div className="tour-dim" />
      )}
      <div className="tour-tip" ref={tipRef} style={{ top: pos.top, left: pos.left }}>
        <div className="tour-step-n">Step {i + 1} of {steps.length}</div>
        <h3>{step.title}</h3>
        <p>{step.body}</p>
        <div className="tour-foot">
          <button className="tour-skip" onClick={onFinish}>Skip</button>
          <span className="tour-dots">{steps.map((_, k) => <span key={k} className={k === i ? "on" : ""} />)}</span>
          <span style={{ flex: 1 }} />
          {i > 0 && <button className="ws-btn sm" onClick={() => setI(i - 1)}>Back</button>}
          <button className="ws-btn sm primary" onClick={next}>{last ? "Finish" : "Next"}</button>
        </div>
      </div>
    </div>
  );
}
