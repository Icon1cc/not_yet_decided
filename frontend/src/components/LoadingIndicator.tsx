import { useState, useEffect } from "react";
import { Bot } from "lucide-react";

const QUOTES = [
  "Deploying stealth bots to sneak into competitor websites...",
  "Traversing the dark web of deeply nested JSON...",
  "Teaching the LLM the difference between an Airfryer and a spaceship...",
  "Bribing the matching algorithm with digital coffee...",
  "Reading thousands of product specs so you don't have to...",
  "Calculating the exact probability of this being a match...",
  "Waiting for the competitor's slow server to respond...",
];

export function LoadingIndicator() {
  const [quoteIndex, setQuoteIndex] = useState(() =>
    Math.floor(Math.random() * QUOTES.length)
  );

  useEffect(() => {
    const interval = setInterval(() => {
      setQuoteIndex((prev) => {
        let next: number;
        do {
          next = Math.floor(Math.random() * QUOTES.length);
        } while (next === prev && QUOTES.length > 1);
        return next;
      });
    }, 3000);
    return () => clearInterval(interval);
  }, []);

  return (
    <div className="flex items-start gap-2.5 animate-fade-in">
      <div className="w-7 h-7 rounded-full bg-secondary flex items-center justify-center shrink-0 mt-0.5">
        <Bot className="w-3.5 h-3.5" />
      </div>
      <div className="chat-bubble-ai flex items-center gap-3">
        <span className="loading-cursor inline-block w-2.5 h-4 bg-foreground shrink-0 rounded-[1px]" />
        <p className="font-sans text-xs leading-relaxed italic text-muted-foreground">
          {QUOTES[quoteIndex]}
        </p>
      </div>
    </div>
  );
}
