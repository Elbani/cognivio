import React from "react";
import ReactDOM from "react-dom/client";
import "highlight.js/styles/github.css";
import "./styles/app.css";
import "./styles/editorial.css";
import { App } from "./App";
import { ErrorBoundary } from "./components/ErrorBoundary";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <ErrorBoundary>
      <App />
    </ErrorBoundary>
  </React.StrictMode>
);
