import path from "node:path";
import type { NextConfig } from "next";

/**
 * Where the FastAPI backend is listening.
 *
 * Overridable because `coraxis serve --port` makes the port a per-developer
 * choice, and a hardcoded destination here silently proxies to nothing when it
 * does not match.
 */
const backend = process.env.CORAXIS_BACKEND_URL ?? "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  turbopack: {
    // The repository has a lockfile at its root as well as here, and Next
    // otherwise guesses the workspace root and warns on every build. Pinning it
    // to this directory makes the build deterministic.
    root: path.resolve(__dirname),
  },

  async rewrites() {
    return [
      {
        // Everything under /api/v1 is the Coraxis API. Proxying it keeps the
        // browser same-origin, which is what lets the app avoid a CORS
        // preflight on every request.
        source: "/api/v1/:path*",
        destination: `${backend}/api/v1/:path*`,
      },
    ];
  },
};

export default nextConfig;
