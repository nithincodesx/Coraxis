declare module "firebase/app" {
  export interface FirebaseOptions {
    apiKey?: string;
    authDomain?: string;
    projectId?: string;
    storageBucket?: string;
    messagingSenderId?: string;
    appId?: string;
    [key: string]: unknown;
  }
  export class FirebaseApp {}
  export function initializeApp(options: FirebaseOptions): FirebaseApp;
}

declare module "firebase/auth" {
  import { FirebaseApp } from "firebase/app";

  export interface User {
    uid: string;
    email: string | null;
    emailVerified: boolean;
    displayName: string | null;
    photoURL: string | null;
    getIdToken(forceRefresh?: boolean): Promise<string>;
  }
  export interface UserCredential {
    user: User;
  }
  export class Auth {
    currentUser: User | null;
  }
  export class GithubAuthProvider {
    constructor();
    addScope(scope: string): this;
  }
  export function getAuth(app?: FirebaseApp): Auth;
  export function signInWithPopup(
    auth: Auth,
    provider: GithubAuthProvider
  ): Promise<UserCredential>;
  export function signInWithEmailAndPassword(
    auth: Auth,
    email: string,
    password: string
  ): Promise<UserCredential>;
  export function createUserWithEmailAndPassword(
    auth: Auth,
    email: string,
    password: string
  ): Promise<UserCredential>;
  export function updateProfile(
    user: User,
    profile: { displayName?: string | null; photoURL?: string | null }
  ): Promise<void>;
  export function signOut(auth: Auth): Promise<void>;
  export function onAuthStateChanged(
    auth: Auth,
    callback: (user: User | null) => void
  ): () => void;
}

declare module "firebase/storage" {
  import { FirebaseApp } from "firebase/app";

  export class FirebaseStorage {}
  export function getStorage(app?: FirebaseApp): FirebaseStorage;
  export function ref(storage: FirebaseStorage, path: string): any;
  export function uploadBytes(ref: any, file: File): Promise<{ ref: any }>;
  export function getDownloadURL(ref: any): Promise<string>;
}
