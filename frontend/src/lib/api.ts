/**
 * API client for the Competitor Matcher backend.
 * Handles communication with the FastAPI backend.
 */

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// Types
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

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

export interface PriceFilter {
  min: number | null;
  max: number | null;
}

export interface QueryStats {
  query: string;
  effective_query: string;
  selected_sources: number;
  matched_sources: number;
  total_links: number;
  visible_links: number;
  hidden_links: number;
  retailer_filter: string[];
  kind_filter: string[];
  anchor_tokens: string[];
  follow_up_expand: boolean;
  additional_only: boolean;
  previous_source_refs: string[];
  excluded_previous_links: number;
  price_filter: PriceFilter;
  output_file: string | null;
}

export interface ChatApiResponse {
  answer: string;
  submission: SourceSubmission[];
  cards: MatchCard[];
  stats: QueryStats;
}

export interface HealthResponse {
  status: string;
  version: string;
  sources: number;
  targets: number;
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// Configuration
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

const API_TIMEOUT_MS = 30000;

function getApiEndpoints(): string[] {
  const envBase = (import.meta.env.VITE_API_BASE_URL as string | undefined)?.trim();
  const normalizedBase = envBase ? envBase.replace(/\/+$/, "") : "";

  const candidates = [
    normalizedBase ? `${normalizedBase}/api/v1` : "",
    "/api/v1",
    "http://127.0.0.1:8000/api/v1",
    "http://localhost:8000/api/v1",
  ].filter(Boolean);

  return Array.from(new Set(candidates));
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// API Client
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class ApiError extends Error {
  constructor(
    message: string,
    public statusCode?: number,
    public endpoint?: string
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function fetchWithRetry<T>(
  path: string,
  options: RequestInit
): Promise<T> {
  const endpoints = getApiEndpoints();
  let lastError: Error = new ApiError("No API endpoints configured");

  for (const baseUrl of endpoints) {
    const url = `${baseUrl}${path}`;
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), API_TIMEOUT_MS);

    try {
      const response = await fetch(url, {
        ...options,
        signal: controller.signal,
      });

      clearTimeout(timeoutId);

      if (response.ok) {
        return (await response.json()) as T;
      }

      const errorText = await response.text();
      lastError = new ApiError(
        errorText || `Request failed with status ${response.status}`,
        response.status,
        url
      );

      // Only retry on transient errors for relative URLs
      const isTransient = [404, 502, 503, 504].includes(response.status);
      const isRelativeUrl = baseUrl.startsWith("/");
      if (!(isTransient && isRelativeUrl)) {
        throw lastError;
      }
    } catch (error) {
      clearTimeout(timeoutId);

      if (error instanceof ApiError) {
        throw error;
      }

      lastError =
        error instanceof Error
          ? new ApiError(error.message, undefined, url)
          : new ApiError("Unknown error", undefined, url);
    }
  }

  throw lastError;
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// Public API Functions
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

export interface ChatQueryParams {
  query: string;
  sourceProducts?: Record<string, unknown>[] | null;
  history?: string[] | null;
  previousSubmission?: SourceSubmission[] | null;
  persistOutput?: boolean;
  maxSources?: number;
  maxCompetitorsPerSource?: number;
}

/**
 * Send a chat query to the backend and get competitor matches.
 */
export async function sendChatQuery(
  params: ChatQueryParams
): Promise<ChatApiResponse> {
  const payload = {
    query: params.query,
    source_products: params.sourceProducts ?? null,
    history: params.history ?? null,
    previous_submission: params.previousSubmission ?? null,
    persist_output: params.persistOutput ?? true,
    max_sources: params.maxSources ?? 5,
    max_competitors_per_source: params.maxCompetitorsPerSource ?? 12,
  };

  return fetchWithRetry<ChatApiResponse>("/chat", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });
}

/**
 * Check the health status of the backend.
 */
export async function checkHealth(): Promise<HealthResponse> {
  return fetchWithRetry<HealthResponse>("/health", {
    method: "GET",
    headers: {
      Accept: "application/json",
    },
  });
}
