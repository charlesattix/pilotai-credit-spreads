import { NextRequest, NextResponse } from 'next/server';
import { jwtVerify } from 'jose';

async function sha256(input: string): Promise<ArrayBuffer> {
  return crypto.subtle.digest('SHA-256', new TextEncoder().encode(input));
}

async function timingSafeCompare(a: string, b: string): Promise<boolean> {
  const [bufA, bufB] = await Promise.all([sha256(a), sha256(b)]);
  const viewA = new Uint8Array(bufA);
  const viewB = new Uint8Array(bufB);
  if (viewA.length !== viewB.length) return false;
  let result = 0;
  for (let i = 0; i < viewA.length; i++) {
    result |= viewA[i] ^ viewB[i];
  }
  return result === 0;
}

function getJwtSecret(): Uint8Array {
  const token = process.env.API_AUTH_TOKEN;
  if (!token) throw new Error('API_AUTH_TOKEN not configured');
  return new TextEncoder().encode(token);
}

// Routes that don't require authentication
const PUBLIC_PATHS = ['/api/health', '/api/auth', '/api/positions', '/api/alerts', '/api/paper-trades', '/login'];

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
    // Auth not configured — allow all requests (single-user / development mode)
    return NextResponse.next();
  }

  // Strategy 1: Check Authorization: Bearer header (for Python backend / direct API calls)
  const bearerToken = request.headers.get('authorization')?.replace('Bearer ', '');
  if (bearerToken && await timingSafeCompare(bearerToken, expectedToken)) {
    const response = NextResponse.next();
    const hashBuf = await sha256(bearerToken);
    const userId = 'user_' + Array.from(new Uint8Array(hashBuf)).map(b => b.toString(16).padStart(2, '0')).join('').substring(0, 12);
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
