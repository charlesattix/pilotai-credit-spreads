import { readFile } from 'fs/promises';

/**
 * Try reading a file from multiple candidate paths.
 * Returns the content of the first path that exists, or null if none do.
 */
export async function tryReadFile(...paths: string[]): Promise<string | null> {
  for (const p of paths) {
    try {
      return await readFile(p, 'utf-8');
    } catch {
      /* path does not exist — try next */
    }
  }
  return null;
}
