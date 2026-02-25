import { readFileSync } from 'fs';
import path from 'path';
import { NextResponse } from 'next/server';

export async function GET() {
  const html = readFileSync(path.join(process.cwd(), 'public', 'dashboard.html'), 'utf-8');
  return new NextResponse(html, {
    headers: { 'Content-Type': 'text/html' },
  });
}

export const dynamic = 'force-dynamic';
