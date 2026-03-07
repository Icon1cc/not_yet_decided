import { useState, useCallback, useRef } from "react";
import { Upload, FileJson } from "lucide-react";

interface DropZoneProps {
  onFileUpload: (file: File) => void;
}

export function DropZone({ onFileUpload }: DropZoneProps) {
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setDragging(false);
      const file = e.dataTransfer.files[0];
      if (file && file.name.endsWith(".json")) {
        onFileUpload(file);
      }
    },
    [onFileUpload]
  );

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) onFileUpload(file);
  };

  return (
    <div
      className={`drop-zone h-48 cursor-pointer px-6 ${dragging ? "drop-zone-active" : ""}`}
      onDragOver={(e) => {
        e.preventDefault();
        setDragging(true);
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={handleDrop}
      onClick={() => inputRef.current?.click()}
    >
      <div className="w-12 h-12 rounded-full bg-secondary flex items-center justify-center mb-4">
        {dragging ? (
          <FileJson className="w-5 h-5" />
        ) : (
          <Upload className="w-5 h-5" />
        )}
      </div>
      <p className="font-mono text-sm font-bold uppercase tracking-wider">
        Drop .json file here
      </p>
      <p className="font-sans text-xs mt-1.5 text-muted-foreground">
        or click to browse your files
      </p>
      <input
        ref={inputRef}
        type="file"
        accept=".json"
        className="hidden"
        onChange={handleChange}
      />
    </div>
  );
}
