import { NextResponse } from 'next/server';

/**
 * Middleware is intentionally minimal — just passes requests through.
 * Auth is enforced per-route via `lib/auth.ts` (verifyAuth helper).
 *
 * Previous attempts to do auth in middleware caused production 503 errors
 * because the jose JWT library failed to load in the Next.js Edge Runtime
 * standalone build.  The per-route approach runs in Node.js runtime and
 * avoids Edge Runtime limitations.
 */
export function middleware() {
  return NextResponse.next();
}

export const config = {
  matcher: '/api/:path*',
};
