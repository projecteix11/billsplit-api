import { Hono } from 'hono'
import { authMiddleware } from '../middleware/auth.js'
import * as ordersService from '../services/orders.service.js'

const app = new Hono()

// Kitchen status — management only
app.patch('/order-items/:itemId/kitchen-status', authMiddleware, async (c) => {
  const itemId = c.req.param('itemId')!
  const { status } = await c.req.json()
  const validStatuses = ['pending', 'cooking', 'ready', 'delivered'] as const

  if (!validStatuses.includes(status)) {
    return c.json({ error: `status must be one of: ${validStatuses.join(', ')}` }, 400)
  }

  await ordersService.updateItemKitchenStatus(itemId, status)
  return c.json({ data: null, error: null })
})

// Payment status — client (mark items as paid)
app.patch('/order-items/payment-status', async (c) => {
  const { itemIds, status } = await c.req.json()
  const validStatuses = ['unassigned', 'assigned', 'paid'] as const

  if (!Array.isArray(itemIds) || itemIds.length === 0) {
    return c.json({ error: 'itemIds[] is required' }, 400)
  }
  if (!validStatuses.includes(status)) {
    return c.json({ error: `status must be one of: ${validStatuses.join(', ')}` }, 400)
  }

  await ordersService.updateItemsPaymentStatus(itemIds, status)
  return c.json({ data: null, error: null })
})

export default app
