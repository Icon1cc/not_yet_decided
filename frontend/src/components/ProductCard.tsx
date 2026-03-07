import { ExternalLink } from "lucide-react";

interface Product {
  reference: string;
  source_reference: string;
  name: string;
  retailer: string;
  price_eur: number | null;
  image_url: string | null;
  url: string | null;
}

export function ProductCard({ product }: { product: Product }) {
  const hasUrl = Boolean(product.url);
  return (
    <div className="border border-border bg-background flex flex-col overflow-hidden rounded-sm hover:shadow-md transition-shadow">
      <div className="aspect-square overflow-hidden border-b border-border bg-secondary">
        {product.image_url ? (
          <img
            src={product.image_url}
            alt={product.name}
            className="w-full h-full object-contain p-4"
            loading="lazy"
          />
        ) : (
          <div className="w-full h-full flex items-center justify-center p-4 text-muted-foreground text-xs font-sans">
            No image
          </div>
        )}
      </div>
      <div className="p-4 flex flex-col gap-1 flex-1">
        <p className="font-sans text-sm font-semibold leading-tight truncate" title={product.name}>
          {product.name}
        </p>
        <p className="font-sans text-[11px] uppercase tracking-wider text-muted-foreground">
          {product.retailer}
        </p>
        <p className="font-mono text-xl font-bold mt-2">
          {typeof product.price_eur === "number" ? `€${product.price_eur.toFixed(2)}` : "N/A"}
        </p>
        <p className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground mt-1">
          {product.source_reference} {"->"} {product.reference}
        </p>
      </div>
      {hasUrl ? (
        <a
          href={product.url || undefined}
          target="_blank"
          rel="noopener noreferrer"
          className="flex items-center justify-center gap-2 border-t border-border bg-primary text-primary-foreground py-2.5 font-sans text-xs font-semibold uppercase tracking-wider hover:opacity-90 transition-opacity"
        >
          View Product
          <ExternalLink className="w-3 h-3" />
        </a>
      ) : (
        <div className="flex items-center justify-center gap-2 border-t border-border bg-secondary text-muted-foreground py-2.5 font-sans text-xs font-semibold uppercase tracking-wider">
          No Product URL
        </div>
      )}
    </div>
  );
}
