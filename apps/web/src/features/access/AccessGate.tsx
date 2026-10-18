import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import { orderApi, setAccessKey } from "../../api/client";

export function AccessGate({ children, scope }: { children: ReactNode; scope: "order" | "kitchen" }) {
  const [ready, setReady] = useState(false);
  const [required, setRequired] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [code, setCode] = useState("");
  const [retry, setRetry] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setReady(false);
    setError(null);
    orderApi.session(scope, controller.signal).then(session => {
      if (controller.signal.aborted) return;
      setRequired(session.required);
      setReady(session.authenticated);
    }).catch(error => {
      if (!controller.signal.aborted) setError(error.message);
    }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    const expired = () => { setReady(false); setRequired(true); setError("Enter the access code again."); };
    window.addEventListener("fullfill:access-required", expired);
    return () => { controller.abort(); window.removeEventListener("fullfill:access-required", expired); };
  }, [retry, scope]);

  async function signIn(event: FormEvent) {
    event.preventDefault();
    if (loading) return;
    setLoading(true);
    setError(null);
    setAccessKey(code.trim());
    try {
      const session = await orderApi.session(scope);
      if (!session.authenticated) {
        setAccessKey("");
        setError(session.role === "order" && scope === "kitchen" ? "Use the kitchen access code. The ordering code cannot access this screen." : "That code didn’t match.");
      } else {
        setCode("");
        setReady(true);
      }
    } catch (error) {
      setAccessKey("");
      setError(error instanceof Error ? error.message : "Could not connect.");
    } finally { setLoading(false); }
  }

  if (ready) return children;
  return <main className="access-page">
    <form className="access-card" onSubmit={signIn}>
      <h1>{required ? scope === "kitchen" ? "Kitchen access" : "Ordering access" : loading ? "Connecting…" : "Unable to connect"}</h1>
      {required && <>
        <label htmlFor="access-code">Access code</label>
        <input id="access-code" type="password" autoComplete="current-password" value={code} onChange={event => setCode(event.target.value)} required disabled={loading} />
      </>}
      {error && <p className="error-banner" role="alert">{error}</p>}
      {required ? <button className="primary-button" disabled={loading || !code.trim()}>{loading ? "Connecting…" : "Continue"}</button>
        : !loading && <button type="button" className="primary-button" onClick={() => setRetry(value => value + 1)}>Retry</button>}
    </form>
  </main>;
}
