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

  const products = tryParseProducts(message.content);

  if (products) {
    return (
      <div className="animate-fade-in">
        <div className="flex items-center gap-2.5 mb-3">
          <div className="w-7 h-7 rounded-full bg-secondary flex items-center justify-center shrink-0">
            <Bot className="w-3.5 h-3.5" />
          </div>
          <p className="font-mono text-xs uppercase tracking-wider text-muted-foreground">
            {products.length} match{products.length !== 1 ? "es" : ""} found
          </p>
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4 ml-9">
          {products.map((p: any, i: number) => (
            <ProductCard key={i} product={p} />
          ))}
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
