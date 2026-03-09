import type { Context, Next } from 'hono'
import { supabase } from '../db/supabase.js'

/**
 * Middleware that verifies a Supabase JWT from the Authorization header.
 * Used for management-only routes (kitchen status, order listing, etc.).
 */
export async function authMiddleware(c: Context, next: Next) {
  const header = c.req.header('Authorization')
  if (!header?.startsWith('Bearer ')) {
    return c.json({ error: 'Missing or invalid Authorization header' }, 401)
  }

  const token = header.slice(7)
  const { data, error } = await supabase.auth.getUser(token)

  if (error || !data.user) {
    return c.json({ error: 'Invalid or expired token' }, 401)
  }

  c.set('user', data.user)
  await next()
}
