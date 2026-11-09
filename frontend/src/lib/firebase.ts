/**
 * Firebase client: authentication (GitHub OAuth, email/password) and storage.
 *
 * Firebase owns identity. After signing in, the frontend sends the Firebase ID
 * token as the `Authorization: Bearer <id token>` header on every API request,
 * and the backend verifies it and maps the account to a Coraxis user by email.
 *
 * Required env vars (prefixed `NEXT_PUBLIC_` so the browser can read them):
 *   NEXT_PUBLIC_FIREBASE_API_KEY
 *   NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN
 *   NEXT_PUBLIC_FIREBASE_PROJECT_ID
 *   NEXT_PUBLIC_FIREBASE_STORAGE_BUCKET
 *   NEXT_PUBLIC_FIREBASE_MESSAGING_SENDER_ID
 *   NEXT_PUBLIC_FIREBASE_APP_ID
 *
 * Copy `.env.example` values into a frontend `.env.local` (or your host's
 * runtime config) and run `firebase login` / `firebase use --add` to target
 * your project.
 */

"use client";

import {
  getAuth,
  GithubAuthProvider,
  signInWithPopup,
  signInWithEmailAndPassword,
  createUserWithEmailAndPassword,
  updateProfile,
  signOut as firebaseSignOut,
  onAuthStateChanged,
  type User as FirebaseUser,
  type Auth,
} from "firebase/auth";

import {
  getStorage,
  ref as storageRef,
  uploadBytes,
  getDownloadURL,
  type FirebaseStorage,
} from "firebase/storage";

import { initializeApp, type FirebaseApp } from "firebase/app";

let app: FirebaseApp | null = null;
let authInstance: Auth | null = null;
let storageInstance: FirebaseStorage | null = null;

function firebaseConfig() {
  return {
    apiKey: process.env.NEXT_PUBLIC_FIREBASE_API_KEY,
    authDomain: process.env.NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN,
    projectId: process.env.NEXT_PUBLIC_FIREBASE_PROJECT_ID,
    storageBucket: process.env.NEXT_PUBLIC_FIREBASE_STORAGE_BUCKET,
    messagingSenderId: process.env.NEXT_PUBLIC_FIREBASE_MESSAGING_SENDER_ID,
    appId: process.env.NEXT_PUBLIC_FIREBASE_APP_ID,
  };
}

export function initFirebase(): FirebaseApp | null {
  if (app) return app;
  const config = firebaseConfig();
  if (!config.apiKey || !config.projectId || !config.appId) {
    return null;
  }
  app = initializeApp(config);
  authInstance = getAuth(app);
  storageInstance = getStorage(app);
  return app;
}

export function isFirebaseConfigured(): boolean {
  const config = firebaseConfig();
  return Boolean(config.apiKey && config.projectId && config.appId);
}

export function getFirebaseAuth(): Auth | null {
  if (!authInstance) initFirebase();
  return authInstance;
}

export function getFirebaseStorage(): FirebaseStorage | null {
  if (!storageInstance) initFirebase();
  return storageInstance;
}

function requireFirebase(): Auth {
  const auth = getFirebaseAuth();
  if (!auth) {
    throw new Error(
      "Firebase is not configured. Set the NEXT_PUBLIC_FIREBASE_* environment variables."
    );
  }
  return auth;
}

/** Sign in with GitHub OAuth via a popup. */
export async function signInWithGitHub(): Promise<FirebaseUser> {
  const auth = requireFirebase();
  const provider = new GithubAuthProvider();
  provider.addScope("read:user");
  const result = await signInWithPopup(auth, provider);
  return result.user;
}

/** Sign in with email + password. */
export async function signInWithEmail(
  email: string,
  password: string
): Promise<FirebaseUser> {
  const auth = requireFirebase();
  const result = await signInWithEmailAndPassword(auth, email, password);
  return result.user;
}

/** Create an account with email + password and set the display name. */
export async function signUpWithEmail(
  email: string,
  password: string,
  displayName: string
): Promise<FirebaseUser> {
  const auth = requireFirebase();
  const result = await createUserWithEmailAndPassword(auth, email, password);
  await updateProfile(result.user, { displayName: displayName || "" });
  return result.user;
}

/** Sign out of Firebase. */
export async function signOut(): Promise<void> {
  const auth = requireFirebase();
  await firebaseSignOut(auth);
}

/** The currently signed-in Firebase user, or null. */
export function getCurrentFirebaseUser(): FirebaseUser | null {
  const auth = getFirebaseAuth();
  if (!auth) return null;
  return auth.currentUser;
}

/** Force-refresh and return the Firebase ID token used as the bearer token. */
export async function getIdToken(forceRefresh = false): Promise<string | null> {
  const user = getCurrentFirebaseUser();
  if (!user) return null;
  return user.getIdToken(forceRefresh);
}

/** Subscribe to Firebase auth state changes. Returns an unsubscribe function. */
export function onAuthStateChange(
  callback: (user: FirebaseUser | null) => void
): () => void {
  const auth = getFirebaseAuth();
  if (!auth) return () => {};
  return onAuthStateChanged(auth, callback);
}

/**
 * Upload a file to Firebase Storage under a user-owned path and return its
 * public download URL. Used for report attachments and user uploads.
 */
export async function uploadFile(
  userId: string,
  path: string,
  file: File
): Promise<string> {
  const storage = getFirebaseStorage();
  if (!storage) {
    throw new Error(
      "Firebase is not configured. Set the NEXT_PUBLIC_FIREBASE_* environment variables."
    );
  }
  const fullPath = `users/${userId}/${path}`;
  const snapshot = await uploadBytes(storageRef(storage, fullPath), file);
  return getDownloadURL(snapshot.ref);
}

export type { FirebaseUser };
