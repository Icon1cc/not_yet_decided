import { useState, useEffect, useRef, useCallback } from "react";
import { Search, Menu } from "lucide-react";

import { SessionSidebar } from "@/components/SessionSidebar";
import { DropZone } from "@/components/DropZone";
import { ChatMessage } from "@/components/ChatMessage";
import { ChatInput } from "@/components/ChatInput";
import { LoadingIndicator } from "@/components/LoadingIndicator";
import { sendChatQuery } from "@/lib/api";
import {
  getAllSessions,
  saveSession,
  deleteSession,
  type Session,
  type ChatMessage as ChatMsg,
} from "@/lib/db";

const QUICK_SUGGESTIONS = [
  "Find competitors for cleaning products",
  "Match kitchen appliances under €50",
  "Show alternatives for Samsung TVs",
  "Find hidden retailer matches for Bosch dishwashers",
];

function createSession(fileName?: string, products?: Record<string, unknown>[] | null): Session {
  return {
    id: crypto.randomUUID(),
    timestamp: Date.now(),
    uploaded_file_name: fileName || null,
    uploaded_source_products: products || null,
    messages: [],
  };
}

function buildUserMessage(content: string): ChatMsg {
  return {
    role: "user",
    content,
    timestamp: Date.now(),
    cards: null,
    submission: null,
  };
}

function buildAiMessage(content: string, options?: Pick<ChatMsg, "cards" | "submission">): ChatMsg {
  return {
    role: "ai",
    content,
    timestamp: Date.now(),
    cards: options?.cards || null,
    submission: options?.submission || null,
  };
}

function parseUploadedCatalog(text: string): Record<string, unknown>[] {
  const parsed = JSON.parse(text);
  if (!Array.isArray(parsed)) {
    throw new Error("Uploaded file must contain a JSON array of source products.");
  }
  if (parsed.length === 0) {
    throw new Error("Uploaded catalog is empty.");
  }
  const invalid = parsed.find(
    (row) =>
      !row ||
      typeof row !== "object" ||
      !("reference" in row) ||
      !("name" in row)
  );
  if (invalid) {
    throw new Error("Each source product must include at least 'reference' and 'name'.");
  }
  return parsed as Record<string, unknown>[];
}

