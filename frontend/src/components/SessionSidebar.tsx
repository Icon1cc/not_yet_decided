import { Plus, FileJson, Trash2, MessageSquare } from "lucide-react";
import type { Session } from "@/lib/db";

interface SessionSidebarProps {
  sessions: Session[];
  activeId: string | null;
  onSelect: (id: string) => void;
  onNew: () => void;
  onDelete: (id: string) => void;
  onHome: () => void;
}

export function SessionSidebar({
  sessions,
  activeId,
  onSelect,
  onNew,
  onDelete,
  onHome,
}: SessionSidebarProps) {
  return (
    <aside className="w-72 shrink-0 border-r border-border h-screen flex flex-col bg-sidebar">
      {/* Logo */}
      <div
        onClick={onHome}
        className="px-5 py-5 flex items-center gap-3 cursor-pointer hover:bg-sidebar-accent transition-colors border-b border-border"
      >
        <div className="w-9 h-9 bg-primary text-primary-foreground flex items-center justify-center font-mono text-sm font-bold tracking-tight rounded-sm shrink-0">
          CM
        </div>
        <div>
          <p className="font-mono text-xs font-bold uppercase tracking-widest leading-tight">
            Competitor
          </p>
          <p className="font-mono text-xs font-bold uppercase tracking-widest leading-tight">
            Matcher
          </p>
        </div>
      </div>

      {/* New Chat */}
      <div className="p-3">
        <button
          onClick={onNew}
          className="w-full flex items-center justify-center gap-2 bg-primary text-primary-foreground py-2.5 px-4 font-sans text-xs font-semibold uppercase tracking-wider hover:opacity-90 transition-opacity rounded-sm"
        >
          <Plus className="w-3.5 h-3.5" />
          New Chat
        </button>
      </div>

      {/* Sessions */}
      <div className="px-3 pb-1">
        <p className="font-sans text-[10px] font-semibold uppercase tracking-widest text-muted-foreground px-2 py-2">
          History
        </p>
      </div>
      <div className="flex-1 overflow-y-auto px-3 pb-3">
        {sessions.length === 0 && (
          <div className="flex flex-col items-center justify-center py-10 text-muted-foreground">
            <MessageSquare className="w-5 h-5 mb-2 opacity-40" />
            <p className="font-sans text-[11px]">No sessions yet</p>
          </div>
        )}
        <div className="space-y-0.5">
          {sessions.map((s) => (
            <div
              key={s.id}
              onClick={() => onSelect(s.id)}
              className={`flex items-center gap-2.5 px-3 py-2.5 cursor-pointer transition-colors group rounded-sm ${
                s.id === activeId
                  ? "bg-primary text-primary-foreground"
                  : "hover:bg-sidebar-accent"
              }`}
            >
              <FileJson className="w-3.5 h-3.5 shrink-0 opacity-60" />
              <div className="flex-1 min-w-0">
                <p className="font-sans text-xs font-medium truncate">
                  {s.uploaded_file_name || "Untitled"}
                </p>
                <p className={`font-sans text-[10px] ${s.id === activeId ? "opacity-60" : "text-muted-foreground"}`}>
                  {new Date(s.timestamp).toLocaleDateString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}
                </p>
              </div>
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  onDelete(s.id);
                }}
                className="opacity-0 group-hover:opacity-60 hover:!opacity-100 transition-opacity"
              >
                <Trash2 className="w-3 h-3" />
              </button>
            </div>
          ))}
        </div>
      </div>

      {/* Footer */}
      <div className="px-5 py-3 border-t border-border">
        <p className="font-sans text-[10px] text-muted-foreground">
          Product Intelligence Platform
        </p>
      </div>
    </aside>
  );
}
