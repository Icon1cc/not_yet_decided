/**
 * IndexedDB persistence layer for session management.
 * Stores chat sessions with messages, uploaded catalogs, and submission history.
 */

import type { MatchCard, SourceSubmission } from "./api";

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// Configuration
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

const DB_NAME = "competitor-matcher";
const DB_VERSION = 2;
const STORE_NAME = "sessions";

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// Types
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

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

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// Database Connection
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

let dbInstance: IDBDatabase | null = null;

function openDB(): Promise<IDBDatabase> {
  // Return cached connection if available
  if (dbInstance) {
    return Promise.resolve(dbInstance);
  }

  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, DB_VERSION);

    request.onupgradeneeded = () => {
      const db = request.result;
      if (!db.objectStoreNames.contains(STORE_NAME)) {
        db.createObjectStore(STORE_NAME, { keyPath: "id" });
      }
    };

    request.onsuccess = () => {
      dbInstance = request.result;

      // Handle connection close
      dbInstance.onclose = () => {
        dbInstance = null;
      };

      resolve(dbInstance);
    };

    request.onerror = () => {
      reject(new Error(`Failed to open IndexedDB: ${request.error?.message}`));
    };
  });
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// Helper Functions
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

function normalizeSession(session: Session): Session {
  return {
    ...session,
    uploaded_source_products: session.uploaded_source_products ?? null,
    messages: (session.messages || []).map((m) => ({
      ...m,
      cards: m.cards ?? null,
      submission: m.submission ?? null,
    })),
  };
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// Public API
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

/**
 * Get all sessions, sorted by timestamp (newest first).
 */
export async function getAllSessions(): Promise<Session[]> {
  const db = await openDB();

  return new Promise((resolve, reject) => {
    const transaction = db.transaction(STORE_NAME, "readonly");
    const store = transaction.objectStore(STORE_NAME);
    const request = store.getAll();

    request.onsuccess = () => {
      const sessions = (request.result as Session[])
        .map(normalizeSession)
        .sort((a, b) => b.timestamp - a.timestamp);
      resolve(sessions);
    };

    request.onerror = () => {
      reject(new Error(`Failed to get sessions: ${request.error?.message}`));
    };
  });
}

/**
 * Get a single session by ID.
 */
export async function getSession(id: string): Promise<Session | undefined> {
  const db = await openDB();

  return new Promise((resolve, reject) => {
    const transaction = db.transaction(STORE_NAME, "readonly");
    const request = transaction.objectStore(STORE_NAME).get(id);

    request.onsuccess = () => {
      const session = request.result as Session | undefined;
      resolve(session ? normalizeSession(session) : undefined);
    };

    request.onerror = () => {
      reject(new Error(`Failed to get session: ${request.error?.message}`));
    };
  });
}

/**
 * Save or update a session.
 */
export async function saveSession(session: Session): Promise<void> {
  const db = await openDB();

  return new Promise((resolve, reject) => {
    const transaction = db.transaction(STORE_NAME, "readwrite");
    transaction.objectStore(STORE_NAME).put(session);

    transaction.oncomplete = () => resolve();
    transaction.onerror = () => {
      reject(new Error(`Failed to save session: ${transaction.error?.message}`));
    };
  });
}

/**
 * Delete a session by ID.
 */
export async function deleteSession(id: string): Promise<void> {
  const db = await openDB();

  return new Promise((resolve, reject) => {
    const transaction = db.transaction(STORE_NAME, "readwrite");
    transaction.objectStore(STORE_NAME).delete(id);

    transaction.oncomplete = () => resolve();
    transaction.onerror = () => {
      reject(new Error(`Failed to delete session: ${transaction.error?.message}`));
    };
  });
}

/**
 * Clear all sessions (for debugging/reset).
 */
export async function clearAllSessions(): Promise<void> {
  const db = await openDB();

  return new Promise((resolve, reject) => {
    const transaction = db.transaction(STORE_NAME, "readwrite");
    transaction.objectStore(STORE_NAME).clear();

    transaction.oncomplete = () => resolve();
    transaction.onerror = () => {
      reject(new Error(`Failed to clear sessions: ${transaction.error?.message}`));
    };
  });
}
