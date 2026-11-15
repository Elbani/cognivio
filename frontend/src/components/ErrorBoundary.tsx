import { Component, CSSProperties, ErrorInfo, ReactNode } from "react";

type Props = { children: ReactNode };
type State = { error: Error | null };

function btnStyle(primary: boolean): CSSProperties {
  return {
    padding: "9px 16px",
    borderRadius: 7,
    border: primary ? "0" : "1px solid #2b3744",
    background: primary ? "#3ddc84" : "transparent",
    color: primary ? "#06140c" : "#cdd6e0",
    font: "inherit",
    fontWeight: 600,
    fontSize: 13,
    cursor: "pointer"
  };
}

/**
 * App-wide safety net: a render-time exception anywhere below this boundary is caught
 * and shown as a recoverable screen instead of white-screening the whole SPA (e.g. one
 * malformed doc taking down the entire workspace).
 */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // Surface it for debugging; there's no client-side error service by design.
    console.error("Unhandled UI error:", error, info.componentStack);
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div className="center-screen" role="alert" style={{ flexDirection: "column", gap: 16, textAlign: "center", padding: 24 }}>
        <h1 style={{ fontSize: 20, margin: 0 }}>Something went wrong</h1>
        <p style={{ color: "#7d8da0", maxWidth: 420, margin: 0 }}>
          An unexpected error broke this view. Reloading usually fixes it. If it keeps
          happening, please let us know what you were doing.
        </p>
        <div style={{ display: "flex", gap: 10 }}>
          <button onClick={() => window.location.reload()} style={btnStyle(true)}>
            Reload
          </button>
          <button onClick={() => window.location.assign("/app")} style={btnStyle(false)}>
            Back to workspace
          </button>
        </div>
      </div>
    );
  }
}
