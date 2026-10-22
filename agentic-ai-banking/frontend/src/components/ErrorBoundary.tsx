import { Component, ReactNode } from "react";

export default class ErrorBoundary extends Component<{ children: ReactNode }, { err: string }> {
  state = { err: "" };
  static getDerivedStateFromError(e: Error) { return { err: e.message || "Unexpected error" }; }
  componentDidCatch(e: Error) { console.error(e); }
  render() {
    if (!this.state.err) return this.props.children;
    return <div className="err" role="alert" style={{ margin: 24 }}>Something went wrong: {this.state.err}{" "}
      <button onClick={() => location.reload()}>Reload</button></div>;
  }
}
