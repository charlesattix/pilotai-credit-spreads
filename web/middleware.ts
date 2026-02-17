import { NextRequest, NextResponse } from 'next/server';
import { jwtVerify } from 'jose';
import crypto from 'crypto';

function timingSafeCompare(a: string, b: string): boolean {
  const bufA = crypto.createHash('sha256').update(a).digest();
  const bufB = crypto.createHash('sha256').update(b).digest();
  return crypto.timingSafeEqual(bufA, bufB);
}

function getJwtSecret(): Uint8Array {
  const token = process.env.API_AUTH_TOKEN;
  if (!token) throw new Error('API_AUTH_TOKEN not configured');
  return new TextEncoder().encode(token);
}

// Routes that don't require authentication
const PUBLIC_PATHS = ['/api/health', '/api/auth', '/login'];

export async function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;

  // Allow public paths without auth
  for (const publicPath of PUBLIC_PATHS) {
    if (pathname === publicPath || pathname.startsWith(publicPath + '/')) {
      return NextResponse.next();
    }
  }

  // Only protect /api/* routes and allow all non-API page routes
  if (!pathname.startsWith('/api/')) {
    return NextResponse.next();
  }

  const expectedToken = process.env.API_AUTH_TOKEN;
  if (!expectedToken) {
    return NextResponse.json({ error: 'Auth not configured' }, { status: 503 });
  }

  // Strategy 1: Check Authorization: Bearer header (for Python backend / direct API calls)
  const bearerToken = request.headers.get('authorization')?.replace('Bearer ', '');
  if (bearerToken && timingSafeCompare(bearerToken, expectedToken)) {
    const response = NextResponse.next();
    const userId = 'user_' + crypto.createHash('sha256').update(bearerToken).digest('hex').substring(0, 12);
    response.headers.set('x-user-id', userId);
    return response;
  }

  // Strategy 2: Check session cookie with JWT verification (for browser calls)
  const sessionCookie = request.cookies.get('session')?.value;
  if (sessionCookie) {
    try {
      const { payload } = await jwtVerify(sessionCookie, getJwtSecret());
      const userId = payload.userId as string;
      if (userId) {
        const response = NextResponse.next();
        response.headers.set('x-user-id', userId);
        return response;
      }
    } catch {
      // JWT invalid or expired — fall through to unauthorized
    }
  }

  return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
}

export const config = {
  matcher: '/api/:path*',
};
