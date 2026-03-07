import { ProductCard } from "./ProductCard";
import type { ChatMessage as ChatMessageType } from "@/lib/db";
import { Bot, User } from "lucide-react";

function tryParseProducts(content: string) {
  try {
    const parsed = JSON.parse(content);
    if (
      Array.isArray(parsed) &&
      parsed.length > 0 &&
      parsed[0].image_url &&
      parsed[0].url
    ) {
      return parsed;
    }
  } catch {
    // not JSON
  }
  return null;
}

export function ChatMessage({ message }: { message: ChatMessageType }) {
  if (message.role === "user") {
    return (
      <div className="flex justify-end gap-2.5 animate-fade-in">
        <div className="chat-bubble-user">
          <p className="text-sm">{message.content}</p>
        </div>
        <div className="w-7 h-7 rounded-full bg-primary text-primary-foreground flex items-center justify-center shrink-0 mt-0.5">
          <User className="w-3.5 h-3.5" />
        </div>
      </div>
    );
  }

  const products = message.cards || tryParseProducts(message.content);
  const submission = message.submission;

  if (products && products.length > 0) {
    return (
      <div className="animate-fade-in">
        <div className="flex items-start gap-2.5 mb-3">
          <div className="w-7 h-7 rounded-full bg-secondary flex items-center justify-center shrink-0 mt-1">
            <Bot className="w-3.5 h-3.5" />
          </div>
          <div className="space-y-1">
            <p className="text-sm whitespace-pre-line">{message.content}</p>
            <p className="font-mono text-xs uppercase tracking-wider text-muted-foreground">
              {products.length} match{products.length !== 1 ? "es" : ""} found
            </p>
          </div>
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4 ml-9">
          {products.map((p: any, i: number) => (
            <ProductCard key={i} product={p} />
          ))}
        </div>
        {submission && (
          <details className="ml-9 mt-4 border border-border rounded-sm bg-background">
            <summary className="cursor-pointer font-mono text-xs uppercase tracking-wider px-3 py-2 bg-secondary">
              Submission JSON (scoring format)
            </summary>
            <pre className="text-xs font-mono whitespace-pre-wrap break-all p-3 max-h-80 overflow-auto">
              {JSON.stringify(submission, null, 2)}
            </pre>
          </details>
        )}
      </div>
    );
  }

  if (submission && submission.length > 0) {
    return (
      <div className="flex justify-start gap-2.5 animate-fade-in">
        <div className="w-7 h-7 rounded-full bg-secondary flex items-center justify-center shrink-0 mt-0.5">
          <Bot className="w-3.5 h-3.5" />
        </div>
        <div className="w-full max-w-[88%] space-y-3">
          <div className="chat-bubble-ai">
            <p className="text-sm whitespace-pre-line">{message.content}</p>
          </div>
          <details className="border border-border rounded-sm bg-background">
            <summary className="cursor-pointer font-mono text-xs uppercase tracking-wider px-3 py-2 bg-secondary">
              Submission JSON (scoring format)
            </summary>
            <pre className="text-xs font-mono whitespace-pre-wrap break-all p-3 max-h-80 overflow-auto">
              {JSON.stringify(submission, null, 2)}
            </pre>
          </details>
        </div>
      </div>
    );
  }

  return (
    <div className="flex justify-start gap-2.5 animate-fade-in">
      <div className="w-7 h-7 rounded-full bg-secondary flex items-center justify-center shrink-0 mt-0.5">
        <Bot className="w-3.5 h-3.5" />
      </div>
      <div className="chat-bubble-ai">
        <p className="text-sm">{message.content}</p>
      </div>
    </div>
  );
}
