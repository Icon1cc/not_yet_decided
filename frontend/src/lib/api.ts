export interface Competitor {
  reference: string;
  competitor_retailer: string;
  competitor_product_name: string;
  competitor_url: string | null;
  competitor_price: number | null;
}

export interface SourceSubmission {
  source_reference: string;
  competitors: Competitor[];
}

export interface MatchCard {
  reference: string;
  source_reference: string;
  name: string;
  retailer: string;
  price_eur: number | null;
  image_url: string | null;
  url: string | null;
}

export interface ChatApiResponse {
  answer: string;
  submission: SourceSubmission[];
  cards: MatchCard[];
  stats: {
    query: string;
    effective_query: string;
    selected_sources: number;
    matched_sources: number;
    total_links: number;
    visible_links: number;
    hidden_links: number;
    retailer_filter: string[];
    kind_filter?: string[];
    anchor_tokens?: string[];
    follow_up_expand?: boolean;
    additional_only?: boolean;
    previous_source_refs?: string[];
    excluded_previous_links?: number;
    price_filter: {
      min: number | null;
      max: number | null;
    };
    output_file: string | null;
  };
}

function chatEndpointCandidates(): string[] {
  const envBase = (import.meta.env.VITE_API_BASE_URL as string | undefined)?.trim();
  const normalizedBase = envBase ? envBase.replace(/\/+$/, "") : "";
  const candidates = [
    normalizedBase ? `${normalizedBase}/api/v1/chat` : "",
    "/api/v1/chat",
    "http://127.0.0.1:8000/api/v1/chat",
    "http://localhost:8000/api/v1/chat",
  ].filter(Boolean);
  return Array.from(new Set(candidates));
}

export async function sendChatQuery(params: {
  query: string;
  sourceProducts?: Record<string, unknown>[] | null;
  history?: string[] | null;
  previousSubmission?: SourceSubmission[] | null;
  persistOutput?: boolean;
  maxSources?: number;
  maxCompetitorsPerSource?: number;
}): Promise<ChatApiResponse> {
  const payload = JSON.stringify({
    query: params.query,
    source_products: params.sourceProducts ?? null,
    history: params.history ?? null,
    previous_submission: params.previousSubmission ?? null,
    persist_output: params.persistOutput ?? true,
    max_sources: params.maxSources ?? 5,
    max_competitors_per_source: params.maxCompetitorsPerSource ?? 12,
  });

  let lastError = "Unknown backend error";
  for (const endpoint of chatEndpointCandidates()) {
    let res: Response;
    try {
      res = await fetch(endpoint, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: payload,
      });
    } catch (error) {
      lastError = error instanceof Error ? error.message : String(error);
      continue;
    }

    if (res.ok) {
      return (await res.json()) as ChatApiResponse;
    }

    const text = await res.text();
    lastError = text || `API request to ${endpoint} failed with status ${res.status}`;
    const transientMissingProxy =
      endpoint.startsWith("/") && (res.status === 404 || res.status === 502 || res.status === 503 || res.status === 504);
    if (transientMissingProxy) {
      continue;
    }
    throw new Error(lastError);
  }

  throw new Error(lastError);
}
