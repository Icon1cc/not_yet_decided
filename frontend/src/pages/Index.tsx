import { useState, useEffect, useRef, useCallback } from "react";
import { SessionSidebar } from "@/components/SessionSidebar";
import { DropZone } from "@/components/DropZone";
import { ChatMessage } from "@/components/ChatMessage";
import { ChatInput } from "@/components/ChatInput";
import { LoadingIndicator } from "@/components/LoadingIndicator";
import { Search } from "lucide-react";
import {
  getAllSessions,
  saveSession,
  deleteSession,
  type Session,
  type ChatMessage as ChatMsg,
} from "@/lib/db";

const MOCK_RESPONSE = JSON.stringify([
  {
    name: "1000ml Universal-Entkalker",
    retailer: "Amazon AT",
    price_eur: 9.88,
    image_url: "https://m.media-amazon.com/images/I/617-0kYRuZL._AC_SL1400_.jpg",
    url: "https://www.amazon.de/",
  },
]);

function createSession(fileName?: string): Session {
  return {
    id: crypto.randomUUID(),
    timestamp: Date.now(),
    uploaded_file_name: fileName || null,
    messages: [],
  };
}

const Index = () => {
  const [sessions, setSessions] = useState<Session[]>([]);
  const [activeSession, setActiveSession] = useState<Session | null>(null);
  const [loading, setLoading] = useState(false);
  const [showAbout, setShowAbout] = useState(false);
  const feedRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    getAllSessions().then(setSessions);
  }, []);

  useEffect(() => {
    if (feedRef.current) {
      feedRef.current.scrollTop = feedRef.current.scrollHeight;
    }
  }, [activeSession?.messages, loading]);

  const refreshSessions = useCallback(async () => {
    const all = await getAllSessions();
    setSessions(all);
  }, []);

  const persistSession = useCallback(
    async (session: Session) => {
      await saveSession(session);
      setActiveSession({ ...session });
      await refreshSessions();
    },
    [refreshSessions]
  );

  const handleNew = useCallback(() => {
    const s = createSession();
    setActiveSession(s);
    saveSession(s).then(refreshSessions);
  }, [refreshSessions]);

  const handleSelect = useCallback(
    (id: string) => {
      const found = sessions.find((s) => s.id === id);
      if (found) setActiveSession({ ...found });
    },
    [sessions]
  );

  const handleDelete = useCallback(
    async (id: string) => {
      await deleteSession(id);
      if (activeSession?.id === id) setActiveSession(null);
      await refreshSessions();
    },
    [activeSession, refreshSessions]
  );

  const handleFileUpload = useCallback(
    async (file: File) => {
      const session = activeSession || createSession(file.name);
      session.uploaded_file_name = file.name;

      const userMsg: ChatMsg = {
        role: "user",
        content: `Uploaded file: ${file.name}`,
        timestamp: Date.now(),
      };
      session.messages = [...session.messages, userMsg];
      await persistSession(session);

      setLoading(true);
      setTimeout(async () => {
        const aiMsg: ChatMsg = {
          role: "ai",
          content: `File "${file.name}" loaded successfully. Ask me to find competitor matches for any product.`,
          timestamp: Date.now(),
        };
        session.messages = [...session.messages, aiMsg];
        await persistSession(session);
        setLoading(false);
      }, 2000);
    },
    [activeSession, persistSession]
  );

  const handleSend = useCallback(
    async (text: string) => {
      if (!activeSession) return;

      const userMsg: ChatMsg = {
        role: "user",
        content: text,
        timestamp: Date.now(),
      };
      const updated = {
        ...activeSession,
        messages: [...activeSession.messages, userMsg],
      };
      await persistSession(updated);

      setLoading(true);
      setTimeout(async () => {
        const aiMsg: ChatMsg = {
          role: "ai",
          content: MOCK_RESPONSE,
          timestamp: Date.now(),
        };
        const final = {
          ...updated,
          messages: [...updated.messages, aiMsg],
        };
        await persistSession(final);
        setLoading(false);
      }, 4000);
    },
    [activeSession, persistSession]
  );

  const hasMessages = activeSession && activeSession.messages.length > 0;

  return (
    <div className="flex h-screen overflow-hidden">
      {/* About Modal */}
      {showAbout && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-foreground/40" onClick={() => setShowAbout(false)}>
          <div className="bg-background border border-border rounded-sm max-w-md w-full mx-4 p-6" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center gap-3 mb-4">
              <div className="w-9 h-9 bg-primary text-primary-foreground flex items-center justify-center font-mono text-sm font-bold rounded-sm">CM</div>
              <h3 className="font-mono text-lg font-bold uppercase tracking-wider">About Us</h3>
            </div>
            <p className="font-sans text-sm leading-relaxed text-foreground mb-3">
              Competitor Matcher is an AI-powered product intelligence platform that helps businesses discover, compare, and track competitor products across multiple retailers.
            </p>
            <p className="font-sans text-sm leading-relaxed text-muted-foreground mb-5">
              Our matching algorithms analyze thousands of product catalogs in real-time, giving you actionable insights to stay ahead of the competition.
            </p>
            <button
              onClick={() => setShowAbout(false)}
              className="w-full bg-primary text-primary-foreground py-2.5 font-sans text-xs font-semibold uppercase tracking-wider rounded-sm hover:opacity-90 transition-opacity"
            >
              Close
            </button>
          </div>
        </div>
      )}
      <SessionSidebar
        sessions={sessions}
        activeId={activeSession?.id || null}
        onSelect={handleSelect}
        onNew={handleNew}
        onDelete={handleDelete}
        onHome={() => setActiveSession(null)}
      />

      <main className="flex-1 flex flex-col h-screen min-w-0 bg-background">
        {!activeSession ? (
          /* ─── Home / Empty State ─── */
          <div className="flex-1 flex flex-col items-center justify-center p-8">
            <div className="w-14 h-14 bg-primary text-primary-foreground flex items-center justify-center font-mono text-xl font-bold rounded-sm mb-6">
              CM
            </div>
            <h2 className="font-mono text-2xl font-bold uppercase tracking-widest mb-1">
              Competitor Matcher
            </h2>
            <p className="font-sans text-sm text-muted-foreground mb-10 max-w-md text-center">
              Upload a product catalog or ask a question to discover competitor products across retailers.
            </p>

            <div className="w-full max-w-md mb-8">
              <DropZone
                onFileUpload={(file) => {
                  const s = createSession(file.name);
                  setActiveSession(s);
                  saveSession(s).then(() => {
                    refreshSessions();
                    handleFileUpload(file);
                  });
                }}
              />
            </div>

            {/* Quick start suggestions */}
            <div className="w-full max-w-lg mb-6">
              <p className="font-sans text-[10px] font-semibold uppercase tracking-widest text-muted-foreground text-center mb-3">
                Or try asking
              </p>
              <div className="grid grid-cols-2 gap-2">
                {[
                  "Find competitors for cleaning products",
                  "Match kitchen appliances under €50",
                  "Compare top-rated electronics",
                  "Show alternatives for personal care",
                ].map((suggestion) => (
                  <button
                    key={suggestion}
                    onClick={() => {
                      const s = createSession();
                      setActiveSession(s);
                      saveSession(s).then(async () => {
                        await refreshSessions();
                        const userMsg: ChatMsg = { role: "user", content: suggestion, timestamp: Date.now() };
                        s.messages = [userMsg];
                        await persistSession(s);
                        setLoading(true);
                        setTimeout(async () => {
                          const aiMsg: ChatMsg = { role: "ai", content: MOCK_RESPONSE, timestamp: Date.now() };
                          s.messages = [...s.messages, aiMsg];
                          await persistSession(s);
                          setLoading(false);
                        }, 4000);
                      });
                    }}
                    className="flex items-start gap-2 text-left px-3 py-2.5 rounded-sm bg-secondary hover:bg-accent text-foreground font-sans text-xs transition-colors"
                  >
                    <Search className="w-3 h-3 mt-0.5 shrink-0 text-muted-foreground" />
                    {suggestion}
                  </button>
                ))}
              </div>
            </div>

            <div className="w-full max-w-lg">
              <ChatInput
                onSend={(text) => {
                  const s = createSession();
                  setActiveSession(s);
                  saveSession(s).then(async () => {
                    await refreshSessions();
                    const userMsg: ChatMsg = { role: "user", content: text, timestamp: Date.now() };
                    s.messages = [userMsg];
                    await persistSession(s);
                    setLoading(true);
                    setTimeout(async () => {
                      const aiMsg: ChatMsg = { role: "ai", content: MOCK_RESPONSE, timestamp: Date.now() };
                      s.messages = [...s.messages, aiMsg];
                      await persistSession(s);
                      setLoading(false);
                    }, 4000);
                  });
                }}
                disabled={loading}
                placeholder="Ask anything about competitor products..."
              />
            </div>

            {/* Footer */}
            <footer className="w-full max-w-lg mt-8 py-4 flex items-center justify-between font-sans text-[11px] text-muted-foreground">
              <p>© {new Date().getFullYear()} Competitor Matcher</p>
              <button
                onClick={() => setShowAbout(true)}
                className="hover:text-foreground transition-colors underline-offset-2 hover:underline"
              >
                About Us
              </button>
            </footer>
          </div>
        ) : (
          <>
            {/* Session Header */}
            <div className="border-b border-border px-6 py-3 flex items-center gap-3 shrink-0 bg-background">
              <div className="w-6 h-6 bg-primary text-primary-foreground flex items-center justify-center font-mono text-[9px] font-bold rounded-sm">
                CM
              </div>
              <span className="font-sans text-sm font-medium">
                {activeSession.uploaded_file_name || "New Session"}
              </span>
              {!activeSession.uploaded_file_name && (
                <label className="ml-auto font-sans text-[11px] font-medium cursor-pointer bg-secondary px-3 py-1.5 rounded-sm hover:bg-accent transition-colors">
                  Upload .json
                  <input
                    type="file"
                    accept=".json"
                    className="hidden"
                    onChange={(e) => {
                      const f = e.target.files?.[0];
                      if (f) handleFileUpload(f);
                    }}
                  />
                </label>
              )}
            </div>

            {/* Chat Feed */}
            <div ref={feedRef} className="flex-1 overflow-y-auto px-6 py-6 space-y-5">
              {!hasMessages && (
                <div className="flex items-center justify-center h-full">
                  <DropZone onFileUpload={handleFileUpload} />
                </div>
              )}
              {activeSession.messages.map((msg, i) => (
                <ChatMessage key={i} message={msg} />
              ))}
              {loading && <LoadingIndicator />}
            </div>

            <ChatInput onSend={handleSend} disabled={loading} />
          </>
        )}
      </main>
    </div>
  );
};

export default Index;
