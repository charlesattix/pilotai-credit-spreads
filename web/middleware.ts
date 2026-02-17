import { NextResponse } from 'next/server';

/**
 * Middleware is intentionally minimal — just passes requests through.
 * Auth is handled per-route when API_AUTH_TOKEN is set.
 *
 * Previous attempts to do auth in middleware caused production 503 errors
 * because the jose JWT library failed to load in the Next.js Edge Runtime
 * standalone build.
 */
export function middleware() {
  return NextResponse.next();
}

export const config = {
  matcher: '/api/:path*',
};
