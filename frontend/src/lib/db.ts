const DB_NAME = "competitor-matcher";
const DB_VERSION = 2;
const STORE_NAME = "sessions";

export interface MatchCard {
  reference: string;
  source_reference: string;
  name: string;
  retailer: string;
  price_eur: number | null;
  image_url: string | null;
  url: string | null;
}

export interface SubmissionCompetitor {
  reference: string;
  competitor_retailer: string;
  competitor_product_name: string;
  competitor_url: string | null;
  competitor_price: number | null;
}

export interface SourceSubmission {
  source_reference: string;
  competitors: SubmissionCompetitor[];
}

export interface ChatMessage {
  role: "user" | "ai";
  content: string;
  timestamp: number;
  cards?: MatchCard[] | null;
  submission?: SourceSubmission[] | null;
}

export interface Session {
  id: string;
  timestamp: number;
  uploaded_file_name: string | null;
  uploaded_source_products: Record<string, unknown>[] | null;
  messages: ChatMessage[];
}

function openDB(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, DB_VERSION);
    req.onupgradeneeded = () => {
      const db = req.result;
      if (!db.objectStoreNames.contains(STORE_NAME)) {
        db.createObjectStore(STORE_NAME, { keyPath: "id" });
      }
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

export async function getAllSessions(): Promise<Session[]> {
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, "readonly");
    const store = tx.objectStore(STORE_NAME);
    const req = store.getAll();
    req.onsuccess = () => {
      const sessions = (req.result as Session[]).map((s) => ({
        ...s,
        uploaded_source_products: s.uploaded_source_products ?? null,
        messages: (s.messages || []).map((m) => ({
          ...m,
          cards: m.cards ?? null,
          submission: m.submission ?? null,
        })),
      }));
      sessions.sort((a, b) => b.timestamp - a.timestamp);
      resolve(sessions);
    };
    req.onerror = () => reject(req.error);
  });
}

export async function getSession(id: string): Promise<Session | undefined> {
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, "readonly");
    const req = tx.objectStore(STORE_NAME).get(id);
    req.onsuccess = () => {
      const session = req.result as Session | undefined;
      if (!session) {
        resolve(undefined);
        return;
      }
      resolve({
        ...session,
        uploaded_source_products: session.uploaded_source_products ?? null,
        messages: (session.messages || []).map((m) => ({
          ...m,
          cards: m.cards ?? null,
          submission: m.submission ?? null,
        })),
      });
    };
    req.onerror = () => reject(req.error);
  });
}

export async function saveSession(session: Session): Promise<void> {
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, "readwrite");
    tx.objectStore(STORE_NAME).put(session);
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
  });
}

export async function deleteSession(id: string): Promise<void> {
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, "readwrite");
    tx.objectStore(STORE_NAME).delete(id);
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
  });
}