const Index = () => {
  const [sessions, setSessions] = useState<Session[]>([]);
  const [activeSession, setActiveSession] = useState<Session | null>(null);
  const [loading, setLoading] = useState(false);
  const [showAbout, setShowAbout] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(false);
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
      const updated = { ...session, timestamp: Date.now() };
      await saveSession(updated);
      setActiveSession({ ...updated });
      await refreshSessions();
      return updated;
    },
    [refreshSessions]
  );

  const runQuery = useCallback(
    async (session: Session, text: string) => {
      const history = session.messages
        .filter((m) => m.role === "user" && !m.content.startsWith("Uploaded file:"))
        .map((m) => m.content);
      const previousSubmission =
        [...session.messages]
          .reverse()
          .find((m) => m.role === "ai" && m.submission && m.submission.length > 0)
          ?.submission ?? null;

      const withUser = {
        ...session,
        messages: [...session.messages, buildUserMessage(text)],
      };
      const persistedUser = await persistSession(withUser);

      setLoading(true);
      try {
        const response = await sendChatQuery({
          query: text,
          sourceProducts: persistedUser.uploaded_source_products,
          history,
          previousSubmission,
          persistOutput: true,
          maxSources: text.toLowerCase().includes("all") ? 200 : 5,
          maxCompetitorsPerSource: 12,
        });

        const withAi = {
          ...persistedUser,
          messages: [
            ...persistedUser.messages,
            buildAiMessage(response.answer, {
              cards: response.cards,
              submission: response.submission,
            }),
          ],
        };
        await persistSession(withAi);
      } catch (error) {
        const message = error instanceof Error ? error.message : "Unknown backend error";
        const withError = {
          ...persistedUser,
          messages: [
            ...persistedUser.messages,
            buildAiMessage(
              `Request failed. Start the backend and retry. Details: ${message}`
            ),
          ],
        };
        await persistSession(withError);
      } finally {
        setLoading(false);
      }
    },
    [persistSession]
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
      let parsedCatalog: Record<string, unknown>[];
      try {
        parsedCatalog = parseUploadedCatalog(await file.text());
      } catch (error) {
        const err = error instanceof Error ? error.message : "Invalid upload";
        const fallback = activeSession || createSession(file.name);
        const withError = {
          ...fallback,
          messages: [
            ...fallback.messages,
            buildAiMessage(`Upload failed: ${err}`),
          ],
        };
        await persistSession(withError);
        return;
      }

      const session = activeSession || createSession(file.name, parsedCatalog);
      const updated = {
        ...session,
        uploaded_file_name: file.name,
        uploaded_source_products: parsedCatalog,
      };

      const withUser = {
        ...updated,
        messages: [...updated.messages, buildUserMessage(`Uploaded file: ${file.name}`)],
      };

      const withAck = {
        ...withUser,
        messages: [
          ...withUser.messages,
          buildAiMessage(
            `Loaded ${parsedCatalog.length} source products from "${file.name}". Ask for matches by product name/reference, retailer, price, or category.`
          ),
        ],
      };

      await persistSession(withAck);
    },
    [activeSession, persistSession]
  );

  const startSessionAndSend = useCallback(
    async (text: string) => {
      const s = createSession();
      setActiveSession(s);
      await saveSession(s);
      await refreshSessions();
      await runQuery(s, text);
    },
    [refreshSessions, runQuery]
  );

  const hasMessages = activeSession && activeSession.messages.length > 0;

  return (
    <div className="flex h-screen overflow-hidden">
      {sidebarOpen && (
        <div
          className="fixed inset-0 z-30 bg-black/50 md:hidden"
          onClick={() => setSidebarOpen(false)}
        />
      )}
      {showAbout && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-foreground/40"
          onClick={() => setShowAbout(false)}
        >
          <div
            className="bg-background border border-border rounded-sm max-w-md w-full mx-4 p-6"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center gap-3 mb-4">
              <div className="w-9 h-9 bg-primary text-primary-foreground flex items-center justify-center font-mono text-sm font-bold rounded-sm">
                CM
              </div>
              <h3 className="font-mono text-lg font-bold uppercase tracking-wider">About Us</h3>
            </div>
            <p className="font-sans text-sm leading-relaxed text-foreground mb-3">
              Competitor Matcher is an AI-powered product intelligence platform that finds, validates, and formats competitor product links for both visible and hidden retailers.
            </p>
            <p className="font-sans text-sm leading-relaxed text-muted-foreground mb-4">
              Output is generated directly in scoring-ready format (`source_reference` + `reference` / `competitor_url`) and persisted with chat history per session.
            </p>
            <div className="border-t border-border pt-4 mb-5">
              <p className="font-mono text-[10px] font-semibold uppercase tracking-widest text-muted-foreground mb-3">Team</p>
              <div className="space-y-2.5">
                <div>
                  <p className="font-sans text-sm font-medium">Rishabh Tiwari</p>
                  <p className="font-sans text-xs text-muted-foreground">rishtiwari98@gmail.com</p>
                </div>
                <div>
                  <p className="font-sans text-sm font-medium">Florian Sprick</p>
                  <p className="font-sans text-xs text-muted-foreground">florian.sprick@hotmail.com</p>
                </div>
              </div>
            </div>
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
        onSelect={(id) => { handleSelect(id); setSidebarOpen(false); }}
        onNew={() => { handleNew(); setSidebarOpen(false); }}
        onDelete={handleDelete}
        onHome={() => { setActiveSession(null); setSidebarOpen(false); }}
        isOpen={sidebarOpen}
        onClose={() => setSidebarOpen(false)}
      />

      <main className="flex-1 flex flex-col h-screen min-w-0 bg-background">
        {!activeSession ? (
          <div className="flex-1 flex flex-col items-center justify-center p-8 relative">
            <button
              onClick={() => setSidebarOpen(true)}
              className="md:hidden absolute top-4 left-4 p-2 hover:bg-secondary rounded-sm transition-colors"
            >
              <Menu className="w-5 h-5" />
            </button>
            <div className="w-14 h-14 bg-primary text-primary-foreground flex items-center justify-center font-mono text-xl font-bold rounded-sm mb-6">
              CM
            </div>
            <h2 className="font-mono text-2xl font-bold uppercase tracking-widest mb-1">
              Competitor Matcher
            </h2>
            <p className="font-sans text-sm text-muted-foreground mb-10 max-w-md text-center">
              Upload a source catalog JSON or ask directly about a product. The response is generated in submission-ready scoring format.
            </p>

            <div className="w-full max-w-md mb-8">
              <DropZone onFileUpload={handleFileUpload} />
            </div>

            <div className="w-full max-w-lg mb-6">
              <p className="font-sans text-[10px] font-semibold uppercase tracking-widest text-muted-foreground text-center mb-3">
                Or try asking
              </p>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                {QUICK_SUGGESTIONS.map((suggestion) => (
                  <button
                    key={suggestion}
                    onClick={() => startSessionAndSend(suggestion)}
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
                onSend={(text) => startSessionAndSend(text)}
                disabled={loading}
                placeholder="Ask anything about competitor products..."
              />
            </div>

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
            <div className="border-b border-border px-4 py-3 flex items-center gap-3 shrink-0 bg-background">
              <button
                onClick={() => setSidebarOpen(true)}
                className="md:hidden p-1 hover:bg-secondary rounded-sm transition-colors"
              >
                <Menu className="w-4 h-4" />
              </button>
              <div className="w-6 h-6 bg-primary text-primary-foreground flex items-center justify-center font-mono text-[9px] font-bold rounded-sm">
                CM
              </div>
              <span className="font-sans text-sm font-medium">
                {activeSession.uploaded_file_name || "New Session"}
              </span>
              <label className="ml-auto font-sans text-[11px] font-medium cursor-pointer bg-secondary px-3 py-1.5 rounded-sm hover:bg-accent transition-colors">
                {activeSession.uploaded_file_name ? "Replace .json" : "Upload .json"}
                <input
                  type="file"
                  accept=".json"
                  className="hidden"
                  onChange={(e) => {
                    const file = e.target.files?.[0];
                    e.currentTarget.value = "";
                    if (file) handleFileUpload(file);
                  }}
                />
              </label>
            </div>

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

            <ChatInput
              onSend={(text) => {
                if (activeSession) {
                  runQuery(activeSession, text);
                }
              }}
              disabled={loading}
            />
          </>
        )}
      </main>
    </div>
  );
};

export default Index;
