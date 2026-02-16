import { NextRequest, NextResponse } from 'next/server';
import crypto from 'crypto';

function timingSafeCompare(a: string, b: string): boolean {
  const bufA = crypto.createHash('sha256').update(a).digest();
  const bufB = crypto.createHash('sha256').update(b).digest();
  return crypto.timingSafeEqual(bufA, bufB);
}

export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;

  // Only protect /api/* routes
  if (!pathname.startsWith('/api/')) {
    return NextResponse.next();
  }

  // Allow unauthenticated access to health endpoint
  if (pathname === '/api/health') {
    return NextResponse.next();
  }

  const token = request.headers.get('authorization')?.replace('Bearer ', '');
  const expectedToken = process.env.API_AUTH_TOKEN;

  if (!expectedToken) {
    // If no token configured, deny all (fail closed)
    return NextResponse.json({ error: 'Auth not configured' }, { status: 503 });
  }

  if (!token || !timingSafeCompare(token, expectedToken)) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  }

  // Pass userId derived from token via header
  const response = NextResponse.next();
  // Derive a stable userId from the token (simple hash)
  const userId = 'user_' + simpleHash(token);
  response.headers.set('x-user-id', userId);
  return response;
}

function simpleHash(str: string): string {
  let hash = 0;
  for (let i = 0; i < str.length; i++) {
    const char = str.charCodeAt(i);
    hash = ((hash << 5) - hash) + char;
    hash |= 0;
  }
  return Math.abs(hash).toString(36);
}

export const config = {
  matcher: '/api/:path*',
};
