import { ExternalLink } from "lucide-react";

interface Product {
  name: string;
  retailer: string;
  price_eur: number;
  image_url: string;
  url: string;
}

export function ProductCard({ product }: { product: Product }) {
  return (
    <div className="border border-border bg-background flex flex-col overflow-hidden rounded-sm hover:shadow-md transition-shadow">
      <div className="aspect-square overflow-hidden border-b border-border bg-secondary">
        <img
          src={product.image_url}
          alt={product.name}
          className="w-full h-full object-contain p-4"
          loading="lazy"
        />
      </div>
      <div className="p-4 flex flex-col gap-1 flex-1">
        <p className="font-sans text-sm font-semibold leading-tight truncate" title={product.name}>
          {product.name}
        </p>
        <p className="font-sans text-[11px] uppercase tracking-wider text-muted-foreground">
          {product.retailer}
        </p>
        <p className="font-mono text-xl font-bold mt-2">
          €{product.price_eur.toFixed(2)}
        </p>
      </div>
      <a
        href={product.url}
        target="_blank"
        rel="noopener noreferrer"
        className="flex items-center justify-center gap-2 border-t border-border bg-primary text-primary-foreground py-2.5 font-sans text-xs font-semibold uppercase tracking-wider hover:opacity-90 transition-opacity"
      >
        View Product
        <ExternalLink className="w-3 h-3" />
      </a>
    </div>
  );
}
