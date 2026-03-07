import { useState } from "react";
import { Send } from "lucide-react";

interface ChatInputProps {
  onSend: (message: string) => void;
  disabled?: boolean;
  placeholder?: string;
}

export function ChatInput({ onSend, disabled, placeholder }: ChatInputProps) {
  const [value, setValue] = useState("");

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = value.trim();
    if (!trimmed || disabled) return;
    onSend(trimmed);
    setValue("");
  };

  return (
    <form
      onSubmit={handleSubmit}
      className="sticky bottom-0 border-t border-border bg-background px-4 py-3 flex gap-2 items-center"
    >
      <input
        type="text"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        placeholder={placeholder || "Ask about competitor products..."}
        disabled={disabled}
        className="flex-1 bg-secondary px-4 py-2.5 font-sans text-sm rounded-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring/20 disabled:opacity-50 transition-shadow"
      />
      <button
        type="submit"
        disabled={disabled || !value.trim()}
        className="bg-primary text-primary-foreground p-2.5 rounded-sm hover:opacity-90 transition-opacity disabled:opacity-20"
      >
        <Send className="w-4 h-4" />
      </button>
    </form>
  );
}
